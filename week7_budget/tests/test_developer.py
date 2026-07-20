from budget_pipeline.developer import _with_verified_sources
from budget_pipeline.retrieval import Document, SearchHit


def test_developer_replaces_unverified_source_list():
    hit = SearchHit(
        1.0,
        Document("docs/data-schema.md:1", "data-schema.md", "text", "docs/data-schema.md"),
    )
    answer = "Фильтр описан в схеме.\n\nИспользованные источники: invented.py"
    verified = _with_verified_sources(answer, [hit])
    assert "invented.py" not in verified
    assert verified.endswith("docs/data-schema.md:1")
