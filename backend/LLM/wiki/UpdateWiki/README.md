## 知识库增量更新工具

根据 `raw/` 目录中的原始文档，自动检测变更并调用大模型同步更新 `wiki/` 目录下的结构化知识库。

## 功能特性

- **增量检测** ：基于文件 MD5 哈希自动检测 `raw/` 目录的变更，仅处理有变动的文件
- **全量构建** ：支持首次运行时的全量初始化，以及 `--force` 强制全量更新
- **多格式支持** ：支持文本文件、Excel、Word、PDF 等多种原始文档格式
- **智能同步** ：调用大模型自动生成/更新/删除 wiki 页面，并维护索引与交叉引用
- **状态持久化** ：通过 `.raw_manifest` 记录文件状态，实现增量追踪

## 环境要求

- Python 3.8+
- 支持的大模型 API（OpenAI、Azure、Anthropic、DeepSeek、智谱等）


```bash 
update-wiki.sh
```
### 安装依赖

使用 [requirements.txt](requirements.txt)：

```
# 安装
pip install -r requirements.txt
```
主要依赖包括： `openai` 、 `pyyaml` 、 `python-dotenv` 、 `pandas` 、 `python-docx` 、 `PyPDF2` 等。

## 配置文件

### 1\. config.yaml（推荐）

在同目录下创建 `config.yaml` ，配置示例如下：

```
# 知识库更新工具配置文件
llm:
  # API 类型: openai, azure, anthropic, deepseek, zhipu
  api_type: "deepseek"
  # API 密钥（建议优先使用环境变量 LLM_API_KEY）
  api_key: "your-api-key-here"
  # API 地址
  api_base: "https://api.deepseek.com/v1"
  # 模型名称
  model: "deepseek-chat"
  # 温度参数 (0-1)，越低输出越稳定
  temperature: 0.1
  # 最大输出 tokens
  max_tokens: 8192
  # 单文件最大处理长度（超长内容会被截断）
  max_content_length: 5000

paths:
  # 项目根目录（raw/、wiki/、logs/ 所在目录）
  project_root: /absolute/path/to/your/project
  # 原始文档目录（相对 project_root）
  raw_dir: "raw"
  # 输出 wiki 目录（相对 project_root）
  wiki_dir: "wiki"
  # 日志目录（相对 project_root）
  logs_dir: "logs"
  # 状态文件（用于增量检测）
  state_file: ".raw_manifest"
```

**配置优先级** ： 
`config.yaml` > 环境变量 > 默认值。若未指定 `config.yaml` ，程序会自动查找同目录下的 `config.yaml` 。

### 2\. 环境变量（可选）

可通过 `.env` 文件或系统环境变量配置 API 信息：

```
LLM_API_KEY=your-api-key-here
LLM_API_BASE=https://api.openai.com/v1
LLM_MODEL=deepseek-chat
```

## 启动方式

### 基本用法

```bash
# 正常运行（自动检测变更并增量更新）
python update_wiki.py

# 强制全量更新（无视状态文件，处理所有 raw 文件）
python update_wiki.py --force

# 指定配置文件
python update_wiki.py --config /path/to/config.yaml

# 详细输出（DEBUG 级别日志）
python update_wiki.py --verbose

# 组合使用
python update_wiki.py --force --verbose --config ./config.yaml

# 常驻模式
python update_wiki.py --daemon 
python update_wiki.py --daemon --config ./config.yaml        
# 常驻模式，每10分钟检测一次
python update_wiki.py -d -i 600 
```

### 命令行参数说明

| 参数 | 简写 | 说明 |
| --- | --- | --- |
| `--config` | `-c` | 指定配置文件路径 |
| `--force` | `-f` | 强制全量更新模式 |
| `--verbose` | `-v` | 开启详细日志输出 |

### 兼容旧版入口

若存在 `update-wiki.sh` 脚本，也可通过以下方式调用：

```
./update-wiki.sh --force
```

## 目录结构

```
project_root/
├── raw/                 # 原始文档目录（输入）
│   ├── doc1.md
│   ├── doc2.xlsx
│   └── ...
├── wiki/                # 结构化知识库（输出，由程序自动生成）
│   ├── index.md         # 知识库索引
│   ├── log.md           # 更新日志
│   └── *.md             # 各主题页面
├── logs/                # 运行日志
│   └── auto-update.log
├── .raw_manifest        # 文件状态记录（增量检测用）
├── config.yaml          # 配置文件
└── update_wiki.py       # 主程序
```

## 工作原理

1. **变更检测** ： `ChangeDetector` 计算 `raw/` 目录下所有文件的 MD5，与 `.raw_manifest` 中的历史状态对比，输出变更文件列表
2. **大模型处理** ： `LLMClient` 将变更文件内容、现有 wiki 结构等信息组装成 Prompt，调用大模型生成需要执行的文件操作（创建/更新/删除）
3. **文件执行** ： `FileExecutor` 根据大模型返回的 JSON 结果，实际写入、修改或删除 `wiki/` 下的文件，并更新 `index.md` 与 `log.md`

## 注意事项

1. **API 密钥安全** ：切勿将包含真实 API Key 的 `config.yaml` 提交到版本控制。建议通过环境变量 `LLM_API_KEY` 注入密钥，或将 `config.yaml` 加入 `.gitignore`
2. **project\_root 路径** ： `config.yaml` 中的 `project_root` 必须为 **绝对路径** ，否则可能导致目录解析错误
3. **首次运行** ：首次运行时会自动进入全量构建模式，生成完整的 wiki 结构。请确保 `raw/` 目录已准备好原始文档
4. **文件大小限制** ：单文件超过 `max_file_size` （默认 1MB）或内容超过 `max_content_length` （默认 5000 字符）时，内容会被截断处理。超大文件建议提前拆分
5. **状态文件勿删** ：`.raw_manifest` 是增量检测的核心，删除后将导致下次运行进入全量构建模式
6. **大模型费用** ：全量更新会消耗较多 Token，建议在正式运行前先用少量文件测试
7. **编码问题** ：程序默认使用 UTF-8 编码读取文件，请确保原始文档编码正确，否则可能出现乱码或读取失败
8. **网络稳定性** ：调用大模型 API 时若网络中断，程序会报错退出，已执行的操作不会回滚，建议检查网络后重新运行