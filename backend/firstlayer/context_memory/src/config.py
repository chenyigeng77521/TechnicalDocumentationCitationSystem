# -*- coding: utf-8 -*-
"""
Context Memory 配置文件
"""

import os
from pathlib import Path

# 获取当前文件所在目录
BASE_DIR = Path(__file__).parent.parent

# 数据目录
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# 会话数据文件
SESSIONS_FILE = DATA_DIR / "sessions.json"

# 服务器配置
PORT = int(os.getenv("CONTEXT_MEMORY_PORT", "3006"))
HOST = os.getenv("CONTEXT_MEMORY_HOST", "0.0.0.0")

# 记忆配置
MAX_CONVERSATIONS = 30  # 最多保存 30 组问答
