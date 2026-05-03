#!/usr/bin/env bash
# 停止 Ingestion Service（生产模式）
#
# 实际复用 stop.sh 的逻辑（kill PID 文件 + 端口兜底，不依赖 Python 环境）。
# 这个 wrapper 只是命名对称：start-prod.sh ↔ stop-prod.sh。
exec "$(dirname "$0")/stop.sh" "$@"
