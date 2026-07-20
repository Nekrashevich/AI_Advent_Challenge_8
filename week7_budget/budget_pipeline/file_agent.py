from __future__ import annotations

import difflib
from datetime import datetime, timezone

from budget_pipeline import data
from budget_pipeline.llm import LLMResult, ProxyAPIClient, ProxyAPIError
from budget_pipeline.mcp_bridge import McpBridge


ALLOWED_READ_FILES = (
    "data/transactions.csv",
    "docs/data-schema.md",
    "docs/runbook.md",
    "budget_pipeline/data.py",
)

DEFAULT_PLAN = {
    "read_files": ["data/transactions.csv", "docs/data-schema.md", "docs/runbook.md"],
    "diff_target": "docs/data-schema.md",
    "artifact": "data-quality-report.md",
    "reason": "Проверить CSV по схеме, сверить правила эксплуатации и сохранить аудит с diff документации.",
}


def _validated_plan(payload: dict, available_files: set[str]) -> tuple[dict, str]:
    if not isinstance(payload, dict):
        return dict(DEFAULT_PLAN), "fallback"
    requested = payload.get("read_files")
    if not isinstance(requested, list):
        return dict(DEFAULT_PLAN), "fallback"
    read_files = list(dict.fromkeys(str(path) for path in requested))
    diff_target = str(payload.get("diff_target", ""))
    artifact = str(payload.get("artifact", ""))
    required = {"data/transactions.csv", "docs/data-schema.md"}
    valid = (
        2 <= len(read_files) <= 3
        and required.issubset(read_files)
        and all(path in ALLOWED_READ_FILES and path in available_files for path in read_files)
        and diff_target == "docs/data-schema.md"
        and artifact == "data-quality-report.md"
    )
    if not valid:
        return dict(DEFAULT_PLAN), "fallback"
    return {
        "read_files": read_files,
        "diff_target": diff_target,
        "artifact": artifact,
        "reason": str(payload.get("reason", "Безопасный план работы с файлами.")),
    }, "proxyapi"


def _plan_file_work(
    goal: str,
    client: ProxyAPIClient,
    available_files: set[str],
) -> tuple[dict, str, LLMResult | None]:
    prompt = (
        f"Цель пользователя: {goal}\n"
        f"Доступные разрешённые файлы: {sorted(available_files & set(ALLOWED_READ_FILES))}\n"
        "Выбери 2–3 файла. Для аудита обязательны data/transactions.csv и docs/data-schema.md. "
        "Разрешённый diff_target: docs/data-schema.md. Разрешённый artifact: data-quality-report.md. "
        "Верни JSON: read_files, diff_target, artifact, reason."
    )
    try:
        payload, llm = client.chat_json(
            [
                {"role": "system", "content": "Ты планировщик безопасного файлового агента. Не выходи за allowlist."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=240,
        )
        plan, mode = _validated_plan(payload, available_files)
        return plan, mode, llm
    except ProxyAPIError:
        return dict(DEFAULT_PLAN), "fallback", None


def _audit_markdown(
    profile: dict,
    issues: list[str],
    llm_summary: str,
    inspected_paths: list[str],
) -> str:
    inspected = [f"- `{path}`" for path in inspected_paths]
    return "\n".join([
        "# Data quality audit",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        "",
        "## Files inspected",
        "",
        *inspected,
        "",
        "## Deterministic checks",
        "",
        f"- Rows: {profile['rows']}",
        f"- Period: {profile['first_date']} — {profile['last_date']}",
        f"- Users: {profile['users']}",
        f"- Statuses: {profile['statuses']}",
        f"- Review flags: {profile['review_rows']}",
        f"- Duplicate flags: {profile['duplicates']}",
        f"- Schema violations: {len(issues)}",
        "",
        "## AI summary",
        "",
        llm_summary,
        "",
        "## Reproducibility",
        "",
        "Run `/demo day34` again; the report is regenerated from a new validated plan.",
    ])


def run_file_goal(
    goal: str = "Проверь данные и подготовь воспроизводимый отчёт",
    *,
    client: ProxyAPIClient | None = None,
    bridge: McpBridge | None = None,
) -> dict:
    owned_bridge = bridge is None
    bridge = bridge or McpBridge(["project"])
    if owned_bridge:
        bridge.start()
    try:
        active_client = client or ProxyAPIClient()
        available = bridge.call("project", "list_files", {"pattern": "**/*", "limit": 200})
        plan, plan_mode, plan_llm = _plan_file_work(goal, active_client, set(available["files"]))
        inspected = [
            bridge.call("project", "read_file", {"path": path, "start": 1, "end": 400})
            for path in plan["read_files"]
        ]
        rows = data.load_transactions()
        profile = data.dataset_profile(rows)
        issues = data.validate_transactions(rows)
        summary_prompt = (
            f"Цель: {goal}\nПрофиль: {profile}\nНарушения схемы: {issues or 'нет'}. "
            "Дубликаты с is_duplicate=true исключаются из финансовых итогов. "
            "Дай 4 коротких проверяемых вывода на русском. Не пересчитывай значения и "
            "не утверждай, что уже исключённый дубликат искажает итог."
        )
        try:
            llm = active_client.chat(
                [
                    {"role": "system", "content": "Ты аудитор качества финансовых данных."},
                    {"role": "user", "content": summary_prompt},
                ],
                max_tokens=320,
            )
            summary = llm.text
        except ProxyAPIError:
            llm = None
            summary = "Данные проходят схему; пограничные операции намеренно помечены для очереди ручной проверки."
        inspected_paths = [item["path"] for item in inspected]
        report = _audit_markdown(profile, issues, summary, inspected_paths)
        written = bridge.call(
            "project",
            "write_generated_file",
            {"path": plan["artifact"], "content": report, "confirm": True},
        )
        inspected_by_path = {item["path"]: item for item in inspected}
        schema_item = inspected_by_path[plan["diff_target"]]
        schema = "\n".join(line[6:] for line in schema_item["text"].splitlines())
        observed = (
            "\n## Observed demo dataset\n\n"
            f"- Rows: {profile['rows']}\n"
            f"- Date range: {profile['first_date']} — {profile['last_date']}\n"
            f"- Statuses: {profile['statuses']}\n"
        )
        preview = "\n".join(difflib.unified_diff(
            schema.splitlines(),
            (schema + observed).splitlines(),
            fromfile="docs/data-schema.md",
            tofile="docs/data-schema.md (proposed)",
            lineterm="",
        ))
        return {
            "goal": goal,
            "plan": plan,
            "plan_mode": plan_mode,
            "plan_llm": plan_llm,
            "inspected": inspected_paths,
            "profile": profile,
            "issues": issues,
            "written": written,
            "summary": summary,
            "diff_preview": preview,
            "llm": llm,
            "mcp_status": bridge.status(),
        }
    finally:
        if owned_bridge:
            bridge.stop()
