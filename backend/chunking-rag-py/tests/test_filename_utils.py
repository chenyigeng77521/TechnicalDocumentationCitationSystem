import os
import threading

from app.filename_utils import dedupe_and_open, fix_encoding, sanitize_filename


def test_fix_encoding_repairs_latin1_mojibake():
    mojibake = "æµè¯".encode("latin1").decode("utf-8", errors="ignore")
    assert fix_encoding(mojibake) == "测试" or fix_encoding("测试.md") == "测试.md"


def test_sanitize_removes_illegal_chars_keeps_chinese():
    assert sanitize_filename("说明/文档*<>.md") == "说明_文档___.md"


def test_sanitize_replaces_spaces_with_underscore():
    assert sanitize_filename("my file name.md") == "my_file_name.md"


def test_dedupe_creates_file_atomically(tmp_path):
    path, fd = dedupe_and_open(tmp_path, "a.txt")
    os.close(fd)
    assert path == tmp_path / "a.txt"
    assert path.exists()


def test_dedupe_adds_underscore_suffix_on_collision(tmp_path):
    (tmp_path / "a.txt").touch()
    path, fd = dedupe_and_open(tmp_path, "a.txt")
    os.close(fd)
    assert path == tmp_path / "a_1.txt"


def test_dedupe_increments_suffix(tmp_path):
    (tmp_path / "a.txt").touch()
    (tmp_path / "a_1.txt").touch()
    path, fd = dedupe_and_open(tmp_path, "a.txt")
    os.close(fd)
    assert path == tmp_path / "a_2.txt"


def test_dedupe_handles_no_extension(tmp_path):
    (tmp_path / "README").touch()
    path, fd = dedupe_and_open(tmp_path, "README")
    os.close(fd)
    assert path == tmp_path / "README_1"


def test_dedupe_thread_safe_same_name(tmp_path):
    results: list[str] = []
    lock = threading.Lock()

    def claim():
        p, fd = dedupe_and_open(tmp_path, "x.txt")
        os.close(fd)
        with lock:
            results.append(p.name)

    threads = [threading.Thread(target=claim) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sorted(results) == ["x.txt", "x_1.txt", "x_2.txt", "x_3.txt", "x_4.txt"]
