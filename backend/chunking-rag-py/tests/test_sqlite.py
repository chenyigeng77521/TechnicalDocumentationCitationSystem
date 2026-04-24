import sqlite3
import uuid
from pathlib import Path

import pytest

from app.database.sqlite import Db, init_db, write_tx


@pytest.fixture
def db_path(tmp_path) -> Path:
    p = tmp_path / "k.db"
    init_db(p)
    return p


@pytest.fixture
def conn(db_path):
    c = sqlite3.connect(db_path, isolation_level=None)
    c.execute("PRAGMA busy_timeout=10000;")
    c.execute("PRAGMA foreign_keys=ON;")
    yield c
    c.close()


def test_init_db_creates_schema(db_path):
    c = sqlite3.connect(db_path)
    tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"files", "chunks"} <= tables
    c.close()


def test_init_db_enables_wal_persistently(db_path):
    c = sqlite3.connect(db_path)
    mode = c.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"
    c.close()


def test_init_db_is_idempotent(db_path):
    init_db(db_path)
    init_db(db_path)
    c = sqlite3.connect(db_path)
    tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"files", "chunks"} <= tables
    c.close()


def test_insert_and_get_file(conn):
    db = Db(conn)
    fid = str(uuid.uuid4())
    db.insert_file(
        id=fid, original_name="a.md", original_path="raw/a.md", converted_path="",
        format="md", size=100, upload_time="2026-04-23T00:00:00", status="converting"
    )
    row = db.get_file(fid)
    assert row["original_name"] == "a.md"
    assert row["status"] == "converting"


def test_update_file_status_transitions(conn):
    db = Db(conn)
    fid = str(uuid.uuid4())
    db.insert_file(id=fid, original_name="a.md", original_path="", converted_path="",
                   format="md", size=0, upload_time="", status="converting")
    db.update_file_status(fid, "completed")
    assert db.get_file(fid)["status"] == "completed"
    db.update_file_status(fid, "failed")
    assert db.get_file(fid)["status"] == "failed"


def test_insert_chunks_and_cascade_delete(conn):
    db = Db(conn)
    fid = str(uuid.uuid4())
    db.insert_file(id=fid, original_name="a.md", original_path="", converted_path="",
                   format="md", size=0, upload_time="", status="completed")
    chunks = [
        dict(id=str(uuid.uuid4()), file_id=fid, content="c1", start_line=1, end_line=2,
             original_lines=[1, 2], vector=[0.1] * 1024),
        dict(id=str(uuid.uuid4()), file_id=fid, content="c2", start_line=3, end_line=4,
             original_lines=[3, 4], vector=[0.2] * 1024),
    ]
    db.insert_chunks(chunks)
    assert len(db.get_chunks_by_file(fid)) == 2

    db.delete_file_and_chunks(fid)
    assert db.get_file(fid) is None
    assert db.get_chunks_by_file(fid) == []


def test_vector_json_roundtrip(conn):
    db = Db(conn)
    fid = str(uuid.uuid4())
    db.insert_file(id=fid, original_name="a.md", original_path="", converted_path="",
                   format="md", size=0, upload_time="", status="completed")
    vec = [0.5] * 1024
    db.insert_chunks([dict(id="c1", file_id=fid, content="x", start_line=1, end_line=1,
                           original_lines=[1], vector=vec)])
    got = db.get_chunks_by_file(fid)[0]
    assert got["vector"] == vec


def test_stats_counts_only_completed(conn):
    db = Db(conn)
    for i, st in enumerate(["completed", "converting", "failed", "completed"]):
        db.insert_file(id=f"f{i}", original_name=f"{i}.md", original_path="", converted_path="",
                       format="md", size=0, upload_time="", status=st)
    stats = db.get_stats()
    assert stats == {"fileCount": 2, "chunkCount": 0}


def test_get_completed_chunks_filters_status(conn):
    db = Db(conn)
    db.insert_file(id="f1", original_name="1.md", original_path="", converted_path="",
                   format="md", size=0, upload_time="", status="completed")
    db.insert_file(id="f2", original_name="2.md", original_path="", converted_path="",
                   format="md", size=0, upload_time="", status="converting")
    db.insert_chunks([
        dict(id="c1", file_id="f1", content="ok", start_line=1, end_line=1, original_lines=[1], vector=[0.0] * 1024),
        dict(id="c2", file_id="f2", content="hidden", start_line=1, end_line=1, original_lines=[1], vector=[0.0] * 1024),
    ])
    chunks = db.get_completed_chunks()
    assert {c["id"] for c in chunks} == {"c1"}


def test_write_tx_rolls_back_on_exception(conn):
    db = Db(conn)
    db.insert_file(id="f1", original_name="x.md", original_path="", converted_path="",
                   format="md", size=0, upload_time="", status="converting")
    with pytest.raises(RuntimeError):
        with write_tx(conn):
            conn.execute("UPDATE files SET status='completed' WHERE id=?", ("f1",))
            raise RuntimeError("boom")
    assert db.get_file("f1")["status"] == "converting"


def test_write_tx_commits_on_success(conn):
    db = Db(conn)
    db.insert_file(id="f1", original_name="x.md", original_path="", converted_path="",
                   format="md", size=0, upload_time="", status="converting")
    with write_tx(conn):
        conn.execute("UPDATE files SET status='completed' WHERE id=?", ("f1",))
    assert db.get_file("f1")["status"] == "completed"
