"""Architecture forcing-functions: keep the lib primitives load-bearing.

Static (AST) checks over the source, not behavioural tests. They exist because
the recurring failure mode in this codebase is an adapter (cli/mcp/api/dashboard)
or a sibling lib module reaching around a primitive with its own inline copy,
which then drifts. A unit test can't see that — it passes on each copy
independently. These tests fail the moment a new inline copy appears.
"""
import ast
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_SRC = _REPO / "src" / "owm"
_DASHBOARD = _REPO / "dashboard"

# git is shelled out from exactly these modules; everywhere else routes through
# their readers (sync.git_run / repo_sync_status / read_repo_state, the worktree
# helpers, the bare-repo clone/fetch). Adding a module here must be a deliberate
# decision, not a way to silence a new violation.
_GIT_OWNING = {"sync.py", "worktrees.py", "workspace.py"}

# The production surface the rules apply to.
_MODULES = [*sorted(_SRC.glob("*.py")), _DASHBOARD / "server.py"]


def _git_subprocess_lines(source: str) -> list[int]:
    """Line numbers of subprocess.<fn>([...]) calls whose command is a literal
    list/tuple starting with the string "git"."""
    hits = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if not (isinstance(fn, ast.Attribute)
                and isinstance(fn.value, ast.Name)
                and fn.value.id == "subprocess"):
            continue
        if not node.args:
            continue
        cmd = node.args[0]
        if isinstance(cmd, (ast.List, ast.Tuple)) and cmd.elts:
            head = cmd.elts[0]
            if isinstance(head, ast.Constant) and head.value == "git":
                hits.append(node.lineno)
    return hits


@pytest.mark.architecture
@pytest.mark.parametrize("module", _MODULES, ids=lambda p: p.name)
def test_git_invoked_only_in_lib_primitives(module):
    """No module outside sync/worktrees/workspace may shell out to git directly.

    Route reads through owm.sync (git_run and the readers built on it); add a new
    primitive there if none fits, rather than an inline subprocess(["git", ...]).
    """
    if module.name in _GIT_OWNING:
        return
    hits = _git_subprocess_lines(module.read_text())
    assert not hits, (
        f"{module.name} invokes git directly at line(s) {hits}; route through an "
        f"owm.sync primitive (git_run / a reader) instead of subprocess(['git', ...])."
    )
