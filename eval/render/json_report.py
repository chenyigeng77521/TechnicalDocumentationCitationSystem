"""JSON report writer."""
from __future__ import annotations
import json


def render_json(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)
