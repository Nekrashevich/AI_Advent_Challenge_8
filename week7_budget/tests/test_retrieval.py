from budget_pipeline.retrieval import BM25Index, project_documents, tokenize


def test_tokenizer_supports_russian_and_identifiers():
    tokens = tokenize("pending_refund и повторный импорт")
    assert "pending" in tokens
    assert "refund" in tokens
    assert "повторный" in tokens


def test_bm25_finds_duplicate_rule():
    hits = BM25Index(project_documents()).search("повторный импорт duplicate external_id", top_k=3)
    assert hits
    assert any("faq.md" in hit.document.id for hit in hits)


def test_recording_script_is_not_indexed():
    documents = project_documents(include_code=True)
    assert all(document.source != "docs/demo-script.md" for document in documents)
