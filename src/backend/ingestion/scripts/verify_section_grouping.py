"""校验 (file_path, title_path) 分组的 chunk_index 连续性。

Spec: docs/superpowers/specs/2026-04-30-x15-rigorous-design.md §2.1 显式假设

未来若 chunker 升级 / 文档新增 / reindex 引入边角 case（同文件下两个不同物理 section 共享相同 title_path 文本），
分组逻辑会静默误并这两段。本脚本提前抓出。

退出码：
  0 = 全部通过
  1 = 发现违规
"""
import sys
import sqlite3
from pathlib import Path

DB_PATH = Path("backend/storage/index/knowledge.db")


def verify_section_grouping(conn) -> list[str]:
    """检查所有 (file_path, title_path) 分组的 chunk_index 连续性。返回违规组列表。"""
    rows = conn.execute("""
        SELECT file_path, COALESCE(title_path,'') AS tp,
               GROUP_CONCAT(chunk_index ORDER BY chunk_index) AS idx_list,
               COUNT(*) AS cnt
        FROM chunks
        WHERE title_path IS NOT NULL AND title_path != ''
        GROUP BY file_path, COALESCE(title_path,'')
        HAVING cnt > 1
    """).fetchall()
    violations = []
    for r in rows:
        indices = [int(x) for x in r['idx_list'].split(',')]
        if any(indices[i+1] - indices[i] != 1 for i in range(len(indices)-1)):
            violations.append(f"{r['file_path']} | tp={r['tp']!r}: {indices}")
    return violations


def main():
    if not DB_PATH.exists():
        print(f"❌ DB 不存在: {DB_PATH}")
        sys.exit(2)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    violations = verify_section_grouping(conn)

    total = conn.execute(
        "SELECT COUNT(DISTINCT file_path || '|' || COALESCE(title_path, '')) FROM chunks "
        "WHERE title_path IS NOT NULL AND title_path != ''"
    ).fetchone()[0]
    conn.close()

    if violations:
        print(f"❌ 发现 {len(violations)} 个分组假设违规（共 {total} 个 SECTION 组）：")
        for v in violations[:20]:
            print(f"  {v}")
        if len(violations) > 20:
            print(f"  ... 共 {len(violations)} 项，仅展示前 20")
        print()
        print("X1.5 (file_path, title_path) 分组假设失效，需排查 chunker 输出或语料是否有重复 title_path。")
        sys.exit(1)
    else:
        print(f"✅ 所有 SECTION 分组的 chunk_index 100% 连续（共 {total} 个组），X1.5 分组假设成立")


if __name__ == "__main__":
    main()
