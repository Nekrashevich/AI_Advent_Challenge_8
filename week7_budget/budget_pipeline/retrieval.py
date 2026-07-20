from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from budget_pipeline import data
from budget_pipeline.config import DOCS_DIR, ROOT, TRANSACTIONS_CSV


TOKEN_RE = re.compile(r"[a-zа-яё0-9]+", re.IGNORECASE)


def tokenize(text: str) -> list[str]:
    normalized = text.lower().replace("_", " ").replace("-", " ")
    words = TOKEN_RE.findall(normalized)
    return words + [f"{a}:{b}" for a, b in zip(words, words[1:])]


@dataclass(frozen=True)
class Document:
    id: str
    title: str
    text: str
    source: str
    kind: str = "doc"


@dataclass(frozen=True)
class SearchHit:
    score: float
    document: Document


class BM25Index:
    def __init__(self, documents: list[Document], k1: float = 1.5, b: float = 0.75):
        self.documents = documents
        self.k1 = k1
        self.b = b
        self.tokens = [tokenize(doc.title + "\n" + doc.text) for doc in documents]
        self.lengths = [len(tokens) for tokens in self.tokens]
        self.avg_length = sum(self.lengths) / max(len(self.lengths), 1)
        self.term_counts = [Counter(tokens) for tokens in self.tokens]
        self.document_frequency = Counter()
        for tokens in self.tokens:
            self.document_frequency.update(set(tokens))

    def search(self, query: str, top_k: int = 6, kinds: set[str] | None = None) -> list[SearchHit]:
        query_tokens = Counter(tokenize(query))
        scored: list[SearchHit] = []
        total = len(self.documents)
        for index, document in enumerate(self.documents):
            if kinds and document.kind not in kinds:
                continue
            score = 0.0
            for term, query_weight in query_tokens.items():
                frequency = self.term_counts[index].get(term, 0)
                if not frequency:
                    continue
                df = self.document_frequency[term]
                idf = math.log(1 + (total - df + 0.5) / (df + 0.5))
                denominator = frequency + self.k1 * (
                    1 - self.b + self.b * self.lengths[index] / max(self.avg_length, 1)
                )
                score += query_weight * idf * frequency * (self.k1 + 1) / denominator
            if score > 0:
                scored.append(SearchHit(round(score, 6), document))
        return sorted(scored, key=lambda hit: (-hit.score, hit.document.id))[:top_k]


def _chunks(path: Path, text: str, kind: str, max_chars: int = 2400) -> list[Document]:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    documents: list[Document] = []
    current: list[str] = []
    size = 0
    chunk_number = 1
    for paragraph in paragraphs:
        if current and size + len(paragraph) > max_chars:
            body = "\n\n".join(current)
            documents.append(Document(f"{path}:{chunk_number}", path.name, body, str(path), kind))
            current, size, chunk_number = [], 0, chunk_number + 1
        current.append(paragraph)
        size += len(paragraph)
    if current:
        documents.append(Document(f"{path}:{chunk_number}", path.name, "\n\n".join(current), str(path), kind))
    return documents


def project_documents(include_code: bool = False) -> list[Document]:
    # The recording script contains the exact demo questions and expected answers.
    # Indexing it would leak the answer into retrieval and crowd out product docs.
    docs = [path for path in sorted(DOCS_DIR.glob("*.md")) if path.name != "demo-script.md"]
    paths = [ROOT / "README.md", *docs]
    if include_code:
        paths.extend(sorted((ROOT / "budget_pipeline").glob("*.py")))
    documents: list[Document] = []
    for path in paths:
        if path.exists():
            kind = "code" if path.suffix == ".py" else "doc"
            documents.extend(_chunks(path.relative_to(ROOT), path.read_text(encoding="utf-8"), kind))
    return documents


def transaction_documents(rows: list[data.Transaction] | None = None) -> list[Document]:
    rows = rows or data.load_transactions(TRANSACTIONS_CSV)
    documents: list[Document] = []
    for month, summary in data.monthly_summary(rows, "U-1001").items():
        categories = "; ".join(
            f"{category}: {data.money(amount)}"
            for category, amount in sorted(summary["categories"].items(), key=lambda item: item[1], reverse=True)
        )
        documents.append(Document(
            id=f"transactions:{month}",
            title=f"Финансовая сводка {month}",
            text=(
                f"Расходы {data.money(summary['spend'])}; доходы {data.money(summary['income'])}; "
                f"остаток {data.money(summary['net'])}. Категории: {categories}."
            ),
            source="data/transactions.csv",
            kind="data",
        ))
    for row in data.review_queue(rows, "U-1001"):
        documents.append(Document(
            id=f"transaction:{row.transaction_id}",
            title=f"Операция на проверке {row.transaction_id}",
            text=(
                f"Дата {row.event_date}; тип {row.transaction_type}; статус {row.status}; "
                f"категория {row.category}; продавец {row.merchant or 'не указан'}; "
                f"сумма {row.amount_rub}; валюта {row.currency}; ошибка {row.error_code or 'нет'}; "
                f"связанная операция {row.related_transaction_id or 'нет'}."
            ),
            source="data/transactions.csv",
            kind="data",
        ))
    return documents


def format_context(hits: list[SearchHit], max_chars: int = 12000) -> str:
    blocks: list[str] = []
    size = 0
    for hit in hits:
        block = f"[{hit.document.id} | BM25 {hit.score:.3f}]\n{hit.document.text}"
        if blocks and size + len(block) > max_chars:
            break
        blocks.append(block)
        size += len(block)
    return "\n\n".join(blocks)
