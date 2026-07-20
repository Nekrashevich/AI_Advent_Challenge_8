from __future__ import annotations

import subprocess
from pathlib import Path

from budget_pipeline.config import GENERATED_DIR, REPO_ROOT, ROOT


class ToolError(RuntimeError):
    pass


def _run_git(*args: str) -> str:
    process = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )
    if process.returncode:
        raise ToolError(process.stderr.strip() or f"git {' '.join(args)} failed")
    return process.stdout.strip()


def git_context() -> dict:
    status = _run_git("status", "--short", "--", "week7_budget")
    return {
        "branch": _run_git("branch", "--show-current"),
        "head": _run_git("rev-parse", "--short", "HEAD"),
        "last_commit": _run_git("log", "-1", "--pretty=%s"),
        "dirty": bool(status),
        "changed_files": [line[3:] for line in status.splitlines() if len(line) > 3],
    }


def git_diff(base: str = "", head: str = "") -> dict:
    if base and head:
        diff = _run_git("diff", "--no-ext-diff", f"{base}...{head}", "--", "week7_budget")
        files = _run_git("diff", "--name-only", f"{base}...{head}", "--", "week7_budget")
        range_name = f"{base}...{head}"
    else:
        diff = _run_git("diff", "--no-ext-diff", "HEAD", "--", "week7_budget")
        files = _run_git("diff", "--name-only", "HEAD", "--", "week7_budget")
        range_name = "HEAD (working tree)"
    return {"range": range_name, "files": files.splitlines() if files else [], "diff": diff}


def _safe_project_path(relative_path: str) -> Path:
    candidate = (ROOT / relative_path).resolve()
    if candidate != ROOT and ROOT not in candidate.parents:
        raise ToolError("Путь выходит за пределы week7_budget")
    return candidate


def list_files(pattern: str = "**/*", limit: int = 200) -> dict:
    files = [
        str(path.relative_to(ROOT))
        for path in sorted(ROOT.glob(pattern))
        if path.is_file() and ".venv" not in path.parts and "runtime" not in path.parts
    ][: max(1, min(limit, 500))]
    return {"pattern": pattern, "count": len(files), "files": files}


def read_file(path: str, start: int = 1, end: int = 0) -> dict:
    target = _safe_project_path(path)
    if not target.is_file():
        raise ToolError(f"Файл не найден: {path}")
    lines = target.read_text(encoding="utf-8").splitlines()
    first = max(start, 1)
    last = min(end or first + 399, len(lines), first + 399)
    selected = lines[first - 1:last]
    return {
        "path": path,
        "start": first,
        "end": last,
        "total_lines": len(lines),
        "text": "\n".join(f"{number:4}: {line}" for number, line in enumerate(selected, first)),
    }


def write_generated_file(path: str, content: str, confirm: bool = False) -> dict:
    if not confirm:
        raise ToolError("Для записи требуется confirm=true")
    target = (GENERATED_DIR / path).resolve()
    if target != GENERATED_DIR and GENERATED_DIR not in target.parents:
        raise ToolError("Запись разрешена только в runtime/generated")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content.rstrip() + "\n", encoding="utf-8")
    return {
        "path": str(target.relative_to(ROOT)),
        "bytes": target.stat().st_size,
        "status": "written",
    }

