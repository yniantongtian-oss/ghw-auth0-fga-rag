"""TF-IDF over document chunks. No model download and no API key."""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass

from app.corpus import Document
from app.rag.text import content_tokens

_PARAGRAPHS = re.compile(r"\n\s*\n")


@dataclass(frozen=True)
class Chunk:
    doc_id: str
    title: str
    text: str
    score: float = 0.0


def chunk_documents(documents: list[Document], max_chars: int = 800) -> list[Chunk]:
    chunks: list[Chunk] = []
    for document in documents:
        paragraphs = [part.strip() for part in _PARAGRAPHS.split(document.body) if part.strip()]
        buffers: list[str] = []
        current = ""
        for paragraph in paragraphs:
            if current and len(current) + len(paragraph) + 2 > max_chars:
                buffers.append(current)
                current = paragraph
            elif current:
                current = current + "\n\n" + paragraph
            else:
                current = paragraph
        if current:
            buffers.append(current)
        if not buffers and document.body.strip():
            buffers.append(document.body.strip())
        for text in buffers:
            chunks.append(Chunk(doc_id=document.id, title=document.title, text=text))
    return chunks


class TfidfIndex:
    """Cosine similarity over smoothed TF-IDF vectors."""

    def __init__(self, chunks: list[Chunk]) -> None:
        self.chunks = list(chunks)
        tokenized = [content_tokens(f"{chunk.title}\n{chunk.text}") for chunk in self.chunks]
        self._df: dict[str, int] = defaultdict(int)
        for tokens in tokenized:
            for token in set(tokens):
                self._df[token] += 1
        self._n = max(1, len(self.chunks))
        self._vectors = [self._vector(tokens) for tokens in tokenized]
        self._norms = [_norm(vector) for vector in self._vectors]

    def search(self, query: str, k: int) -> list[Chunk]:
        query_vector = self._vector(content_tokens(query))
        query_norm = _norm(query_vector)
        if query_norm == 0 or k <= 0:
            return []
        scored: list[tuple[float, Chunk]] = []
        for chunk, vector, norm in zip(self.chunks, self._vectors, self._norms):
            if norm == 0:
                continue
            dot = sum(weight * vector[term] for term, weight in query_vector.items() if term in vector)
            score = dot / (query_norm * norm)
            if score > 0:
                scored.append((score, chunk))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [
            Chunk(doc_id=chunk.doc_id, title=chunk.title, text=chunk.text, score=score)
            for score, chunk in scored[:k]
        ]

    def _vector(self, tokens: list[str]) -> dict[str, float]:
        counts = Counter(tokens)
        vector: dict[str, float] = {}
        for term, count in counts.items():
            if term not in self._df:
                continue
            tf = 1.0 + math.log(count)
            idf = math.log((1.0 + self._n) / (1.0 + self._df[term])) + 1.0
            vector[term] = tf * idf
        return vector


def _norm(vector: dict[str, float]) -> float:
    return math.sqrt(sum(weight * weight for weight in vector.values()))
