import re

FIXED_SIZE = 1600
FIXED_OVERLAP = 200
STRUCT_MAX = 2400
STRUCT_MIN = 300

SENTENCE_END = re.compile(r"(?<=[.!?…])\s+|\n+")


def _sentences(text):
    parts = [p.strip() for p in SENTENCE_END.split(text)]
    return [p for p in parts if p]


def _pack(sentences, limit, overlap):
    pieces = []
    current = []
    length = 0
    for sentence in sentences:
        if length + len(sentence) > limit and current:
            pieces.append(" ".join(current))
            while current and length > overlap:
                removed = current.pop(0)
                length -= len(removed) + 1
        current.append(sentence)
        length += len(sentence) + 1
    if current:
        pieces.append(" ".join(current))
    return pieces


def _make_chunk(strategy, document, section, order, text):
    return {
        "chunk_id": f"{strategy}:{document['file']}:{order}",
        "strategy": strategy,
        "source": document["file"],
        "group": document["group"],
        "title": document["title"],
        "section": section,
        "n_chars": len(text),
        "text": text,
    }


def fixed_chunks(document):
    plain = re.sub(r"^#{1,6}\s+", "", document["text"], flags=re.MULTILINE)
    pieces = _pack(_sentences(plain), FIXED_SIZE, FIXED_OVERLAP)
    return [
        _make_chunk("fixed", document, f"фрагмент {order}", order, piece)
        for order, piece in enumerate(pieces, 1)
    ]


def _sections(text):
    heading = re.compile(r"^(#{1,6})\s+(.+)$", flags=re.MULTILINE)
    matches = list(heading.finditer(text))
    if not matches:
        return [("без заголовка", text.strip())]
    sections = []
    trail = {}
    preamble = text[: matches[0].start()].strip()
    if preamble:
        sections.append(("преамбула", preamble))
    for position, match in enumerate(matches):
        level = len(match.group(1))
        trail = {k: v for k, v in trail.items() if k < level}
        trail[level] = match.group(2).strip()
        path = " > ".join(trail[k] for k in sorted(trail))
        end = matches[position + 1].start() if position + 1 < len(matches) else len(text)
        body = text[match.end(): end].strip()
        if body:
            sections.append((path, body))
    return sections


def structural_chunks(document):
    chunks = []
    order = 0
    pending_path = None
    pending_body = ""
    for path, body in _sections(document["text"]):
        if pending_body:
            path = pending_path
            body = pending_body + "\n\n" + body
            pending_body = ""
        if len(body) < STRUCT_MIN:
            pending_path = path
            pending_body = body
            continue
        for piece in _pack(_sentences(body), STRUCT_MAX, FIXED_OVERLAP):
            order += 1
            chunks.append(_make_chunk("structural", document, path, order, piece))
    if pending_body:
        order += 1
        chunks.append(_make_chunk("structural", document, pending_path, order, pending_body))
    return chunks


STRATEGIES = {"fixed": fixed_chunks, "structural": structural_chunks}


def chunk_corpus(documents, strategy):
    chunks = []
    for document in documents:
        chunks.extend(STRATEGIES[strategy](document))
    return chunks


def stats(chunks):
    sizes = [c["n_chars"] for c in chunks]
    broken = sum(1 for c in chunks if not re.search(r"[.!?…:)\]»]$", c["text"].strip()))
    return {
        "count": len(chunks),
        "avg": sum(sizes) // max(len(sizes), 1),
        "min": min(sizes, default=0),
        "max": max(sizes, default=0),
        "broken_end": broken,
    }
