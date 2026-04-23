# Layer 1 数据处理层 · 设计 v2

> **文档性质**：替代 `技术文档智能问答与引用溯源系统.md` §1.1-§1.5 的定稿版本。  
> **起草**：2026-04-22  
> **基于**：原架构文档 + `docs/layer1-design-review.md`（P0-P2 优化项）+ 评测框架实测反馈  
> **目标读者**：全体开发成员 + 非技术背景队员（含术语表，大白话可读）  
> **状态**：待团队讨论确认，标注 ✅ 的为已内置决策，❓ 的需当面对齐

---

## 0. 设计说明：怎么读这份文档

1. 技术决策带 ✅ 标记，不再讨论；带 ❓ 的需当面拍板
2. 每个子章节有「设计 / 为什么这么做 / 代码示例 / 接口契约」四部分
3. 不懂的术语看文末【术语表】（与 layer1-design-review.md 同一份）
4. **只看核心的，跳到 §2（核心决策摘要）**，30 秒把握全貌

---

## 1. 设计目标与约束

### 赛题要求（原文抄送）

1. 对评委会给定的文档集构建检索问答系统
2. 每次回答必须附带至少一条出处（文档路径 + 段落 anchor）
3. 对文档中不存在答案的问题，必须明确拒答而非幻觉
4. 支持文档增量更新（新增 / 修改 / 删除后 5 分钟内生效）
5. 提供 WebUI 供评委交互

### Layer 1 专属目标

| # | 目标 | 验收标准 |
|---|---|---|
| L1-G1 | 多格式文档解析 | md / pdf / docx / xlsx / pptx / html 至少跑通，中文 OCR 可用 |
| L1-G2 | 稳定的 Chunking | token 数对齐 embedding 模型，边界场景不丢内容 |
| L1-G3 | Anchor 精确定位 | char_offset 级，UI 点击可跳转 |
| L1-G4 | 增量更新 ≤ 5min | 小文档 < 1min，中 < 3min，大异步完成 |
| L1-G5 | 数据一致性 | 任意失败点不丢数据，幂等重试 |
| L1-G6 | 与 Layer 2/3 接口稳定 | 接口定义一次，后续不重构 |

### 约束

- **时间**：19 个自然日（2026-04-22 → 2026-05-10 18:00），但**功能开发只有 10 天**，剩余 9 天必须留给联调、评委语料适配、提交准备（见 §6 路线图）
- **规模**：初赛语料估 50MB 级，~几百到几千文件
- **红线**：所有 LLM / embedding 调用必须走**统一 LLM 网关**
- **网关已知支持模型**（v2.4 更新）：
  - **聊天类**：`glm5` / `kimi` / `minimax` / `qwen 3.6`
  - **Embedding / Rerank**：**待确认**，见 §7 Q1
- **部署**：Docker Compose 一键起
- **协作依赖**：Layer 2（海军，reranker/检索）、Layer 3（推理/引用）、Layer 4（前端 UI），**接口契约锁死**，不能单独改

---

## 2. 核心决策摘要（30 秒把握全貌）

| 维度 | 决策 | 对比原设计 |
|---|---|---|
| **存储** ✅ | SQLite + FTS5 + 向量列 | ❌ 不切 Elasticsearch（时间不够） |
| **Chunking 实现语言** ✅ | Node（TS），对接 Express 主服务 | ✅ 与原设计的 Python 解耦，集成更简单 |
| **重活语言** ✅ | Python 微服务 `rag-service`（embedding + reranker + OCR） | ✅ 保留设计意图，但只做 Node 做不了的 |
| **Embedding 模型** ❓ | 通过 config 注入，默认走统一网关（模型名由 env 决定），schema 不绑定具体模型 | 需要先查网关能力（Q1），**schema 不假设具体模型和维度** |
| **三路召回** ✅ | 砍掉 ColBERT Sparse，保留 BM25 + Dense + Reranker | ❌ 原设计三路召回 → 两路 + reranker |
| **Anchor 格式** ✅ | `file_path#chunk_id` + `char_offset_start`（辅助）| ✅ v2.2 修正原设计：单靠 char_offset 在增量更新后会漂移 |
| **Chunking 策略** ✅ | 按 content_type 分派：document（三级 fallback） / code（语言感知） / structured_data（按 key） | ✅ 扩展原设计 |
| **支持格式范围** ✅ | 文档类（md/txt/html/pdf/docx/doc/xlsx/xls/pptx/ppt） + 代码类（py/java/cpp/sql/json/yaml/xml/html） | ✅ 扩展原设计（补代码、补旧版 Office） |
| **旧版 Office** ✅ | LibreOffice headless 先转成新格式再解析 | ✅ 原设计未覆盖 |
| **增量粒度** ✅ | **chunk 级 diff**（非文件级） | ✅ 优化原设计 |
| **事件 debounce** ✅ | 1 秒抖动抑制 | ✅ 原设计未覆盖 |
| **SLA 分级** ✅ | 小 < 1min / 中 < 3min / 大异步 + 进度条 | ✅ 放宽原设计过于乐观时间表 |
| **孤儿 GC** ✅ | 启动时 + 每小时扫描 | ✅ 原设计未覆盖 |

---

## 3. 数据流总览

```
┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│    WebUI 上传            外部 cp 文件到 raw/                     │
│       │                        │                                 │
│       │                        ▼                                 │
│       │                  chokidar 监听                           │
│       │                        │                                 │
│       └──────┬─────────────────┘                                 │
│              ▼  (debounce 1s)                                    │
│        ┌──────────────────────┐                                  │
│        │   index_pipeline     │  ← 文件级互斥锁                  │
│        └──────────┬───────────┘                                  │
│                   │                                              │
│        1. 算 SHA-256 hash                                        │
│           hash 未变？ → 结束                                     │
│                   │                                              │
│        2. parse_document  ─────→  Python rag-service /parse     │
│           （根据扩展名选解析器）    （Docling / Unstructured /    │
│                   │                  PaddleOCR）                 │
│                   │                                              │
│           输出: { raw_text, title_path[], line_mapping }         │
│                   │                                              │
│        3. chunker.split_markdown                                 │
│           （Node 内置，段落→句子→硬切三级）                      │
│                   │                                              │
│           输出: Chunk[] (chunk_id, content, anchor, title_path)  │
│                   │                                              │
│        4. chunk-level diff                                       │
│           to_add / to_delete / unchanged                         │
│                   │                                              │
│        5. batch embed (to_add only)  ───→  rag-service /embed    │
│           （≤ 8 并发, rate limit 感知）                          │
│                   │                                              │
│        6. 写入 SQLite (先写新 version)                           │
│           更新 documents 表 (version 切换，原子)                 │
│           删除 old version chunks                                │
│                   │                                              │
│        7. 更新索引状态 = indexed                                 │
│                                                                  │
│                   ▼                                              │
│           WebSocket 推送进度给前端                               │
└─────────────────────────────────────────────────────────────────┘
```

---

## 4. 详细设计

### 4.1 文档解析

**设计**：

- 按**扩展名 + MIME sniff**路由到对应解析器，统一输出 `ParseResult`
- 解析器分三类：**Node 内置 / Python rag-service / 转格式后再解析**
- 输入文件按**内容类型**（文档 / 代码 / 结构化数据）决定不同的 chunking 策略（详见 §4.2）

#### 4.1.1 支持格式与解析器路由

**文档类**（人写给人看的文本）：

| 扩展名 | 解析器 | 处理方式 | 优先级 |
|---|---|---|---|
| `.md` | Node 内置（`marked`） ✅ | 直读 | P0 |
| `.txt` | Node 内置 | 直读，按扩展名推测编码 | P0 |
| `.html` | Node 内置（`cheerio` + html2md） | 转 markdown 后走 md 路径 | P0 |
| `.pdf`（文字版） | `Unstructured`（Python） | 通过 rag-service | P0 |
| `.pdf`（扫描版） | `PaddleOCR`（Python） | 通过 rag-service，中文强 | P1 |
| `.docx` | `mammoth`（Node）→ md | 现有实现可用，P1 升级 Unstructured | P0 |
| `.doc`（旧版） | **LibreOffice 转 .docx** → mammoth | 需要额外依赖 | P1 |
| `.xlsx` | `xlsx`（Node） | 按 sheet 转 markdown 表格（现有） | P0 |
| `.xls`（旧版） | **LibreOffice 转 .xlsx** → xlsx | - | P1 |
| `.pptx` | `Unstructured`（Python） | 每 slide 一个段落 | P1 |
| `.ppt`（旧版） | **LibreOffice 转 .pptx** → pptx 处理 | - | P1 |

**代码类**（给机器执行的文本，结构不同于文档）：

| 扩展名 | 语言 | 处理方式 | chunking 特殊规则 |
|---|---|---|---|
| `.py` | Python | 直读 + 语言感知切分 | 按 `^class` / `^def` / `^async def` 切 |
| `.java` | Java | 直读 + 语言感知切分 | 按 class / method 切 |
| `.cpp` / `.hpp` / `.cc` / `.h` | C/C++ | 直读 + 语言感知切分 | 按函数定义切 |
| `.sql` | SQL | 直读 + 语句切分 | 按 `;` + 空行切 |
| `.json` | JSON | 结构化解析 | 小文件 1 chunk；大文件按顶层 key 切 |
| `.yaml` / `.yml` | YAML | 结构化解析 | 按顶层 key 切；保留注释 |
| `.xml` | XML | 结构化解析 | 按根 tag 切 |
| `.html`（代码视角） | HTML | 如果是文档版直转 md；如果是源码保留结构 | 见下注 |

**注**：`.html` 有二义性——可以是"网页文档"（→ 转 markdown 走文档路径）也可以是"源码"（→ 保留标签结构走代码路径）。**启发式规则**：如果文件含 `<body>` 标签且以 HTML 布局为主，走文档；否则走代码。

#### 4.1.2 旧版 Office 格式的处理

`.doc` / `.xls` / `.ppt` 是 Microsoft Office 97-2003 的**二进制格式**，新版的 `mammoth` / `xlsx` / `python-pptx` 都不支持。**统一方案**：在 `rag-service` 里用 **LibreOffice headless** 先转成新版格式：

```python
# rag-service/legacy_office.py
import subprocess

def convert_legacy_office(src_path: str) -> str:
    """把 .doc/.xls/.ppt 转成 .docx/.xlsx/.pptx"""
    out_dir = tempfile.mkdtemp()
    subprocess.run([
        "libreoffice", "--headless", "--convert-to", 
        {"doc": "docx", "xls": "xlsx", "ppt": "pptx"}[src_ext],
        "--outdir", out_dir, src_path
    ], check=True, timeout=60)
    return os.path.join(out_dir, new_filename)
```

**成本**：
- Docker 镜像 +300MB（LibreOffice）
- 转换耗时：小文件 3-5 秒，大文件 10-30 秒
- 兼容性：LibreOffice 对 MS 格式的兼容度 95%+

**替代方案**：用 Python `textract`（封装了多种解析器），但依赖更杂乱；或 Apache Tika（Java，又要起 JVM）。LibreOffice 综合最稳。

#### 4.1.3 代码类文件的特殊处理

代码不是"段落文档"，需要特殊对待：

**① 编码检测**：源码可能是 UTF-8 / GBK / Latin-1。用 `chardet` 检测后统一转 UTF-8。

**② 不生成 title_tree**：代码没有 heading 概念，`title_tree = []`。但可以用**函数/类名**作为 title_path 的近似：

```python
# Python 文件解析示例
def parse_python(content: str) -> ParseResult:
    tree = ast.parse(content)
    structure = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)):
            structure.append({
                "name": node.name,
                "type": type(node).__name__,
                "line_start": node.lineno,
                "char_offset": get_char_offset(content, node.lineno),
            })
    return ParseResult(
        raw_text=content,
        title_tree=build_title_tree_from_code(structure),  # 函数名当 heading
        confidence=1.0,
        content_type="code",
        language="python",
    )
```

**③ 保留原始格式**：代码的缩进、换行、空格**都有意义**，不能像文档那样合并空白。

**④ 注释单独标记**（P1 优化）：检索时可以用不同权重处理注释和代码体。

#### 4.1.4 统一输出格式（扩展）

```typescript
interface ParseResult {
  file_path: string;
  raw_text: string;                   // 解析后统一文本
  title_tree: TitleNode[];            // 可为空（代码文件 / 纯 txt）
  confidence: number;                 // 0-1，解析置信度
  content_type: "document" | "code" | "structured_data";  // ⭐新增
  language?: string;                  // ⭐新增：zh / en / python / java / sql / ...
  metadata: {                         // ⭐新增：格式专属元数据
    pdf_pages?: number;
    pdf_is_scanned?: boolean;
    code_functions?: string[];        // 代码文件里的函数名列表
    sheet_names?: string[];           // xlsx 的 sheet 名
  };
}

interface TitleNode {
  level: number;
  text: string;
  char_offset_start: number;
  children: TitleNode[];
  confidence?: number;                // PDF 靠字体猜的 heading 带置信度
}
```

**接口**：

```
POST http://rag-service:8000/parse
Content-Type: application/json
Body:
{
  "file_path": "/data/docs/pods.md",         // 绝对路径（在共享 volume 内）
  "format": "md",                             // 可选，rag-service 自己从扩展名推断
  "hint_language": "zh"                       // 可选，"zh" | "en" | "auto"
}

→ ParseResult (JSON)
```

**为什么传路径而非二进制**（详见 §4.4.0）：
- Node 和 rag-service 共享 `/data/docs/` volume
- 大 PDF（> 50MB）走 HTTP multipart 易超时、易失败
- 避免大文件反复 serialize/deserialize

#### 4.1.5 决策与权衡

- ✅ **Node 处理 md/txt/html/docx/xlsx**（现有能力 + 复用代码）
- ✅ **Python 处理 pdf/pptx/代码 AST/旧版 Office**（生态强）
- ✅ **LibreOffice 统一旧版 Office 转换**（避免维护多套二进制格式解析器）
- ✅ **输出分 document / code / structured_data 三类**，给 chunker 用
- ✅ **代码不 OCR**（源码不可能是扫描件）
- ✅ **MIME sniff 兜底**：用户可能改扩展名（比如把 .txt 改成 .md），用 `file-type`（Node）/ `python-magic`（Python）二次确认

#### 4.1.6 P1 / P2 细节

- **P1**：title_tree 带 `confidence`，低置信度时 UI 隐藏章节
- **P1**：v1 PDF 不 OCR 图片内容；v2 加
- **P2**：`.ipynb`（Jupyter）支持——既是 JSON 又是代码 + markdown，需要特殊解析
- **P2**：`.rst`（reStructuredText）支持——Python 文档常用
- **P2**：代码注释 vs 代码体分权重检索

---

### 4.2 Chunking

**设计**：按 `content_type` **分派到三套切分策略**，都走同一个 Node 模块。

```typescript
// src/chunker/index.ts
const MAX_CHARS = 1500;         // 经验值：对常见 embedding 模型（bge-m3 / text-embedding-3-*）输入都在上限内
const OVERLAP_CHARS = 200;      // 重叠

export function chunkDocument(parseResult: ParseResult): Chunk[] {
  switch (parseResult.content_type) {
    case "document":
      return splitDocument(parseResult);         // 散文 / Markdown / PDF 正文
    case "code":
      return splitCode(parseResult);             // 源码（py/java/cpp/sql）
    case "structured_data":
      return splitStructuredData(parseResult);   // json/yaml/xml
    default:
      return splitByChars(parseResult.raw_text); // 兜底
  }
}
```

#### 4.2.1 document 类型：段落 → 句子 → 硬切 三级 fallback

（适用于 md / pdf / docx / pptx / html / txt 转出的 markdown）

```typescript
function splitDocument(pr: ParseResult): Chunk[] {
  // 第一步：按 title 切成大段
  const sections = splitByTitles(text, titleTree);

  const chunks: Chunk[] = [];
  for (const section of sections) {
    if (section.content.length <= MAX_CHARS) {
      chunks.push(makeChunk(section));
      continue;
    }
    
    // 第 1 级：段落边界（\n\n）
    const paragraphs = section.content.split(/\n\n+/);
    for (const para of paragraphs) {
      if (para.length <= MAX_CHARS) {
        chunks.push(makeChunk({ ...section, content: para }));
        continue;
      }
      
      // 第 2 级：句子边界（。！？. ! ?）
      const sentences = splitSentences(para);
      let buf: string[] = [];
      let bufLen = 0;
      for (const sent of sentences) {
        if (bufLen + sent.length > MAX_CHARS) {
          if (buf.length > 0) chunks.push(makeChunk(...));
          buf = [sent];
          bufLen = sent.length;
        } else {
          buf.push(sent);
          bufLen += sent.length;
        }
      }
      if (buf.length > 0) chunks.push(makeChunk(...));
      
      // 第 3 级：硬切（带 is_truncated 标记）
      // 只在单句都 > MAX_CHARS 时触发
    }
  }
  
  // 添加重叠（取前一 chunk 的末尾 200 字符拼到下一 chunk 前面）
  return addOverlap(chunks, OVERLAP_CHARS);
}
```

#### 4.2.2 code 类型：语言感知的结构化切分

代码不能像文档那样按段落切，会把函数切一半。策略：**按"顶级定义"为天然边界**，超长函数再降级。

```typescript
function splitCode(pr: ParseResult): Chunk[] {
  const { raw_text, language, metadata } = pr;
  
  // 第 1 级：按语言的"顶级定义"边界切
  const topLevelBlocks = splitByTopLevelDefinitions(raw_text, language);
  
  const chunks: Chunk[] = [];
  for (const block of topLevelBlocks) {
    if (block.content.length <= MAX_CHARS) {
      chunks.push(makeChunk({
        ...block,
        title_path: block.definition_name,  // 函数名/类名当 title_path
      }));
      continue;
    }
    
    // 第 2 级：超长函数按逻辑块切（空行分隔）
    // 代码里空行通常分隔逻辑段
    const logicalBlocks = block.content.split(/\n{2,}/);
    let buf: string[] = [];
    let bufLen = 0;
    for (const lb of logicalBlocks) {
      if (bufLen + lb.length > MAX_CHARS && buf.length > 0) {
        chunks.push(makeChunk({ ...block, content: buf.join("\n\n") }));
        buf = [lb];
        bufLen = lb.length;
      } else {
        buf.push(lb);
        bufLen += lb.length;
      }
    }
    if (buf.length > 0) chunks.push(makeChunk({ ...block, content: buf.join("\n\n") }));
    
    // 第 3 级：如果单个逻辑块还 > MAX_CHARS，硬切（极少见）
  }
  
  // 注意：代码 chunk 不加 overlap（语法上会出错）
  return chunks;
}

// 各语言的"顶级定义"匹配规则
// P2-10 修正：支持装饰器/注解/缩进/嵌套的常见场景
function splitByTopLevelDefinitions(text: string, lang: string): CodeBlock[] {
  const patterns: Record<string, RegExp> = {
    // Python：允许装饰器前缀（@...\n），允许类内方法（缩进 4 或 tab）
    // 注意：仅顶层的 class/def 和紧跟 @decorator 的 def 作为边界
    python: /^(?:@[\w.]+(?:\([^)]*\))?\s*\n)*(?:class\s+\w+|def\s+\w+|async\s+def\s+\w+)/gm,
    
    // Java：允许注解（@Override 等），允许 public/private/protected 前缀
    java:   /^(?:\s*@\w+(?:\([^)]*\))?\s*\n)*\s*(?:public|private|protected)?\s*(?:static\s+)?(?:final\s+)?(?:class|interface|enum|void|\w+)\s+\w+\s*[({<]/gm,
    
    // C/C++：函数定义（简化版，不处理所有模板场景）
    cpp:    /^(?:template\s*<[^>]+>\s*\n)?(?:class\s+\w+|struct\s+\w+|(?:\w[\w\s*&:<>]*\s+)?\w+\s*\([^)]*\)\s*(?:const)?\s*\{)/gm,
    
    // SQL：按语句关键字切
    sql:    /(?:^|;\s*\n)(CREATE|SELECT|INSERT|UPDATE|DELETE|ALTER|DROP|WITH)\s+/gmi,
  };
  
  if (!patterns[lang]) {
    // 不认识的语言：整个文件作为一个 block（P2-10 fallback）
    return [{ content: text, definition_name: null, char_offset_start: 0 }];
  }
  
  const matches = [...text.matchAll(patterns[lang])];
  
  // 如果没匹配到任何定义（例如一个纯脚本没有 class/def），也 fallback
  if (matches.length === 0) {
    return [{ content: text, definition_name: null, char_offset_start: 0 }];
  }
  
  // 两两之间就是一个 block
  const blocks = matches.map((m, i) => ({
    definition_name: extractName(m[0], lang),
    content: text.slice(m.index!, matches[i+1]?.index ?? text.length),
    char_offset_start: m.index!,
  }));
  
  // 第一个匹配之前的"preamble"（import、注释等）如果非空，合并到第一个 block
  if (matches[0].index! > 0) {
    const preamble = text.slice(0, matches[0].index!);
    if (preamble.trim().length > 0) {
      blocks[0].content = preamble + blocks[0].content;
      blocks[0].char_offset_start = 0;
    }
  }
  
  return blocks;
}
```

**已知局限**（P2 可迭代）：
- **嵌套类**：内部类的方法不会被切成独立 chunk（和外层类一起）。通常这是好的，因为内部类和外层语义上一体。
- **Lambda / 匿名函数**：不切。也是合理的，它们从属于外层函数。
- **复杂 C++ 模板 / 宏定义**：覆盖不全。P2 优化时可用 `tree-sitter` 做真正的 AST 解析。

**关键点**：
- ✅ **不加 overlap**：代码加 overlap 会让同一函数的签名出现在多个 chunk 里，检索重复
- ✅ **函数名 / 类名当 title_path**：给 LLM 和 UI 一个"这段代码是做什么的"的上下文
- ✅ **SQL 按语句切**：每条 CREATE / SELECT 独立一个 chunk
- ✅ **保留原始格式**：缩进 / 换行 / 注释全部保留，不做任何归一化
- ✅ **语言不识别时的 fallback**：整个文件一个 chunk（小文件）或按 char 硬切（大文件）

#### 4.2.3 structured_data 类型：按顶层 key / 节点切

（json / yaml / xml）

```typescript
function splitStructuredData(pr: ParseResult): Chunk[] {
  const { raw_text, language } = pr;
  
  // 小文件直接一个 chunk
  if (raw_text.length <= MAX_CHARS) {
    return [makeChunk({ 
      content: raw_text, 
      title_path: null, 
      char_offset_start: 0 
    })];
  }
  
  // 大文件按顶层 key 切
  if (language === "json" || language === "yaml") {
    return splitByTopLevelKeys(raw_text, language);
  }
  if (language === "xml") {
    return splitByRootChildren(raw_text);
  }
  
  return splitByChars(raw_text);  // fallback
}
```

**例子**：
```yaml
# docker-compose.yml（500 行）
version: '3'
services:     ← 顶层 key 1
  backend: ...
  frontend: ...
volumes:      ← 顶层 key 2
  data: ...
networks:     ← 顶层 key 3
  ...
```

切出来 3 个 chunk，每个带 title_path: `services` / `volumes` / `networks`。

**关键点**：
- ✅ **解析失败时降级为纯文本**：畸形 JSON 也能入库
- ✅ **每个 chunk 要自包含语法**：不能把 `{ "a": 1 }` 切成 `{ "a":` 和 `1 }`（用 parser 不是 split）
- ✅ **title_path 用 key 路径**：`services.backend`

#### 4.2.4 共用：Chunk 数据结构

**⚠️ v2.4 关键重构（Rank 1）**：把字段分成"**内容相关**（跨版本复用）"和"**版本相关**（每次索引可变）"两组，在两张表里各存一部分。Layer 2/3 看到的 `Chunk` 形状是两表 JOIN 后的合并视图。

```typescript
// Chunk 合并视图（查询时由 storage 层 JOIN 产出）
interface Chunk {
  // ========== 来自 chunks 表（内容相关，跨版本稳定） ==========
  chunk_id: string;              // sha256(file_path + content[:500] + occurrence_seq)
  file_path: string;
  content: string;
  content_type: "document" | "code" | "structured_data";
  language?: string;
  char_count: number;
  embedding?: number[];
  embedding_model?: string;
  embedding_dim?: number;

  // ========== 来自 chunk_versions 表（版本相关，每次索引可变） ==========
  // ⭐ v2.4：放在 chunk_versions 是因为同一内容在不同版本里位置/章节可能都变
  char_offset_start: number;     // 当前 active 版本下的位置
  char_offset_end: number;
  chunk_index: number;           // 当前 active 版本下的顺序
  title_path: string | null;     // 当前 active 版本下的章节（章节结构可重构）
  is_truncated: boolean;

  // ========== 计算字段（不存，访问时生成） ==========
  // anchor_id = `${file_path}#${chunk_id}`
  // 不作为存储列，避免"存的值 vs 计算值"的一致性风险
}
```

**为什么要把 char_offset / title_path / chunk_index 分离出去**（v2.4 修正）：

假设同一段话"Pod 是最小调度单元"：
- v1 的文档里：位于 offset 100，title_path = "Pod > 基础"
- 用户在前面插入了一章 → v2 的文档里：位于 offset 800，title_path = "Kubernetes > Pod > 定义"
- chunk 内容没变，**chunk_id 不变**

v2.3 的错误做法：位置 / 章节放在 chunks 表 + `INSERT OR IGNORE` → 老数据不会更新 → UI 按 chunk_id 拿 char_offset 会跳到**错误的旧位置**，显示**过时的章节路径**。

v2.4 的正确做法：每次索引都为 chunk 写一行 chunk_versions，位置/章节随版本变化；chunks 表只存"内容本身永远不变的东西"。

**关于 Anchor 格式**：

- **v2.4 格式**：`anchor_id = "{file_path}#{chunk_id}"`（**computed，不再作为列存储**）
  - chunk_id 内容稳定 → anchor 跨版本稳定
  - UI 跳转时：用 chunk_id 查 `chunk_versions` 拿当前版本的 `char_offset_start`
  - 零一致性风险（因为不是存储值）
- **展示格式（UI 用）**：`docs/pods.md > Pod > 重启策略`（title_path 来自当前版本的 chunk_versions）

#### 4.2.5 各类型的关键决策汇总

| 决策项 | document | code | structured_data |
|---|---|---|---|
| 切分粒度 | 段落/句子/硬切 | 顶级定义/逻辑块 | 顶层 key |
| overlap | 200 char | **无** | 无 |
| title_path 来源 | heading 路径 | 函数名/类名 | key 路径 |
| 硬切 fallback | ✓（罕见） | ✓（极少） | ✗（按 parser） |
| 质量过滤（< 30 char） | ✓ | ✗（短函数也有意义） | ✗ |
| 保留原始格式 | 允许归一化 | **严格保留** | **严格保留** |
| 大小上限 | 1500 char | 1500 char | 1500 char |

**跨类型共用决策**：

- ✅ **用 char 数代替 token 数**：避免 tokenizer 不对齐（原设计 P0-1）

- ✅ **稳定 chunk_id（v2.1 公式有缺陷，已修正）**：
  
  ❌ **旧公式（错）**：`sha256(file_path + chunk_index + content[:100])`  
  **问题**：在文档头部插入一段新内容 → 后面所有 chunk 的 `chunk_index` 都 +1 → **所有 chunk_id 都变** → 增量复用机制失效（恰恰是"大文档改一段"的场景）。
  
  ✅ **新公式**：`sha256(file_path + content[:500] + occurrence_seq)`
  
  - `content[:500]`：取 chunk 内容前 500 字符（足够区分不同内容 + 抗微小改动）
  - `occurrence_seq`：本 chunk 的内容（前 500 字）在**当前文档中第几次出现**。大多数情况是 0；只有文档里有完全重复的段落时才 > 0（如"本页目录"出现多次）
  - **关键性质**：内容相同 + 文件相同 → ID 相同，与位置无关。文档头部插入新段落不影响后面 chunks 的 ID。
  - **伪代码**：
    ```typescript
    function makeChunkId(filePath: string, content: string, 
                        occurrenceSeq: number): string {
      const payload = `${filePath}||${content.slice(0, 500)}||${occurrenceSeq}`;
      return crypto.createHash('sha256').update(payload).digest('hex');
    }
    
    // chunker 在切分后统一调用
    function assignChunkIds(chunks: RawChunk[], filePath: string): Chunk[] {
      const seenContent = new Map<string, number>();  // content prefix → count
      return chunks.map(c => {
        const prefix = c.content.slice(0, 500);
        const seq = seenContent.get(prefix) ?? 0;
        seenContent.set(prefix, seq + 1);
        return { ...c, chunk_id: makeChunkId(filePath, c.content, seq) };
      });
    }
    ```
  
  **已知局限**（Rank 7，可接受）：
  - 如果文档里有**内容完全相同**的两个段落（`content[:500]` 一样），在第一个重复段落前**插入一个新的重复段落**，后续重复段落的 `occurrence_seq` 会全部 +1 → chunk_id 变化。但：
    - 这只影响**完全重复的段落**，技术文档里很罕见
    - 最坏情况：少量 chunk 多做一次 embedding（成本可控）
    - **不影响数据一致性和查询正确性**
  - 如果需要彻底解决：用 `char_offset_start` 代替 `occurrence_seq` 入 hash，但会牺牲"段落移动复用 embedding"的能力

- ✅ **硬切时 `is_truncated: true`**：Layer 3 在 prompt 里告诉 LLM"此 chunk 被截断"

**接口**（Node 内部）：

```typescript
// src/chunker/index.ts
export function chunkDocument(parseResult: ParseResult): Chunk[];
```

---

### 4.3 存储

**设计**：**SQLite + FTS5 + 向量列**。不切 Elasticsearch。

**为什么不切 ES**（给队友的解释）：
- ES 搭建成本：Docker 1.5GB + 4GB 内存 + 配置调优 2-3 天
- 迁移成本：重写 retriever 代码，改 docker-compose
- 收益：50MB 级语料 SQLite + FTS5 完全够用
- **17 天内 ES 不是关键路径**，决赛（5/22）再考虑

**Schema**：

```sql
-- 文档级元数据
CREATE TABLE documents (
    file_path        TEXT PRIMARY KEY,
    file_name        TEXT NOT NULL,                    -- 原始文件名（修复双重编码）
    file_hash        TEXT NOT NULL,                    -- SHA-256
    file_size        INTEGER NOT NULL,                 -- 字节数（UI 展示）
    format           TEXT NOT NULL,                    -- md / pdf / docx / ...
    language         TEXT,                             -- zh / en / mixed / null
    index_version    TEXT,                             -- UUID，增量更新原子切换用
    index_status     TEXT DEFAULT 'pending',           -- pending / indexed / error
    error_detail     TEXT,
    chunk_count      INTEGER DEFAULT 0,
    last_modified    TIMESTAMP NOT NULL,
    indexed_at       TIMESTAMP,
    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ⚠️ v2.4 修正（Rank 1）：严格区分"内容相关"vs"版本相关"字段
--   内容相关（content-stable） → chunks 表（跨版本去重）
--   版本相关（version-specific） → chunk_versions 表（每次索引都可不同）
--
-- 为什么要分开：
--   同一段文字（chunk_id 相同）在不同版本的文档里，
--   char_offset / chunk_index / title_path 都可能不同
--   （例如用户在前面插入新章节 → 这段位置后移 + 章节路径可能变）
--
--   如果把这些字段放在 chunks 表，INSERT OR IGNORE 时不会更新，
--   UI 按 chunk_id 拿 char_offset 跳转会定位到老位置。

-- Chunks 表（仅存内容衍生的不变字段）
CREATE TABLE chunks (
    chunk_id         TEXT PRIMARY KEY,                 -- content-stable，全局唯一
    file_path        TEXT NOT NULL,                    -- 归属文件（创建后不变）
    content          TEXT NOT NULL,                    -- 内容本身
    content_type     TEXT NOT NULL,                    -- document / code / structured_data
    language         TEXT,                             -- 代码 chunk 带语言
    char_count       INTEGER NOT NULL,                 -- 内容长度（content.length）
    embedding        TEXT,                             -- JSON array，维度由配置决定
    embedding_model  TEXT,                             -- 记录是哪个模型算的
    embedding_dim    INTEGER,                          -- 维度
    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (file_path) REFERENCES documents(file_path) ON DELETE CASCADE
);

-- 版本成员表：某 chunk 在某次索引里的位置 + 章节归属
-- ⭐ v2.4：从 chunks 搬过来的字段都是"跨版本可变"的
CREATE TABLE chunk_versions (
    chunk_id         TEXT NOT NULL,
    index_version    TEXT NOT NULL,
    file_path        TEXT NOT NULL,                    -- 冗余，查询性能优化
    -- 位置信息（这次索引下的值）
    char_offset_start INTEGER NOT NULL,                -- UI 跳转的当前位置
    char_offset_end  INTEGER NOT NULL,
    chunk_index      INTEGER NOT NULL,                 -- 在本次索引该文档中的顺序
    -- 上下文信息（这次索引下的章节归属）
    title_path       TEXT,                             -- "Pod > 重启策略"（章节可重构）
    is_truncated     INTEGER DEFAULT 0,                -- 硬切标记（上下文可能变化）
    -- 审计字段（v2.5.2 P2-6 新增）：调试时能追踪某版本行何时写入
    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (chunk_id, index_version),
    FOREIGN KEY (chunk_id) REFERENCES chunks(chunk_id) ON DELETE CASCADE
);

-- 注：anchor_id 不再作为存储字段，查询时由 `file_path + "#" + chunk_id` 拼接而成
--     这样消除了"anchor_id 存的值 vs 计算值"的一致性风险

CREATE INDEX idx_chunks_file ON chunks(file_path);
CREATE INDEX idx_chunk_versions_version ON chunk_versions(index_version);
CREATE INDEX idx_chunk_versions_file_version ON chunk_versions(file_path, index_version);

-- FTS5 全文索引（BM25）
-- ⚠️ v2.5 修正（Rank 1）：键加入 index_version，避免 title_path 跨版本冲突
--   因为 title_path 在 chunk_versions 里是版本相关的，FTS 也必须按版本区分
--   content 是内容相关的，跨版本不变，但为了查询简洁统一按 (chunk_id, index_version) 键
--
-- ⚠️ v2.5.2 P2-7：tokenizer 选择说明
--   因为存入 content / title_path 前应用层已用 nodejieba 分词（空格分隔），
--   tokenizer 只需要做简单的空格切分 + 小写归一
--   unicode61 默认就按空格/标点切 + lowercasing，remove_diacritics=2 处理变音符号（对中文无影响，对西语/越南语有益）
--   不需要自定义 tokenizer（better-sqlite3 不支持 loadable extension 注册）
CREATE VIRTUAL TABLE chunks_fts USING fts5(
    chunk_id UNINDEXED,
    index_version UNINDEXED,       -- ⭐ v2.5 新增
    content,           -- 存的是 jieba 预分词后的文本（空格分隔的 token 串）
    title_path,        -- 版本相关字段，也是 jieba 预分词后的文本
    tokenize = 'unicode61 remove_diacritics 2'
);
```

**关于 FTS5 的版本关联（v2.5 Rank 1 修复）**：

v2.4 把 title_path 搬到 chunk_versions 后，FTS5 的行也必须按 `(chunk_id, index_version)` 存，否则新版本的 title_path 不会被索引：

- **写入**：每次 `chunk_versions` 插入新行时，**同步插入一行 FTS**（带当前版本的 title_path）
- **查询**：JOIN `documents.index_version` 只取当前 active 版本的 FTS 行
- **删除**：删除旧版本 chunk_versions 时，同步删除对应 FTS 行

**关于 FTS5 中文分词**（P0-3 详述）：

SQLite 自带的 `unicode61` tokenizer **不支持中文分词**，它只会按空格/标点切词。所以"`技术文档`"会被当成**一个 token**，搜"`文档`"就搜不到。这对中文文档是**硬伤**。

**采用方案：应用层预分词（jieba）**

Node 侧集成 `nodejieba`，在 **写入 chunks_fts 之前**，先对 `content` 和 `title_path` 分词，用空格连接：

```typescript
// src/database/fts_index.ts
import jieba from 'nodejieba';

function segmentForFTS(text: string): string {
  // jieba 分词 + 小写 + 空格连接
  // "Kubernetes 的 Pod 是什么" → "kubernetes 的 pod 是 什么"
  return jieba.cut(text.toLowerCase()).join(' ');
}

// ⭐ v2.5：按 (chunk_id, index_version) 维度索引
function indexChunkFTS(
  chunk: Chunk, 
  version: string,
  titlePath: string | null
) {
  db.prepare(`
    INSERT INTO chunks_fts(chunk_id, index_version, content, title_path) 
    VALUES (?, ?, ?, ?)
  `).run(
    chunk.chunk_id,
    version,
    segmentForFTS(chunk.content),
    segmentForFTS(titlePath ?? '')
  );
}

// ⭐ v2.5：删除某版本的所有 FTS 行
function deleteFTSByVersion(version: string) {
  db.prepare(`DELETE FROM chunks_fts WHERE index_version = ?`).run(version);
}
```

查询时同样对 query 预分词，且**必须按 active 版本过滤**（完整实现见 §5.1 `searchBM25`）：

```typescript
// 概念示例（生产实现见 §5.1，使用 ACTIVE_CHUNKS_CTE 暴露的 active_version 字段）
function searchBM25(query: string, topK: number): Chunk[] {
  const segmented = segmentForFTS(query);
  const rows = db.prepare(`
    ${ACTIVE_CHUNKS_CTE}
    SELECT ac.*, bm25(chunks_fts) as score
    FROM chunks_fts
    JOIN active_chunks ac 
      ON chunks_fts.chunk_id = ac.chunk_id
      AND chunks_fts.index_version = ac.active_version   -- ⭐ 版本匹配
    WHERE chunks_fts MATCH ?
    ORDER BY score LIMIT ?
  `).all(segmented, topK);
  return rows;
}
```

**为什么不用 SQLite 自定义 tokenizer**：
- `better-sqlite3` 不支持 loadable extension 注册 tokenizer（需要编译 C 代码）
- `sqlite-fts5-custom-tokenizers` 等第三方方案维护差
- 应用层分词方案**完全够用**，且和检索预处理逻辑保持一致

**替代方案（P2 可选）**：
- 升级到 `sqlean` + `fts5-unicode61-cjk`（支持 CJK 二元分词 bigram）
- 或整体迁移到 Elasticsearch 用原生中文分词器

**触发器 vs 应用层同步（v2.5 修订）**：

由于 FTS 行现在按 `(chunk_id, index_version)` 维度管理，且 content 需要 jieba 预分词（trigger 里拿不到），**统一由应用层维护 FTS**，不用 trigger。

应用层负责：
- 插入 `chunk_versions` 新行时，**同步**调 `indexChunkFTS(chunk, new_version, title_path)`
- 删除旧版本 `chunk_versions` 时，**同步**调 `deleteFTSByVersion(old_version)`
- GC 孤立 chunks 时，同步 `DELETE FROM chunks_fts WHERE chunk_id NOT IN (SELECT chunk_id FROM chunks)`（兜底）

**不用 DB trigger 的原因**：
- jieba 分词必须在 Node 侧做
- version 感知逻辑 trigger 里表达不了（需要 JOIN documents 拿 current version）
- 应用层单点控制更容易调试

**关键决策**：

- ✅ **embedding 存 JSON text**（和当前实现一致，保持兼容）
  - 规模大了性能会降，但 50MB 语料（估 ~10k chunks）单次全表 cosine 约 100ms，可接受
  - 后期优化：用 `sqlite-vec` 扩展（SQLite 原生向量索引）
- ✅ **新增 `index_version`**：增量更新的"原子切换开关"（详见 §4.4）
- ✅ **新增 `language`**：多语言文档过滤用
- ✅ **`file_name` 单独存**：修复当前代码的文件名双重编码 bug（ISSUE-003）
- ✅ **ON DELETE CASCADE**：documents 删除 → chunks 自动删

#### 4.3.1 从现有 Schema 迁移（P0-2 补充）

**现状**：当前代码用的是 `files + chunks` 两张表（`src/database/index.ts`），字段结构与 v2 不兼容。

**迁移策略：Drop & Rebuild**（最简单，赛题场景可接受）：

- **理由**：
  - 现有 chunks 表里 `chunk_count = 0`（因为 chunker 没实现，见 ISSUE-001），实际没数据要保留
  - 文档 raw 文件都在 `storage/original/`，重新上传触发索引即可
  - 评委侧拿到代码是从 docker-compose 启动，v2 schema 是"出厂默认"

- **步骤**：
  
  ```typescript
  // src/database/migrate.ts
  const SCHEMA_VERSION = 2;
  
  export function migrate(db: Database) {
    const currentVersion = db.prepare(
      "SELECT value FROM meta WHERE key='schema_version'"
    ).get()?.value ?? 0;
    
    if (currentVersion < SCHEMA_VERSION) {
      log.warn(`Migrating schema: v${currentVersion} → v${SCHEMA_VERSION}`);
      db.exec(`
        -- 备份老表（防止手滑，可选）
        ALTER TABLE files RENAME TO files_v1_backup;
        ALTER TABLE chunks RENAME TO chunks_v1_backup;
        
        -- 创建 v2 schema（见上面 CREATE TABLE）
        ${V2_SCHEMA_SQL}
        
        -- 记录版本
        CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
        INSERT OR REPLACE INTO meta VALUES ('schema_version', '2');
      `);
      
      // 触发"强制重新索引所有文件"
      // 把 storage/original/ 下的文件重新走一遍 index_pipeline
      reindexAllFromOriginalStorage();
    }
  }
  ```

- **为什么不做"数据迁移"**：
  - 老 `chunks` 表几乎是空的（当前 bug）
  - 即使有数据，老的 `vector` 字段是 OpenAI `text-embedding-3-large` 1536 维，新的 bge-m3 1024 维，**维度不同不能复用**
  - 转化成本 > 重做成本

- **生产场景应如何做**（赛后参考）：
  - 保留老数据 + 渐进式迁移
  - Schema migrations 工具（如 `node-pg-migrate`、`umzug`、`knex migrations`）
  - 版本化 migration 文件（`001-init.sql`, `002-add-index-version.sql`...）

---

### 4.4 增量同步

**设计**：**双路径 → 单 Pipeline → 文件级锁 → chunk 级 diff → 原子切换**

#### 4.4.0 执行环境说明（解决"伪代码归属不清"）

本节所有代码均为 **TypeScript，跑在 Node Express 进程内**。只有明确标注 `[rag-service]` 的部分才在 Python FastAPI 微服务里。数据访问直接走 SQLite（`better-sqlite3`），不跨网络。

**部署拓扑**（与 rag-service 的交互）：

```
docker-compose.yml
  volumes:
    raw-docs:/data/docs        ← Node 和 rag-service 都挂载
    storage:/app/storage       ← SQLite 数据库位置（仅 Node）
  
  backend (Node):
    - 文件 I/O、chokidar 监听、SQLite 访问、Pipeline 编排
    - 通过挂载的 raw-docs volume 读文件
  
  rag-service (Python):
    - 挂载相同的 raw-docs volume
    - Node 传【路径】而非二进制文件，rag-service 自己从 volume 读
```

**决策**（P1-7 修正）：**共享 volume + 传路径**。理由：
- 大 PDF（50MB+）通过 HTTP multipart 传输延迟高、易失败
- docker-compose 单机部署下 volume 共享零成本
- Node 负责"文件管理"，rag-service 纯计算，职责清晰

**接口修正**：`POST /parse` 的 body 改为 `{ file_path: string, format: string, hint_language?: string }`，不再传二进制。

#### 4.4.1 完整 Pipeline（TypeScript）

```typescript
// src/pipeline/index.ts

import { Mutex } from 'async-mutex';
import { v4 as uuidv4 } from 'uuid';
import crypto from 'crypto';
import fs from 'fs/promises';

// 文件级锁，防止同一文件并发处理
const fileLocks = new Map<string, Mutex>();

function getFileLock(filePath: string): Mutex {
  if (!fileLocks.has(filePath)) {
    fileLocks.set(filePath, new Mutex());
  }
  return fileLocks.get(filePath)!;
}

// 入口：WebUI 上传 + chokidar 都调这个
export async function handleFileEvent(filePath: string) {
  const lock = getFileLock(filePath);
  await lock.runExclusive(() => indexPipeline(filePath));
}

async function indexPipeline(filePath: string): Promise<IndexResult> {
  // 1. 算新 hash
  const buffer = await fs.readFile(filePath);
  const newHash = crypto.createHash('sha256').update(buffer).digest('hex');
  const oldRecord = db.getDocument(filePath);

  // 2. hash 未变，提前返回（关键优化）
  if (oldRecord && oldRecord.file_hash === newHash) {
    return { status: 'unchanged' };
  }

  // 3. 生成新 index_version
  const newVersion = uuidv4();
  db.upsertDocument({
    file_path: filePath,
    file_hash: newHash,
    index_version: newVersion,
    index_status: 'pending',
  });

  try {
    // 4. 解析（调 rag-service）
    const parseResult = await ragClient.parse({
      file_path: filePath,
      format: detectFormat(filePath),
    });

    // 5. 切分（Node 内）
    const newChunks = chunkDocument(parseResult);

    // 6. chunk 级 diff
    const oldChunks = oldRecord
      ? db.getChunks(filePath, oldRecord.index_version)
      : [];
    const { toAdd, toDelete, reusePairs } = chunkDiff(newChunks, oldChunks);

    // 7. 复用老 embedding（toAdd 才需要新算）
    for (const [newChunk, oldChunk] of reusePairs) {
      newChunk.embedding = oldChunk.embedding;
    }

    // 8. Batch embed（调 rag-service，并发有 rate limit）
    const embeddings = await ragClient.batchEmbed(
      toAdd.map(c => c.content),
      { concurrency: 8 }  // 内部 Semaphore 控制
    );
    toAdd.forEach((c, i) => { c.embedding = embeddings[i]; });

    // 9. 原子写入（v2.4 修正 Rank 1 - 版本元数据分离）
    //    模型：chunks 存"内容"，chunk_versions 存"本次索引下的位置/章节"
    //    - 内容相同（chunk_id 相同） → chunks 表 INSERT OR IGNORE（老数据保留）
    //    - 位置/章节 → chunk_versions 每次新版本都插入新行（携带当前版本的值）
    db.transaction(() => {
      // 9a. 内容主表：INSERT OR IGNORE（内容已存在就不动）
      //     只包含内容相关字段：content, embedding, language 等
      db.insertChunksOrIgnore(
        newChunks.map(c => ({
          chunk_id: c.chunk_id,
          file_path: c.file_path,
          content: c.content,
          content_type: c.content_type,
          language: c.language,
          char_count: c.char_count,
          embedding: c.embedding,
          embedding_model: c.embedding_model,
          embedding_dim: c.embedding_dim,
        }))
      );
      
      // 9b. 版本成员表：为每个 chunk 插入本次版本的位置/章节
      //     key 是 (chunk_id, index_version)，不会冲突
      //     reuse 的 chunk 在 chunks 表没动，但这里仍会插入新 chunk_versions 行
      //     这样可以记录 "这块内容在新版本中位于 offset X, 属于章节 Y"
      db.insertChunkVersions(
        newChunks.map(c => ({
          chunk_id: c.chunk_id,
          index_version: newVersion,
          file_path: filePath,
          char_offset_start: c.char_offset_start,
          char_offset_end: c.char_offset_end,
          chunk_index: c.chunk_index,
          title_path: c.title_path,
          is_truncated: c.is_truncated ? 1 : 0,
        }))
      );
      
      // 9c. ⭐ v2.5：同步插入 FTS 行（按 index_version 维度）
      //     每个 chunk 在新版本下插一行 FTS，即使 content 没变（因为 title_path 可能变）
      for (const c of newChunks) {
        indexChunkFTS(c, newVersion, c.title_path);
      }
      
      // 9d. ⭐ v2.5.2 P1-4：同事务清理旧版本的 chunk_versions 和 FTS
      //     原 v2.5 把清理放在 step 10 单独事务 → 如果 step 10 前进程崩溃会留下"新+旧两套数据"
      //     合并到 step 9 同事务 → 要么新旧都更新，要么都不变，无中间态
      if (oldRecord) {
        db.deleteChunkVersionsByVersion(oldRecord.index_version);
        deleteFTSByVersion(oldRecord.index_version);
      }
      
      // 9e. 切换文档的 active 版本（原子性：这一行是"真相切换"）
      db.updateDocument(filePath, {
        index_version: newVersion,
        index_status: 'indexed',
        chunk_count: newChunks.length,
        indexed_at: new Date().toISOString(),
      });
    });

    // 10. 清理孤立 chunks（没有任何 chunk_versions 引用的内容行）
    //     这一步不必和 9 同事务——即使失败，查询也是对的（孤儿不在 active 视图里）
    //     但仍然放同一进程调用里，失败时 GC 兜底
    if (oldRecord) {
      try {
        db.exec(`
          DELETE FROM chunks 
          WHERE chunk_id NOT IN (SELECT DISTINCT chunk_id FROM chunk_versions)
        `);
      } catch (e) {
        log.warn(`GC orphan chunks failed, will retry in scheduled GC: ${e}`);
      }
    }

    return {
      status: 'indexed',
      chunk_count: newChunks.length,
      embedded: toAdd.length,
      reused: reusePairs.length,
    };

  } catch (err: any) {
    const detail = err instanceof ParseError
      ? `解析失败: ${err.type}`
      : err.message;
    db.updateDocument(filePath, { index_status: 'error', error_detail: detail });
    throw err;
  }
}
```

#### 4.4.2 处理删除

```typescript
export async function handleFileDelete(filePath: string) {
  const lock = getFileLock(filePath);
  await lock.runExclusive(() => {
    db.deleteDocument(filePath);  // ON DELETE CASCADE 自动删 chunks
  });
}
```

#### 4.4.3 孤儿 GC（启动时 + 每小时跑）

```typescript
// src/pipeline/gc.ts
const GC_GRACE_PERIOD_MS = 5 * 60 * 1000;  // P2-9 修正：5 分钟 grace period

export async function gcOrphanChunks() {
  const allDocs = db.getAllDocuments();
  for (const doc of allDocs) {
    // Grace period：刚创建 5min 内的记录不 GC（避免和并发上传竞态）
    const age = Date.now() - new Date(doc.created_at).getTime();
    if (age < GC_GRACE_PERIOD_MS) continue;

    try {
      await fs.access(doc.file_path);
    } catch {
      log.warn(`文件已删除但索引还在: ${doc.file_path}`);
      db.deleteDocument(doc.file_path);
    }
  }

  // 兜底：删 chunks 表里没对应 document 的孤儿
  db.exec(`
    DELETE FROM chunks 
    WHERE file_path NOT IN (SELECT file_path FROM documents)
  `);
  
  // ⭐ v2.5.2 P1-4 兜底：清理 FTS 里孤立的版本行（document 已不存在或版本已切换）
  //     正常情况下 Pipeline step 9d 已清理；这里是防"step 9d 后、step 10 前进程崩溃"的残留
  db.exec(`
    DELETE FROM chunks_fts 
    WHERE index_version NOT IN (SELECT index_version FROM documents WHERE index_version IS NOT NULL)
  `);
  
  // 清理 chunk_versions 里孤立的版本行
  db.exec(`
    DELETE FROM chunk_versions
    WHERE index_version NOT IN (SELECT index_version FROM documents WHERE index_version IS NOT NULL)
  `);
}
```

#### 4.4.4 chunk_diff 算法（修正 chunk_id 公式后的逻辑不变）

```typescript
export function chunkDiff(newChunks: Chunk[], oldChunks: Chunk[]) {
  const newMap = new Map(newChunks.map(c => [c.chunk_id, c]));
  const oldMap = new Map(oldChunks.map(c => [c.chunk_id, c]));

  const toAdd = newChunks.filter(c => !oldMap.has(c.chunk_id));
  const toDelete = oldChunks.filter(c => !newMap.has(c.chunk_id));
  const reusePairs: [Chunk, Chunk][] = [];

  for (const [id, newChunk] of newMap) {
    const oldChunk = oldMap.get(id);
    if (oldChunk) reusePairs.push([newChunk, oldChunk]);
  }

  return { toAdd, toDelete, reusePairs };
}
```

**关键决策**：

- ✅ **文件级锁用 Node `async-mutex` 或 Python `asyncio.Lock`**：单进程够用，不需要 Redis 分布式锁
- ✅ **Debounce 1 秒**：文件事件风暴抑制
- ✅ **chunk_diff 复用 embedding**：**省 99% embedding 调用**（大文档改一段的场景）
- ✅ **原子版本切换**：查询永远看到一致的版本
- ✅ **失败时保留老数据**：不会"消失"
- ✅ **定时 GC**：防漏事件导致的孤儿

---

### 4.5 5 分钟 SLA 保障

**设计**：**分级 SLA + 动态并发 + 进度可视化**

**分级时间承诺**：

| 文档大小 | 解析 | 切分 | Embedding | 合计 | SLA 级别 |
|---|---|---|---|---|---|
| 小（< 20 页 / 100KB） | 1-5s | 1s | 5-10s（~20 chunks × 8 并发）| **< 30s** | P0 必达 |
| 中（20-100 页） | 5-30s | 2-5s | 20-60s | **< 2min** | P0 必达 |
| 大（100-500 页） | 30s-2min | 5-15s | 1-3min（分片并发）| **< 5min** | P1 尽力 |
| 超大（> 500 页 / 50MB+） | 2-10min | 10-30s | 3-10min | **异步 + 进度条** | P2 不承诺 SLA |

**动态并发控制**（v2.5.2 修正 P1-2：改成 TypeScript，和 §4.4.0 的"Node 主体"声明一致）：

> 说明：并发控制放在 **Node Pipeline 侧**（调用方），不是 rag-service 里。这样：
> - 一个 Node 进程里的 embed 总并发数可控（rag-service 侧如果并发控制，多 Node 实例会绕过）
> - 重试策略与 Pipeline 的错误恢复、WebSocket 进度上报耦合更紧密
> - rag-service 里保持无状态，方便扩展

```typescript
// src/pipeline/embed_pool.ts
import pLimit from 'p-limit';   // 简洁的并发控制库，Node 生态标准选择

class EmbedPool {
  private limit: ReturnType<typeof pLimit>;
  
  constructor(gatewayQps: number) {
    // 给其他请求（查询、reranker）留 2 qps
    const concurrency = Math.max(1, Math.min(8, gatewayQps - 2));
    this.limit = pLimit(concurrency);
  }
  
  async embed(text: string): Promise<number[]> {
    return this.limit(() => this.embedWithRetry(text));
  }
  
  async batchEmbed(texts: string[]): Promise<number[][]> {
    return Promise.all(texts.map(t => this.embed(t)));
  }
  
  // 指数退避重试（简化实现，生产可换 async-retry 库）
  private async embedWithRetry(text: string, attempt = 0): Promise<number[]> {
    try {
      return await ragClient.embed(text);    // 调 rag-service
    } catch (err: any) {
      if (attempt >= 5 || !this.isRetryable(err)) throw err;
      const delay = Math.min(60_000, 1000 * 2 ** attempt);  // 1s → 2s → 4s → 8s → 16s → 32s (cap 60s)
      await new Promise(r => setTimeout(r, delay));
      return this.embedWithRetry(text, attempt + 1);
    }
  }
  
  private isRetryable(err: any): boolean {
    // 429 Rate Limit、5xx、网络错误可重试；4xx（除 429）不重试
    return err.status === 429 
        || (err.status >= 500 && err.status < 600)
        || err.code === 'ECONNRESET'
        || err.code === 'ETIMEDOUT';
  }
}
```

**进度反馈**：

WebSocket 推送进度给前端（每个文档）：

```typescript
{
  file_path: "docs/pods.md",
  stage: "parsing" | "chunking" | "embedding",
  progress: 0.34,                // 0-1
  chunks_done: 12,
  chunks_total: 35,
  eta_seconds: 45,
  status: "running" | "done" | "error"
}
```

前端显示：

```
⏳ docs/pods.md
   嵌入向量化中 34% (12/35)
   预计还需 45 秒
```

---

## 5. 接口契约（与 Layer 2/3/4 的协议）

### 5.1 Layer 1 → Layer 2（检索）

**部署关系与调用方式（P2-11 澄清）**：

Layer 1 和 Layer 2 **同进程（Node Express）内直接调用**，不通过 HTTP。Layer 2 是 `src/retriever/` 下的模块，import Layer 1 的 `Layer1Storage` 接口即可。

**为什么这么做**：
- 两层都要访问 SQLite，同进程共享连接池最简单
- 避免不必要的序列化成本（一个查询可能返回 20 chunks，每个带 embedding）
- 海军的 reranker 逻辑也是 Node/TS（如果需要调 Python reranker，是 **Layer 2 → rag-service**，不是 Layer 2 → Layer 1）

**接口契约（TypeScript 模块级）**：

**⚠️ v2.3 关键修正（Rank 2）**：所有读方法**必须按 active index_version 过滤**，否则会读到"已被新版本替代但尚未清理"的旧 chunks。过滤条件统一是：

```sql
-- 所有查询的标准过滤子句
chunk_versions.index_version = documents.index_version  -- JOIN documents 拿 active version
AND documents.index_status = 'indexed'                   -- 不读 pending/error 的文档
```

这个过滤在 `SqliteStorage` 内部实现，对 Layer 2 透明——Layer 2 不需要感知 index_version。

```typescript
// src/storage/index.ts —— Layer 1 导出的稳定接口
export interface Layer1Storage {
  // 按 chunk_id 获取单个 chunk（引用跳转用）
  // ⚠️ 即使 chunk 存在但已不是任何文档的 active version，返回 null
  getChunk(chunk_id: string): Chunk | null;
  
  // BM25 搜索（FTS5 + jieba 预分词）
  // ⚠️ 只返回 active version 的 chunks
  searchBM25(query: string, top_k: number): Chunk[];
  
  // 拿某文档的所有 chunks（reranker 去重 / 溯源）
  // ⚠️ 只返回该文档当前 active version 的 chunks
  getChunksByFile(file_path: string): Chunk[];
  
  // 全量 chunks + embedding（Layer 2 做向量检索）
  // ⚠️ 只返回 active chunks，50MB 语料 ~10k chunks，一次加载 ~100MB 内存
  getAllChunksWithEmbedding(limit?: number): Chunk[];
  
  // 按 chunk_ids 批量获取（reranker 精排后回查原文用）
  // ⚠️ 过滤掉非 active 的 chunks
  getChunksByIds(ids: string[]): Chunk[];
  
  // 索引统计（只数 active 的）
  getStats(): { file_count: number; chunk_count: number; indexed_count: number };
  
  // ⭐ v2.3 新增：调试 / 运维用，不对 Layer 2 暴露业务用途
  // 允许读非 active version（例如查询 rollback 历史），默认 false
  _getChunkInAllVersions?(chunk_id: string): Array<{ chunk: Chunk; version: string }>;
}

// 具体实现
export class SqliteStorage implements Layer1Storage { ... }

// 单例导出（Layer 2 用：import { storage } from '../storage'）
export const storage: Layer1Storage = new SqliteStorage();
```

**内部实现示例（v2.4 修正：两表 JOIN 形成合并视图）**：

```typescript
// 所有 SELECT 查询走的统一基础 CTE
// ⭐ v2.5：CTE 额外暴露 active_version，让下游查询（特别是 FTS）能按版本过滤
// ⭐ v2.5.2 P2-5：加 c.file_path = cv.file_path 防御性约束（理论上 chunk_id 含 file_path 不会不一致，但 defense in depth）
const ACTIVE_CHUNKS_CTE = `
  WITH active_chunks AS (
    SELECT 
      -- 来自 chunks（内容字段）
      c.chunk_id, c.file_path, c.content, c.content_type, c.language,
      c.char_count, c.embedding, c.embedding_model, c.embedding_dim,
      -- 来自 chunk_versions（当前版本的位置/章节字段）
      cv.char_offset_start, cv.char_offset_end, cv.chunk_index,
      cv.title_path, cv.is_truncated,
      -- ⭐ v2.5：暴露 active 版本，供 FTS / 其他查询过滤
      d.index_version AS active_version
    FROM chunks c
    INNER JOIN chunk_versions cv 
      ON c.chunk_id = cv.chunk_id 
      AND c.file_path = cv.file_path              -- ⭐ v2.5.2：防御性约束
    INNER JOIN documents d ON cv.file_path = d.file_path
    WHERE cv.index_version = d.index_version         -- 只当前版本
      AND d.index_status = 'indexed'                 -- 只已索引完成的
  )
`;

searchBM25(query: string, topK: number): Chunk[] {
  const segmented = segmentForFTS(query);
  // ⭐ v2.5.2 双重过滤（更明显的版本约束）
  //   chunks_fts 按 (chunk_id, index_version) 存；必须同时匹配 chunk_id 和 version
  //   如果只匹配 chunk_id，会同时命中新旧版本的 FTS 行 → 搜索结果重复 + 拿到老 title_path
  //   版本约束放在 WHERE 里更显眼（JOIN ON 的 AND 效果相同但不醒目）
  const rows = this.db.prepare(`
    ${ACTIVE_CHUNKS_CTE}
    SELECT ac.*, bm25(chunks_fts) AS score
    FROM chunks_fts
    JOIN active_chunks ac ON chunks_fts.chunk_id = ac.chunk_id
    WHERE chunks_fts MATCH ?
      AND chunks_fts.index_version = ac.active_version   -- ⭐ 必须过滤到 active 版本的 FTS 行
    ORDER BY score LIMIT ?
  `).all(segmented, topK);
  
  // 合并 anchor_id（computed，非存储）
  return rows.map(r => ({ ...r, anchor_id: `${r.file_path}#${r.chunk_id}` }));
}

getChunk(chunk_id: string): Chunk | null {
  // getChunk 不涉及 FTS，只走 active_chunks CTE 就够（CTE 已做版本过滤）
  const row = this.db.prepare(`
    ${ACTIVE_CHUNKS_CTE}
    SELECT * FROM active_chunks WHERE chunk_id = ?
  `).get(chunk_id);
  if (!row) return null;
  return { ...row, anchor_id: `${row.file_path}#${row.chunk_id}` };
}
```

**接口稳定承诺**：方法签名一旦 merge 到 main，**Layer 1 不改**。需要扩展时**新增方法**，不改老方法签名。如果发现设计失误必须改，**发 PR 改接口时 @ 所有 Layer 使用方**。

**版本标记**：`Layer1Storage` 接口的 import 路径带版本命名空间（可选 P1 优化）：
```typescript
import type { Layer1Storage as Layer1StorageV1 } from '../storage/v1';
```

### 5.2 Layer 1 → Layer 4（WebUI）HTTP 接口

**⚠️ v2.3 修正（Rank 5）向后兼容策略**：

当前 `frontend/lib/api.ts` 在调用 `/api/qa/files`、`/api/qa/stats`、`/api/qa/index`；如果 Layer 1 把端点改成 `/api/documents`、`/api/stats`，前端会直接挂。

**采用策略：新增端点 + 保留旧端点（alias 同一实现）**——旧端点不废弃，新端点作为更语义化的别名提供给新代码 / 外部评测工具使用。迁移时间表由全队决定，初赛期间**都保留**。

**端点清单**：

```
# ----- 新增端点（语义更清晰，对接评委自动化评测工具友好） -----
POST   /api/documents          上传文档（新增）
DELETE /api/documents/:id      删除文档 ⭐新增
GET    /api/documents          列出所有文档（新别名）
GET    /api/documents/:id      单文档详情（chunk_count, status, eta）
GET    /api/stats              系统统计（新别名）
POST   /api/index/rebuild      手动重建所有索引（debug 用）⭐新增
POST   /api/index/:file_path   单文件强制重建（debug 用）⭐新增

# ----- 保留旧端点（向后兼容，内部调新实现） -----
POST   /api/upload             等同 POST /api/documents
GET    /api/qa/files           等同 GET /api/documents
GET    /api/qa/stats           等同 GET /api/stats
POST   /api/qa/index           等同 POST /api/index/rebuild
POST   /api/qa/ask             （Layer 3 的，Layer 1 不影响）
POST   /api/qa/ask-stream      （Layer 3 的，Layer 1 不影响）
POST   /api/qa/search          （Layer 2 的，Layer 1 不影响）

# ----- WebSocket -----
WS     /ws/progress            WebSocket 进度推送 ⭐新增
                              - 认证：URL 携带 token（赛题场景下简化，生产需 OAuth）
                              - 重连：客户端指数退避（1s/2s/4s/8s...），重连后请求全量状态快照
                              - Payload：{file_path, stage, progress, chunks_done, chunks_total, eta_seconds, status}
```

**实现约定**：新旧端点**共享同一 handler 函数**，只是路由不同。例如：

```typescript
// src/routes/documents.ts
const listDocumentsHandler = async (req, res) => { ... };

router.get('/api/documents', listDocumentsHandler);  // 新
router.get('/api/qa/files', listDocumentsHandler);   // 旧，向后兼容
```

**前端迁移**（P2 可选）：`frontend/lib/api.ts` 可以渐进地切到新端点，但**不阻塞 Layer 1 落地**。

### 5.3 Node ↔ rag-service（Python 微服务）

```
POST http://rag-service:8000/parse
  body: { file_path: string, format: string }
  → ParseResult

POST http://rag-service:8000/embed
  body: { texts: string[], batch_size: number }
  → { embeddings: number[][] }

POST http://rag-service:8000/rerank
  body: { query: string, candidates: string[] }
  → { scores: number[] }

GET  http://rag-service:8000/health
  → { status: "ok", embedding_model: "<从 env 读取>", embedding_dim: <N>,
      reranker_model: "<从 env 读取或 null>" }
```

---

## 6. 实施路线图（19 天，分 5 阶段）

**总体原则**：**前紧后松**——开发留时间早期暴露问题，后期只修 bug 不加 feature。**2/5 时间用于联调 + 评委语料适配 + 提交准备**。

**关键里程碑**：
- **4/28（Day 7）**：Layer 1 MVP 可端到端跑通，提交 PR 给主仓
- **5/1（Day 10）**：功能全部完成，进入"只修 bug"模式
- **5/5（Day 14）**：全量联调完成，等评委语料
- **5/7（Day 16）**：评委语料到位
- **5/10 18:00**：提交

### 阶段 1：MVP 核心通路（Day 1-5，4/22-4/26）

解锁评测基线，保证系统能端到端跑。**P1-6 修正**：Day 1-2 合并，Day 3 做 buffer。

| Day | 日期 | 任务 | 验收 |
|---|---|---|---|
| 1-2 | 4/22-4/23 | 最小 markdown chunker + 接入 upload.ts + 评测 smoke test | `chunkCount > 0`, eval 首个基线分数 |
| 3 | 4/24 五 | **Buffer**：扩展 chunker 到 pdf/docx（若 Day 1-2 顺利则推进，否则补 MVP） | md + pdf + docx 可切分 |
| 4 | 4/25 六 | Schema 迁移到 v2（含 v2.2 的 chunk_id / anchor / FTS5 jieba） | ISSUES 关掉 3 条，FTS5 搜"文档"命中 |
| 5 | 4/26 日 | rag-service 骨架 + docker-compose + embedding 端到端 | `/health` 可达，真实向量入库，eval 分数 > 30 |

**阶段出口**：Layer 1 MVP 跑通，发 PR 给主仓，通知 Layer 2 可以开始联调。

**前置依赖风险**：Day 1-2 如果 chunker 写慢（遇到 nodejieba 集成、稳定 chunk_id 算法调试），Day 3 作为兜底。**千万不要为了赶 Day 2 deadline 跳过 eval 验证**。

---

### 阶段 2：增量 + 可靠性（Day 6-10，4/27-5/1）

加上增量更新 + 并发 + 错误恢复，让系统**生产级可用**。

| Day | 日期 | 任务 | 验收 |
|---|---|---|---|
| 6 | 4/27 一 | chunk 级 diff + index_version 原子切换 | 改文档只重 embed 变化部分 |
| 7 | 4/28 二 | chokidar 监听 + debounce 1s | 外部 cp 文件 1min 内生效 |
| 8 | 4/29 三 | 文件级锁 + 并发上传测试 | 20 并发上传不串数据 |
| 9 | 4/30 四 | 孤儿 GC + 错误恢复 | 删文件、杀进程、恢复后索引一致 |
| 10 | 5/1 五 | 进度反馈 + WebSocket 推送 | UI 显示真实阶段 + ETA |

**阶段出口**：**Feature Freeze**——后续只修 bug，不加新功能。评测 eval 分数 > 60（独立看 Layer 1）。

---

### 阶段 3：联调 + 压测 + 全量测试（Day 11-14，5/2-5/5）⭐ 关键

**4 天联调时间**，这是原路线图里没有充分预留的。

| Day | 日期 | 任务 | 验收 |
|---|---|---|---|
| 11 | 5/2 六 | **与 Layer 2 接口联调**（reranker、Dense kNN 接入） | 端到端 eval 分数 > 65 |
| 12 | 5/3 日 | **与 Layer 3 联调**（引用验证、prompt 格式对齐） | 引用准确率 > 70% |
| 13 | 5/4 一 | **与 Layer 4 联调**（前端调 WebSocket、文件管理 UI） | UI 展示正常 |
| 14 | 5/5 二 | **性能压测**（50MB 语料 + 5min SLA 验证）+ 评测集扩到 50 题 | 全量评测通过 |

**阶段出口**：整个系统端到端跑通，各 Layer 接口契约稳定。

**联调缓冲策略**：
- 如果 Layer 2/3 进度慢，Day 11-13 优先压**最小闭环**（Layer 1 + Layer 2 最小版本）
- 任何 Day 发现接口不一致，**立即喊停**，优先改接口再继续

---

### 阶段 4：评委语料适配（Day 15-17，5/6-5/8）

**预留日**：语料 5/7 发放，我们需要 3 天应对"未知的实际文档"。

| Day | 日期 | 任务 | 验收 |
|---|---|---|---|
| 15 | 5/6 三 | 评委语料预处理脚本 + 评测集通用类保留验证 | 通用类评测分数不降 |
| 16 | 5/7 四 | **评委语料接入** + 重跑评测 + 快速针对性优化 | 在评委语料上评测 > 70 |
| 17 | 5/8 五 | 根据评委语料的特点调优 chunking / anchor / 拒答阈值 | 稳定在 ≥ 目标分 |

**阶段出口**：在评委语料上跑出稳定分数。

**风险兜底**：
- 如果评委语料和 K8s/Python docs 风格差异极大（比如 PDF 扫描件占主导），**Day 17 可能需要额外工作**，所以 Day 15 必须把"应急预案"（PaddleOCR 启用开关、chunking 参数可配）提前做好。

---

### 阶段 5：提交准备（Day 18-19，5/9-5/10）

**非开发日**——只做提交物收尾。

| Day | 日期 | 任务 | 验收 |
|---|---|---|---|
| 18 | 5/9 六 | Demo 视频录制 + README 定稿 + 架构文档清理 + SELF_EVAL.md | 所有交付件齐全 |
| 19 上 | 5/10 日上午 | 最终 docker-compose 在干净机器上验证 + 最后一次全量 eval | 一键启动成功 |
| 19 下 | 5/10 日 18:00 前 | **提交** | 提交完成 |

**阶段出口**：✅ 作品提交。

---

### 路线图风险缓冲总结

| 类型 | 原路线图 | 新路线图 |
|---|---|---|
| Feature 开发天数 | 14 天（Day 1-14） | 10 天（Day 1-10） |
| 联调压测天数 | 1-2 天（Day 13 兼做） | **4 天（Day 11-14）⭐** |
| 评委语料适配 | 1 天（Day 15） | **3 天（Day 15-17）⭐** |
| 提交收尾 | 2 天（Day 16-17） | **2 天（Day 18-19）** |
| **总 buffer** | **3-4 天** | **9 天**（联调 + 语料 + 提交）|

**原则**：宁可 Feature 做少一点，也要留足联调时间。未联调的功能等于没有。

---

## 7. 待定事项（需团队讨论）

### ❓ Q1：Embedding 模型最终选什么？

**已知信息（v2.4 补充）**：统一 LLM 网关**已确认**支持的模型：
- **生成类**（chat）：`glm5` / `kimi` / `minimax` / `qwen 3.6`
- **Embedding / Rerank**：**待确认**（这 4 个列出的都是聊天模型，没有明说 embedding）

**三个可能场景**：

| 场景 | 解决方案 |
|---|---|
| **A. 网关支持 embedding**（如 qwen-embedding） | ✅ 直接走网关，符合红线 |
| **B. 网关不支持 embedding，但允许本地 embedding**（因为 embedding 不是"对外模型调用"意义上的 LLM） | ✅ 本地跑 bge-m3，只是算向量不上传数据 |
| **C. 网关强硬要求 100% embedding 也走网关** | ⚠️ 需要升级组委会需求 / 申请例外 |

**建议 Day 1 action**：
1. 队长直接问网关管理员：**"网关是否提供 embedding API？如果没有，本地跑 bge-m3 算不算违反红线？"**
2. 根据答复决定场景 A / B / C
3. 代码层面 schema 已解耦（v2.3 修完），切换成本低

### ❓ Q2：rag-service 谁写？

候选：
- 海军（懂 RAG）
- 其他 Python 背景成员

**建议**：海军主导，我（涂祎豪）协助 glue code。

### ❓ Q3：是否做 PaddleOCR？

- 成本：+1GB Docker 镜像，首次启动 +30s 模型加载
- 收益：扫描版 PDF / 图片内容也能检索
- **P1 优化**，看评委语料是否有扫描件决定

### ❓ Q4：向量索引升级到 sqlite-vec？

- 当前：JSON 字符串 + 全表 cosine
- 升级：`sqlite-vec` 扩展，原生向量索引，查询 10x 快
- **P1 优化**，50MB 语料先不急

### ❓ Q5：LibreOffice 是否纳入 rag-service 镜像？

- 场景：支持 `.doc` / `.xls` / `.ppt` 旧版 Office（依赖 LibreOffice headless 转换）
- 成本：Docker 镜像 +300MB，转换耗时 3-30s
- 替代：只支持新版 `.docx` / `.xlsx` / `.pptx`，旧版让评委自己转
- **建议**：先评估评委语料里旧版 Office 占比。若几乎没有（大概率），**P2 不做**

### ❓ Q6：代码类文件的"源码 vs 文本"识别

- `.html` 有二义性：可能是网页文档（→ 转 markdown 走文档路径）或源码（→ 走代码路径）
- `.xml` 类似：配置文件 vs 数据文件 vs 文档
- **建议的启发式**：
  - 含 `<body>` 且有 `<p>` / `<h1>` → 文档路径
  - 以 `<?xml` 开头且简单结构 → structured_data 路径
  - 其他 → 代码路径

---

## 8. 风险与兜底

| 风险 | 概率 | 影响 | 兜底 |
|---|---|---|---|
| 网关不支持 embedding | 中 | 高 | 先确认红线定义（见 Q1）；若允许本地 embedding 用 bge-m3；若不允许，升级给组委会 |
| PaddleOCR 中文识别慢 | 中 | 中 | OCR 异步，不阻塞主流程 |
| SQLite 50MB 后性能降 | 低 | 中 | 升级 sqlite-vec |
| chokidar 漏事件 | 中 | 低 | 每小时全扫描兜底 |
| 大文档 SLA 超时 | 高 | 中 | 分级 SLA + 异步承诺 |
| chunk 切分边界错乱 | 低 | 高 | 评测集验证 + P0-4 三级 fallback |
| **LibreOffice 转换失败**（旧版 Office 损坏） | 中 | 低 | try-catch 记 error_detail，降级为纯文本提取（`antiword` / `catdoc`） |
| **代码文件编码非 UTF-8** | 中 | 中 | `chardet` 检测 + 转码；失败时跳过并标记 error |
| **代码"顶级定义"regex 误判** | 低 | 低 | 整文件当一个 chunk 兜底 |
| **二义性文件判错类型**（如 HTML 判成代码） | 中 | 低 | UI 提供"手动重新分类"按钮 |
| **nodejieba 原生模块编译失败**（Node 版本新 / Apple Silicon / Alpine Docker） | **高** | 中 | **项目已在 `better-sqlite3` 上踩过同类坑**。兜底方案：改用**纯 JS 分词库**（如 `jieba-wasm`、`segmentit`、`nodejs-jieba-chs-cht`），精度略降但零原生依赖。Dockerfile 明确基于 `node:20-bookworm` 而非 Alpine |
| **FTS5 在高并发 INSERT 下报 lock** | 中 | 中 | 所有 FTS 写入放在同一事务；SQLite 开 WAL 模式 |
| **embedding 维度切换**（如从 1024 换到 1536） | 低 | 高 | schema 已带 `embedding_dim` 列，换模型后标记旧 chunks 需要重 embed，分批迁移 |

---

## 9. 术语表

| 术语 | 通俗解释 |
|---|---|
| Chunk | 把长文档切成的"小段"，便于检索。每段一般 300-1500 字。 |
| Token | AI 模型处理文字的最小单位。中文大约 1 字 1 token。 |
| Tokenizer | 把文字切成 token 的工具。不同模型切法不同。 |
| Embedding / 向量化 | 把一段文字变成一串数字（几百到几千个小数），AI 靠这串数字判断语义相似度。 |
| bge-m3 | 一个中文效果好的开源 embedding 模型。 |
| Reranker | 对检索候选结果做二次打分的模型，比 embedding 单独用更准。 |
| BM25 | 传统关键词检索算法（"有没有出现这个词 + 出现频率"）。 |
| kNN / Dense kNN | 基于向量相似度的近邻检索。K 指返回几个最相似的。 |
| ColBERT | 一种多向量检索算法，精度高但存储爆炸，本设计砍掉。 |
| RRF | 多路召回结果融合算法。 |
| Elasticsearch / ES | 专业的检索引擎，本设计**不用**（时间不够）。 |
| SQLite FTS5 | SQLite 内置的全文检索模块，支持 BM25，本设计用它。 |
| sqlite-vec | SQLite 的向量索引扩展，本设计 P1 可选升级。 |
| Anchor | "锚点"，指向文档某个具体位置（如 `pods.md#4821`）。 |
| char_offset | 字符偏移量，"从第几个字符开始"。比行号精确。 |
| title_path | 标题路径面包屑，如 "Pod > 重启策略"。 |
| Watchdog / chokidar | 文件监听库，Watchdog 是 Python 的，chokidar 是 Node 的。 |
| inotify | Linux 内核级文件监听机制。 |
| Debounce | 抖动抑制，短时间内多次触发合并成一次。 |
| Idempotent | 幂等，同操作执行多次和一次结果相同。 |
| SHA-256 | 哈希算法，把内容摘要成 64 位字符串，用来判断内容变化。 |
| GC | 垃圾回收，清理无用的老数据。 |
| Rate Limit | 速率限制，"每秒最多 X 次调用"。 |
| Semaphore | 并发控制的"令牌"，最多 N 个任务同时跑。 |
| Transaction | 数据库"要么全做要么不做"的操作组。 |
| Unstructured | Python 文档解析库，处理 pdf/docx/pptx 强。 |
| Docling | 另一个 Python 文档解析库，markdown/html 强。 |
| PaddleOCR | 百度开源的 OCR，中文效果强。 |
| FastAPI | Python 的高性能 Web 框架，rag-service 用它。 |
| LibreOffice headless | 无界面模式的 LibreOffice，可命令行调用来做文档格式转换。 |
| antiword / catdoc | 古老的 Linux 命令行工具，单独提取 `.doc` 里的纯文本。LibreOffice 的 backup。 |
| AST（抽象语法树） | 把代码解析成的树状结构，能准确识别函数/类/语句边界。 |
| chardet | Python 编码检测库，自动识别文件是 UTF-8 / GBK / Latin-1 等。 |
| MIME sniff | 不靠文件扩展名，而是读文件前几字节判断真实类型（如 PDF 前 4 字节是 `%PDF`）。 |
| file-type (Node) / python-magic | 实现 MIME sniff 的库。 |
| `content_type` | 本设计新增的分类字段，值为 `document / code / structured_data`，决定用哪套 chunking 策略。 |
| overlap | chunk 之间的重叠内容。文档类加 overlap 保连贯，代码类不加避免重复。 |

---

## 10. 更新历史

- **2026-04-22 v2 初版**：替代原架构文档 §1.1-§1.5，整合 P0×7 优化，明确技术栈决策
- **2026-04-22 v2.1**：扩充支持格式（代码类 7 种 + 旧版 Office 3 种），chunking 分派为 document / code / structured_data 三套策略，风险表补充相关兜底，术语表扩充
- **2026-04-22 v2.2**：基于 11 条审视意见全面修正
  - **P0-1**（§4.4）：伪代码从 Python 改为 TypeScript，明确每段代码的执行环境，新增 §4.4.0 执行环境说明
  - **P0-2**（§4.3.1 新增）：补充从 v1 到 v2 的 Schema 迁移策略（Drop & Rebuild + 从 `storage/original/` 重索引）
  - **P0-3**（§4.3）：修正 FTS5 中文分词方案，改用应用层 `nodejieba` 预分词 + `simple` tokenizer，纠正原"unicode61 支持中英文"的错误说法
  - **P1-4**（§4.2.4）：anchor 格式从 `file_path#char_offset` 改为 `file_path#chunk_id`，防止文件修改后 char_offset 漂移导致引用失效
  - **P1-5**（§4.2.5）：**关键修正**——chunk_id 公式从 `sha256(file_path + chunk_index + content[:100])` 改为 `sha256(file_path + content[:500] + occurrence_seq)`，去掉 chunk_index，解决"文档头部插入 → 所有 chunk_id 都变 → 增量复用失效"的硬伤
  - **P1-6**（§6）：路线图调整，Day 1-2 合并为 MVP，Day 3 作为 buffer
  - **P1-7**（§4.4.0）：明确 `rag-service` 通过共享 volume 接收文件路径而非二进制
  - **P2-8**（§5.2）：WebSocket 补充认证（URL token）和重连（指数退避）约定
  - **P2-9**（§4.4.3）：孤儿 GC 增加 5 分钟 grace period 避免并发竞态
  - **P2-10**（§4.2.2）：代码切分的 regex 补充装饰器/注解/缩进的支持，增加 preamble 合并逻辑
  - **P2-11**（§5.1）：明确 Layer 1 与 Layer 2 **同进程调用**（不走 HTTP），补充接口稳定承诺

- **2026-04-22 v2.3**：基于二轮审视的 7 条修正（其中 5 条高风险），闭合数据不变量
  - **Rank 1（硬 bug）**（§4.3）：chunk_id PRIMARY KEY + 先写后删 → PK 冲突。**Schema 拆成 `chunks`（内容）+ `chunk_versions`（版本成员）两表**，同一 chunk_id 可被多个 index_version 引用
  - **Rank 2（硬 bug）**（§5.1）：读路径没按 active index_version 过滤。**统一加 `ACTIVE_CHUNKS_CTE` 基础过滤**，`Layer1Storage` 对 Layer 2 透明（Layer 2 不需要感知版本）
  - **Rank 3**（§4.1 + §4.4.0）：删除 §4.1 里残留的 multipart/form-data 契约，统一成 `{file_path, format}` JSON
  - **Rank 4**（§2 + schema + §5.3）：embedding 模型 / 维度从 schema 和 health 里解耦，改为 config 注入；schema 的 `embedding` 字段通用化，加 `embedding_model`、`embedding_dim` 元数据列
  - **Rank 5**（§5.2）：**保留旧端点 `/api/qa/*` 作为 alias**，不废弃；新旧端点共享同一 handler；明确前端可渐进迁移
  - **Rank 6**（§4.3 schema）：anchor 注释已修正为 `file_path#chunk_id`
  - **Rank 7**（§4.2.5）：在 `chunk_id` 设计处注明 `occurrence_seq` 对"同文件内重复段落前插入"的边缘局限，评估可接受

- **2026-04-22 v2.4**：基于三轮审视的 2 条结构性修正，以及网关模型新信息
  - **Rank 1（建模错误）**（§4.3 + §4.2.4 + §4.4）：v2.3 把 `char_offset_start` / `char_offset_end` / `chunk_index` / `title_path` / `is_truncated` 留在了 chunks 表，但它们**跨版本会变**（用户插入章节、重构标题都会改变）。v2.4 把这些字段**全部搬到 chunk_versions**。**anchor_id 改为 computed（不存储）**，消除"存的值 vs 计算值"的一致性风险。Pipeline 写入逻辑同步重写（每次新版本都为 reuse chunks 写 chunk_versions 新行，记录当前位置）。
  - **Rank 2（红线冲突）**（§1 约束 + §7 Q1 + 风险表）：新信息——网关支持 `glm5/kimi/minimax/qwen 3.6`（聊天模型）。embedding 未明确。Q1 重写为"3 种场景决策树"：网关支持 embedding → 走网关；不支持但本地允许 → 本地 bge-m3；强硬要求全走网关 → 升级组委会。**Day 1 必须先问清楚**。
  - **Rank 3（已承认）**（§4.2.5）：occurrence_seq 的边缘 case 已在 v2.3 记为"已知局限"，v2.4 维持判断：技术文档里完全重复段落罕见，影响可接受
  - **Rank 4（定性变化）**：与当前实现的接口差距从"矛盾"降级为"实施缺口"。路线图里的 Day 4 任务已包含 Schema 迁移，v2.3 §5.2 也补了兼容 alias 策略，不重复修

- **2026-04-22 v2.5**：基于四轮审视的 1 条连动修正，FTS5 同步到 chunk_versions 模型
  - **Rank 1（连动 bug）**（§4.3 FTS + §4.4 Pipeline）：v2.4 把 `title_path` 搬到 chunk_versions，但漏改 FTS5 虚拟表——`chunks_fts` 仍按 `chunk_id` 为键存 `title_path`，BM25 搜到的会是老章节路径
    - **修复**：FTS5 加 `index_version` 字段，按 `(chunk_id, index_version)` 维度索引
    - **写入**：Pipeline 的 9c 步为每个 chunk 的新版本插一行 FTS（即使内容没变，title_path 可能变）
    - **删除**：清理老版本 chunk_versions 时，同步 `deleteFTSByVersion(old_version)`
    - **查询**：`searchBM25` 必须 JOIN `documents.index_version` 过滤到 active 版本的 FTS 行
    - **触发器**：完全移除，FTS 同步统一由应用层负责（因为需要 jieba 分词 + version 逻辑）
  - Rank 2/3/4：维持 v2.4 判断，已是"待确认"或"可接受"状态

- **2026-04-22 v2.5.1**：基于五轮审视的 1 条"改一处漏一处"修正
  - **Rank 1（文档内部不一致）**（§5.1 vs §4.3）：v2.5 修了 §4.3 FTS 章节的 `searchBM25` 示例加上 version 过滤，但**漏改** §5.1 Layer1Storage 内部实现里的同名函数，两处代码不一致
    - **修复**：
      - `ACTIVE_CHUNKS_CTE` 现在额外暴露 `active_version` 字段
      - §5.1 的 `searchBM25` JOIN 条件补上 `AND chunks_fts.index_version = ac.active_version`
      - §4.3 的 `searchBM25` 改为"概念示例"，用同样的 CTE 格式，两处一致
    - 同时：`getChunk` 不涉及 FTS，走 CTE 即可（CTE 已做版本过滤），明确这个区别
  - Rank 2/3/4：维持 v2.4/v2.5 判断

- **2026-04-22 v2.5.2**：基于六轮审视的 7 条修正（P0×1 + P1×3 + P2×3）
  - **P0-1**（§5.1）：searchBM25 的 version 过滤从 JOIN ON 挪到 WHERE 子句，**可读性更强**（功能等价，但 reviewer 一眼能看到）
  - **P1-2**（§4.5 EmbedPool）：剩下的 Python 伪代码（asyncio.Semaphore、@retry）改写成 TypeScript（`p-limit` + 手写指数退避），和 §4.4.0 "Node 主体" 声明对齐；明确并发控制在 Node 侧而非 rag-service
  - **P1-3**（§8 风险表）：补 `nodejieba` 原生模块编译风险（项目已在 `better-sqlite3` 上踩过同类坑）；兜底方案切 `jieba-wasm` 或 `segmentit`；加 FTS5 锁、embedding 维度切换两条风险
  - **P1-4**（§4.4 Pipeline + §4.4.3 GC）：原 step 10 的 FTS/chunk_versions 清理合并进 step 9 事务；GC 里加 FTS/chunk_versions 孤立版本兜底清理，防进程崩溃残留
  - **P2-5**（§5.1 CTE）：`ACTIVE_CHUNKS_CTE` 加 `c.file_path = cv.file_path` 防御性约束
  - **P2-6**（§4.3 schema）：`chunk_versions` 加 `created_at` 字段，方便调试"step 10 失败导致残留旧版本行"的场景
  - **P2-7**（§4.3 FTS）：tokenizer 声明处补说明——因为 content/title_path 已被 jieba 预分词成空格分隔串，`unicode61` 只做空格切分 + 小写归一，这是匹配的（不是冗余 / 错误）
