"""Unit test: AST-based regression guard for init_db single-source-of-truth.

确保 routes_search / routes_index 函数体内不再调用 init_db()。
init_db 应只在 server.create_app() 启动时调用一次。

Refs: docs/superpowers/plans/2026-05-07-ingestion-init-db-once.md
"""
import ast
import inspect

import pytest

from backend.ingestion.api import routes_index, routes_search


def _find_init_db_calls(module) -> list[tuple[str, int]]:
    """遍历模块 AST，返回函数体内所有 init_db(...) 调用位置。

    返回列表元素：(函数名, 行号)。空列表表示函数体里没有 init_db 调用。

    AST 解析的 robustness（vs 字符串匹配）:
    - 注释里的 # init_db(...) → 不会误报（注释不进 AST）
    - docstring 里提到 init_db → 不会误报（字符串字面量是 ast.Constant 不是 ast.Call）
    - import 行 from x import init_db → 不会误报（ImportFrom 不是 Call）
    - 变量名碰巧叫 init_db_logged → 不会误报（Name.id 必须精确等于 'init_db'）
    """
    source = inspect.getsource(module)
    tree = ast.parse(source)
    results: list[tuple[str, int]] = []

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for child in ast.walk(node):
                if (
                    isinstance(child, ast.Call)
                    and isinstance(child.func, ast.Name)
                    and child.func.id == "init_db"
                ):
                    results.append((node.name, child.lineno))
    return results


@pytest.mark.parametrize(
    "module, module_name",
    [
        (routes_search, "routes_search"),
        (routes_index, "routes_index"),
    ],
)
def test_no_init_db_call_in_request_path(module, module_name):
    """守不变量：业务路由函数体内不应再调 init_db。

    init_db 已在 server.create_app() 启动时调用一次。
    请求路径再调会引入 50-200ms 开销 + sqlite_master 锁竞争（云主机慢盘下导致 :3003 timeout）。
    """
    calls = _find_init_db_calls(module)
    assert calls == [], (
        f"{module_name} 函数体内不应有 init_db() 调用，发现:\n"
        + "\n".join(f"  - 函数 {fn} 第 {ln} 行" for fn, ln in calls)
        + "\n\ninit_db 已在 server.create_app() 启动时跑过。"
        "请删除请求路径里的冗余调用，参考:\n"
        "  docs/superpowers/plans/2026-05-07-ingestion-init-db-once.md"
    )


def test_server_create_app_calls_init_db_once():
    """守不变量：server.create_app() 函数体内必须有且只有 1 处 init_db() 调用。

    这是 init_db single-source-of-truth 的另一面：startup 必须 init，
    不能因为重构不小心把 startup init 也删了。
    """
    from backend.ingestion.api import server
    calls = _find_init_db_calls(server)
    create_app_calls = [c for c in calls if c[0] == "create_app"]
    assert len(create_app_calls) == 1, (
        f"server.create_app() 应有且仅有 1 处 init_db() 调用，"
        f"实际找到 {len(create_app_calls)} 处: {create_app_calls}"
    )
