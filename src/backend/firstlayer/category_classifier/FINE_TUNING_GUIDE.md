# GLiClass 模型微调指南

## 概述

本指南介绍如何微调 `google/flan-t5-base` 模型以改进问题分类任务。

## 分类类别定义

| 标签 | 描述 | 示例 |
|------|------|------|
| FACT | 事实型 - 询问具体事实、数据、定义、名称等 | "年假有多少天？"、"公司总部在哪里？" |
| PROC | 过程型 - 询问步骤、流程、操作方法 | "如何申请年假？"、"入职流程是什么？" |
| EXPL | 解释型 - 询问原因、原理、机制 | "为什么需要试用期？"、"社保是如何计算的？" |
| COMP | 比较型 - 询问对比、差异、优劣 | "正式员工和实习生的区别？" |
| META | 元认知型 - 询问学习方法、策略、反思 | "怎么提高工作效率？"、"如何提升沟通能力？" |

---

## 步骤 1: 准备训练数据

### 数据格式

创建 `data/train.jsonl` 文件，每行一个 JSON 对象：

```json
{"question": "年假有多少天？", "label": "FACT"}
{"question": "如何申请年假？", "label": "PROC"}
{"question": "为什么需要试用期？", "label": "EXPL"}
{"question": "正式员工和实习生的区别？", "label": "COMP"}
{"question": "怎么提高工作效率？", "label": "META"}
```

### 数据量建议

| 数据量 | 预期效果 | 训练时间 |
|--------|---------|---------|
| 500 样本 | 基础改进 | ~30 分钟 |
| 1000 样本 | 明显改进 | ~1 小时 |
| 5000 样本 | 显著改进 | ~4 小时 |

### 数据标注模板

```python
# 快速标注脚本示例
questions = [
    "新员工入职需要准备哪些材料？",  # PROC
    "公司年假政策是什么？",  # FACT
    "为什么要有试用期？",  # EXPL
    "带薪年假和病假有什么区别？",  # COMP
    "如何快速适应新环境？",  # META
]
```

---

## 步骤 2: 安装依赖

```bash
cd backend/firstlayer
pip install datasets evaluate accelerate scikit-learn
```

---

## 步骤 3: 创建微调脚本

创建 `train_classifier.py`：

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GLiClass 模型微调脚本
"""

import json
import torch
import numpy as np
from datasets import Dataset, DatasetDict
from transformers import (
    AutoTokenizer, 
    AutoModelForSeq2SeqLM,
    DataCollatorForSeq2Seq,
    TrainingArguments,
    Trainer,
    set_seed
)
import evaluate

# 设置随机种子
set_seed(42)

# 配置
MODEL_NAME = "google/flan-t5-base"
TRAIN_DATA_PATH = "data/train.jsonl"
VALID_DATA_PATH = "data/valid.jsonl"
OUTPUT_DIR = "models/fine-tuned-classifier"
NUM_EPOCHS = 3
BATCH_SIZE = 16
MAX_LENGTH = 128

# 标签映射
LABELS = ["FACT", "PROC", "EXPL", "COMP", "META"]
LABEL_TO_ID = {label: i for i, label in enumerate(LABELS)}
ID_TO_LABEL = {i: label for i, label in enumerate(LABELS)}


def load_data(jsonl_path):
    """加载 JSONL 数据"""
    data = []
    with open(jsonl_path, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                data.append(json.loads(line))
    return data


def preprocess_function(examples):
    """预处理文本"""
    # 添加提示词引导模型
    inputs = [f"Classify question: {q}" for q in examples["question"]]
    
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
    model_inputs = tokenizer(inputs, max_length=MAX_LENGTH, truncation=True)
    
    # 编码标签
    labels = tokenizer([f"{LABEL_TO_ID[label]}" for label in examples["label"]])
    model_inputs["labels"] = labels["input_ids"]
    
    return model_inputs


def compute_metrics(eval_pred):
    """计算评估指标"""
    accuracy = evaluate.load("accuracy")
    predictions, labels = eval_pred
    
    # 解码预测结果
    predictions = np.argmax(predictions, axis=-1)
    
    return {"accuracy": accuracy.compute(predictions=predictions, references=labels)}


def main():
    print("=" * 60)
    print("  GLiClass 模型微调")
    print("=" * 60)
    
    # 1. 加载数据
    print("\n📊 加载训练数据...")
    train_data = load_data(TRAIN_DATA_PATH)
    valid_data = load_data(VALID_DATA_PATH) if valid_data_path else train_data[:len(train_data)//5]
    
    print(f"   训练集：{len(train_data)} 样本")
    print(f"   验证集：{len(valid_data)} 样本")
    
    # 2. 创建 Dataset
    train_dataset = Dataset.from_list(train_data)
    valid_dataset = Dataset.from_list(valid_data)
    dataset = DatasetDict({"train": train_dataset, "validation": valid_dataset})
    
    # 3. 加载 tokenizer
    print("\n🔧 加载 tokenizer...")
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
    
    # 4. 预处理
    print("\n📝 预处理数据...")
    tokenized_datasets = dataset.map(
        preprocess_function,
        batched=True,
        remove_columns=["question", "label"]
    )
    
    # 5. 加载模型
    print("\n🤖 加载模型...")
    model = AutoModelForSeq2SeqLM.from_pretrained(MODEL_NAME)
    
    # 6. 设置数据 collator
    data_collator = DataCollatorForSeq2Seq(tokenizer, model=model)
    
    # 7. 训练参数
    training_args = TrainingArguments(
        output_dir=OUTPUT_DIR,
        num_train_epochs=NUM_EPOCHS,
        per_device_train_batch_size=BATCH_SIZE,
        per_device_eval_batch_size=BATCH_SIZE,
        learning_rate=3e-5,
        evaluation_strategy="epoch",
        save_strategy="epoch",
        load_best_model_at_end=True,
        metric_for_best_model="accuracy",
        logging_steps=50,
        warmup_ratio=0.1,
        weight_decay=0.01,
        report_to="none",
        push_to_hub=False,
    )
    
    # 8. 创建 Trainer
    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=tokenized_datasets["train"],
        eval_dataset=tokenized_datasets["validation"],
        tokenizer=tokenizer,
        data_collator=data_collator,
        compute_metrics=compute_metrics,
    )
    
    # 9. 开始训练
    print("\n🚀 开始训练...")
    print(f"   设备：{torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU'}")
    
    trainer.train()
    
    # 10. 评估
    print("\n📊 评估模型...")
    eval_results = trainer.evaluate()
    print(f"   验证集准确率：{eval_results['eval_accuracy']:.4f}")
    
    # 11. 保存模型
    print(f"\n💾 保存模型到 {OUTPUT_DIR}...")
    trainer.save_model(OUTPUT_DIR)
    tokenizer.save_pretrained(OUTPUT_DIR)
    
    # 保存标签映射
    with open(f"{OUTPUT_DIR}/label_map.json", "w", encoding="utf-8") as f:
        json.dump({"label_to_id": LABEL_TO_ID, "id_to_label": ID_TO_LABEL}, f, ensure_ascii=False, indent=2)
    
    print("\n✅ 微调完成！")
    print(f"\n📁 模型位置：{OUTPUT_DIR}")
    print("📋 使用方法:")
    print("   修改 config.py 中的 MODEL_NAME 为微调后的模型路径")
    print("   MODEL_NAME = 'models/fine-tuned-classifier'")


if __name__ == "__main__":
    main()
```

---

## 步骤 4: 创建示例数据

创建 `data/train.jsonl`（至少 100 条）：

```bash
mkdir -p data
```

```python
# generate_sample_data.py - 生成示例数据
import json

samples = [
    # FACT 类型
    ("公司总部在哪里？", "FACT"),
    ("年假有多少天？", "FACT"),
    ("社保缴纳比例是多少？", "FACT"),
    ("入职体检需要多少钱？", "FACT"),
    ("员工工号在哪里查看？", "FACT"),
    ("公司几点下班？", "FACT"),
    ("工资什么时候发？", "FACT"),
    ("办公室在几楼？", "FACT"),
    ("公司有多少员工？", "FACT"),
    ("老板叫什么名字？", "FACT"),
    
    # PROC 类型
    ("如何申请年假？", "PROC"),
    ("怎么办理入职手续？", "PROC"),
    ("如何提交报销单？", "PROC"),
    ("怎样申请请假？", "PROC"),
    ("怎么开通邮箱账号？", "PROC"),
    ("如何申请加班？", "PROC"),
    ("怎样申请调休？", "PROC"),
    ("如何办理离职手续？", "PROC"),
    ("怎么申请出差？", "PROC"),
    ("如何申请培训？", "PROC"),
    
    # EXPL 类型
    ("为什么需要试用期？", "EXPL"),
    ("为什么要交社保？", "EXPL"),
    ("为什么要有保密协议？", "EXPL"),
    ("为什么工资要扣税？", "EXPL"),
    ("为什么要签劳动合同？", "EXPL"),
    ("为什么会有年终奖？", "EXPL"),
    ("为什么要进行背景调查？", "EXPL"),
    ("为什么需要转正答辩？", "EXPL"),
    ("为什么要规定工作时间？", "EXPL"),
    ("为什么要有绩效考核？", "EXPL"),
    
    # COMP 类型
    ("正式员工和实习生的区别？", "COMP"),
    ("带薪年假和病假有什么不同？", "COMP"),
    ("五险一金和社保有什么区别？", "COMP"),
    ("调休和加班费哪个更好？", "COMP"),
    ("合同工和派遣工的区别？", "COMP"),
    ("绩效 A 和绩效 B 有什么不同？", "COMP"),
    ("年终奖和 13 薪有什么区别？", "COMP"),
    ("远程办公和现场办公哪个更好？", "COMP"),
    ("试用期工资和转正后一样吗？", "COMP"),
    ("调休和请假有什么不同？", "COMP"),
    
    # META 类型
    ("怎么提高工作效率？", "META"),
    ("如何快速适应新环境？", "META"),
    ("怎么和同事搞好关系？", "META"),
    ("如何提升沟通能力？", "META"),
    ("怎样做好时间管理？", "META"),
    ("怎么应对工作压力？", "META"),
    ("如何规划职业发展？", "META"),
    ("怎样提高工作效率？", "META"),
    ("怎么做好团队协作？", "META"),
    ("如何提升专业技能？", "META"),
]

# 生成 100 条训练数据
with open("data/train.jsonl", "w", encoding="utf-8") as f:
    for question, label in samples * 10:  # 重复 10 次得到 100 条
        f.write(json.dumps({"question": question, "label": label}, ensure_ascii=False) + "\n")

print("✅ 已生成 100 条训练数据到 data/train.jsonl")
```

运行生成脚本：
```bash
python generate_sample_data.py
```

---

## 步骤 5: 开始训练

```bash
# 使用 GPU 训练（如果有）
python train_classifier.py

# 或仅使用 CPU
CUDA_VISIBLE_DEVICES="" python train_classifier.py
```

训练输出示例：
```
============================================================
  GLiClass 模型微调
============================================================

📊 加载训练数据...
   训练集：100 样本
   验证集：20 样本

🔧 加载 tokenizer...
📝 预处理数据...
🤖 加载模型...

🚀 开始训练...
   设备：NVIDIA A100-SXM4-40GB

Epoch 1/3: 100%|██████████| 6/6 [00:15<00:00,  2.53s/it]
Epoch 2/3: 100%|██████████| 6/6 [00:14<00:00,  2.41s/it]
Epoch 3/3: 100%|██████████| 6/6 [00:13<00:00,  2.25s/it]

📊 评估模型...
   验证集准确率：0.8500

💾 保存模型到 models/fine-tuned-classifier...

✅ 微调完成！
```

---

## 步骤 6: 使用微调后的模型

修改 `config.py`：

```python
# 将模型路径改为微调后的模型
GLIClass_MODEL_NAME = "models/fine-tuned-classifier"  # 使用微调后的模型
```

然后重启服务：
```bash
pkill -f uvicorn
cd backend/firstlayer
nohup python3 -m uvicorn src.app:app --host 0.0.0.0 --port 3004 > /tmp/firstlayer.log 2>&1 &
```

---

## 常见问题

### Q: 训练太慢？
- 减小 `BATCH_SIZE`
- 使用 GPU（推荐）
- 减少 `NUM_EPOCHS`

### Q: 准确率不高？
- 增加训练数据量
- 检查数据标注质量
- 增加训练轮数

### Q: 内存不足？
- 减小 `BATCH_SIZE`
- 使用梯度累积
- 使用更小的模型（如 flan-t5-small）

---

## 参考资源

- [Hugging Face Transformers 文档](https://huggingface.co/docs/transformers/)
- [Text Classification 教程](https://huggingface.co/docs/transformers/tasks/sequence_classification)
- [FLAN-T5 模型卡](https://huggingface.co/google/flan-t5-base)
