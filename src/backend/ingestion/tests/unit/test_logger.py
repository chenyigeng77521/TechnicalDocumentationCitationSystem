"""测试 JSON line logger。"""
import json
from backend.ingestion.common.logger import get_logger


def test_logger_writes_json_lines(tmp_path):
    log_file = tmp_path / "test.log"
    logger = get_logger("test_module_1", log_file=log_file)
    logger.info("hello", extra={"chunk_id": "abc123"})
    lines = log_file.read_text().strip().split("\n")
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["message"] == "hello"
    assert record["level"] == "INFO"
    assert record["module"] == "test_module_1"
    assert record["chunk_id"] == "abc123"


def test_logger_levels(tmp_path):
    log_file = tmp_path / "test.log"
    logger = get_logger("test_module_2", log_file=log_file)
    logger.warning("warn msg")
    logger.error("err msg")
    lines = log_file.read_text().strip().split("\n")
    assert len(lines) == 2
    assert json.loads(lines[0])["level"] == "WARNING"
    assert json.loads(lines[1])["level"] == "ERROR"
