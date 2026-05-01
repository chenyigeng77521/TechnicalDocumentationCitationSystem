#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NLU 模型下载脚本
一键下载所有需要的 NLU 模型到本地
"""

import os
import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))

from huggingface_hub import snapshot_download


def download_models():
    """下载所有 NLU 模型"""
    
    # 获取项目根目录
    project_root = Path(__file__).parent.parent.parent.parent
    models_dir = project_root / "models"
    models_dir.mkdir(exist_ok=True)
    
    print("=" * 60)
    print("🚀 开始下载 NLU 模型")
    print("=" * 60)
    
    # 模型列表
    models = [
        {
            "name": "Qwen2.5-0.5B (指代消解 + 查询改写)",
            "repo_id": "Qwen/Qwen2.5-0.5B-Instruct",
            "local_dir": models_dir / "qwen2.5-0.5b"
        },
        {
            "name": "chinese-roberta-wwm-ext (完整性检查)",
            "repo_id": "hfl/chinese-roberta-wwm-ext",
            "local_dir": models_dir / "chinese-roberta-wwm-ext"
        }
    ]
    
    for model in models:
        model_name = model["name"]
        repo_id = model["repo_id"]
        local_dir = str(model["local_dir"])
        
        print(f"\n📦 下载：{model_name}")
        print(f"   仓库：{repo_id}")
        print(f"   目标：{local_dir}")
        
        if os.path.exists(local_dir) and os.listdir(local_dir):
            print(f"   ⚠️  模型已存在，跳过")
            continue
        
        try:
            snapshot_download(
                repo_id=repo_id,
                local_dir=local_dir,
                cache_dir=str(models_dir / "cache")
            )
            print(f"   ✅ 下载完成")
        except Exception as e:
            print(f"   ❌ 下载失败：{str(e)}")
            return False
    
    print("\n" + "=" * 60)
    print("✅ 所有模型下载完成！")
    print("=" * 60)
    
    # 显示模型信息
    print("\n📊 模型目录结构:")
    for model in models:
        local_dir = str(model["local_dir"])
        if os.path.exists(local_dir):
            files = os.listdir(local_dir)
            print(f"\n{model['local_dir'].name}/")
            for f in files[:10]:  # 只显示前 10 个文件
                print(f"  ├── {f}")
            if len(files) > 10:
                print(f"  └── ... ({len(files) - 10} more files)")
    
    return True


if __name__ == "__main__":
    success = download_models()
    sys.exit(0 if success else 1)
