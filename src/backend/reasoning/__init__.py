# Layer 3 — 推理与引用层
import os
import sys

# Ensure current dir is in path for absolute imports in reasoning.py
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from .reasoning import build_citations, build_context_blocks, run_reasoning

__all__ = ["build_citations", "build_context_blocks", "run_reasoning"]
