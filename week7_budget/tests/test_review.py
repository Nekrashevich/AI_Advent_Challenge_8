from budget_pipeline import review


class OfflineClient:
    def chat_json(self, messages, **kwargs):
        raise review.ProxyAPIError("offline")


def test_deterministic_review_finds_demo_problems():
    findings = review.deterministic_checks(review.DEMO_DIFF)
    titles = {finding.title for finding in findings}
    assert "Возможный секрет добавлен в код" in titles
    assert "Выполнение недоверенного выражения" in titles
    assert "Голый except скрывает ошибки" in titles


def test_review_falls_back_and_renders_required_sections():
    files = ["week7_budget/budget_pipeline/broken_demo.py"]
    result = review.review_diff(review.DEMO_DIFF, files, client=OfflineClient())
    markdown = review.render_review(result, files)
    assert result["mode"] == "deterministic-fallback"
    assert "### Потенциальные баги" in markdown
    assert "### Архитектурные проблемы" in markdown
    assert "### Рекомендации" in markdown
    assert review.REVIEW_MARKER in markdown

