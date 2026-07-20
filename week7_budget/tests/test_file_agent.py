from budget_pipeline.file_agent import ALLOWED_READ_FILES, _validated_plan


def test_file_plan_accepts_only_allowlisted_audit_inputs():
    payload = {
        "read_files": ["data/transactions.csv", "docs/data-schema.md", "docs/runbook.md"],
        "diff_target": "docs/data-schema.md",
        "artifact": "data-quality-report.md",
        "reason": "Проверить данные.",
    }
    plan, mode = _validated_plan(payload, set(ALLOWED_READ_FILES))
    assert mode == "proxyapi"
    assert plan["read_files"] == payload["read_files"]


def test_file_plan_rejects_paths_outside_allowlist():
    payload = {
        "read_files": ["data/transactions.csv", "docs/data-schema.md", "../.zshrc"],
        "diff_target": "docs/data-schema.md",
        "artifact": "data-quality-report.md",
    }
    plan, mode = _validated_plan(payload, set(ALLOWED_READ_FILES) | {"../.zshrc"})
    assert mode == "fallback"
    assert "../.zshrc" not in plan["read_files"]
