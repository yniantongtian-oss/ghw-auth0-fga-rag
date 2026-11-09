"""Retrieve from the full index, then drop anything FGA does not allow.

The language model (or the offline extractor) is called only after both the
list-objects prefilter and the batch check have run. Denied chunk text is
never copied into the context string.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

import httpx

from app.config import Settings
from app.fga.http import FgaError
from app.rag.index import Chunk
from app.rag.text import content_tokens, tokenize

logger = logging.getLogger("hearth.rag")

_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_HEADING = re.compile(r"^#{1,6}\s+", re.MULTILINE)

OUTAGE_ANSWER = (
    "I couldn't confirm which documents you are allowed to read, "
    "so I am not using the index for this question."
)
DENIED_ANSWER = (
    "I can't answer that from documents you are allowed to read. "
    "Matching files may exist in the index, but your role and department "
    "do not grant view access, so those passages were withheld before an answer was written."
)

_SYSTEM_PROMPT = (
    "You are Hearth, an internal HR assistant. Answer only with facts that appear "
    "in the context. If the context does not contain the answer, say so. Do not "
    "use outside knowledge for compensation, medical, or succession details. "
    "Cite the document title. The context has already been filtered to documents "
    "this user may view; do not speculate about withheld files."
)


@dataclass
class TraceItem:
    doc_id: str
    score: float
    allowed: bool


@dataclass
class Retrieval:
    candidates: list[Chunk]
    allowed_chunks: list[Chunk]
    trace: list[TraceItem]
    batch_failed: bool

    @property
    def llm_context(self) -> str:
        """Context built only from chunks that passed FGA."""
        return build_context(self.allowed_chunks)


@dataclass
class AnswerResult:
    answer: str
    citations: list[dict]
    trace: list[TraceItem]
    withheld_count: int
    llm_used: bool
    backend: str
    llm_context: str = ""
    batch_failed: bool = False
    titles: dict[str, str] = field(default_factory=dict)

    def public_dict(self) -> dict:
        # Denied rows expose the document id and score, never the title or excerpt.
        # quoted is the subset that was actually copied into the answer context.
        quoted = {citation["doc_id"] for citation in self.citations}
        return {
            "answer": self.answer,
            "citations": self.citations,
            "trace": [
                {
                    "doc_id": item.doc_id,
                    "score": round(item.score, 4),
                    "allowed": item.allowed,
                    "quoted": item.allowed and item.doc_id in quoted,
                    "title": self.titles.get(item.doc_id) if item.allowed else None,
                }
                for item in self.trace
            ],
            "withheld_count": self.withheld_count,
            "llm_used": self.llm_used,
            "backend": self.backend,
        }


def build_context(chunks: list[Chunk]) -> str:
    parts = []
    for index, chunk in enumerate(chunks, start=1):
        parts.append(f"[{index}] {chunk.title} ({chunk.doc_id})\n{chunk.text}")
    return "\n\n".join(parts)


def fga_user(user_id: str) -> str:
    from app.identity import normalize_user_id

    normalized = normalize_user_id(user_id)
    if not normalized:
        raise ValueError("invalid user id")
    return f"user:{normalized}"


class Engine:
    def __init__(self, index, fga, settings: Settings, documents, users) -> None:
        self.index = index
        self.fga = fga
        self.settings = settings
        self.documents = documents
        self.users = users
        self.users_by_id = {user.id: user for user in users}
        self.docs_by_id = {document.id: document for document in documents}

    def retrieve(self, user_id: str, question: str, *, candidate_k: int = 40, context_k: int = 4) -> Retrieval:
        user = fga_user(user_id)
        ranked = self.index.search(question, candidate_k)
        best_score: dict[str, float] = {}
        chunks_by_doc: dict[str, list[Chunk]] = {}
        doc_order: list[str] = []
        for chunk in ranked:
            chunks_by_doc.setdefault(chunk.doc_id, []).append(chunk)
            previous = best_score.get(chunk.doc_id)
            if previous is None or chunk.score > previous:
                best_score[chunk.doc_id] = chunk.score
            if chunk.doc_id not in doc_order:
                doc_order.append(chunk.doc_id)

        objects = [f"document:{doc_id}" for doc_id in doc_order]
        listed: set[str] | None
        try:
            listed = set(self.fga.list_objects(user, "viewer", "document"))
        except FgaError:
            logger.warning("list_objects failed; batch check remains mandatory")
            listed = None

        batch_failed = False
        try:
            decisions = self.fga.batch_check(user, "viewer", objects) if objects else {}
        except FgaError:
            logger.warning("batch_check failed; withholding every candidate")
            batch_failed = True
            decisions = {obj: False for obj in objects}

        trace: list[TraceItem] = []
        allowed_chunks: list[Chunk] = []
        for doc_id in doc_order:
            obj = f"document:{doc_id}"
            allowed = bool(decisions.get(obj, False))
            if listed is not None:
                allowed = allowed and obj in listed
            trace.append(TraceItem(doc_id=doc_id, score=best_score[doc_id], allowed=allowed))
            if allowed:
                allowed_chunks.extend(chunks_by_doc[doc_id])
        allowed_chunks.sort(key=lambda chunk: chunk.score, reverse=True)
        allowed_chunks = _relevant_chunks(question, ranked, allowed_chunks)[:context_k]
        withheld = [item.doc_id for item in trace if not item.allowed]
        if withheld:
            logger.info("withheld user=%s docs=%s", user_id, ",".join(withheld))
        return Retrieval(
            candidates=ranked,
            allowed_chunks=allowed_chunks,
            trace=trace,
            batch_failed=batch_failed,
        )

    def visible_documents(self, user_id: str) -> list[dict[str, str]]:
        user = fga_user(user_id)
        try:
            objects = self.fga.list_objects(user, "viewer", "document")
        except FgaError:
            return []
        visible = []
        for obj in objects:
            doc_id = obj.split(":", 1)[1] if obj.startswith("document:") else obj
            document = self.docs_by_id.get(doc_id)
            if document is None:
                continue
            visible.append({"id": document.id, "title": document.title})
        visible.sort(key=lambda item: item["title"])
        return visible

    def answer(self, user_id: str, question: str, *, complete=None) -> AnswerResult:
        retrieval = self.retrieve(user_id, question)
        backend = self.settings.fga_backend_label
        withheld = sum(1 for item in retrieval.trace if not item.allowed)
        if retrieval.batch_failed or not retrieval.allowed_chunks:
            text = OUTAGE_ANSWER if retrieval.batch_failed else DENIED_ANSWER
            return AnswerResult(
                answer=text,
                citations=[],
                trace=retrieval.trace,
                withheld_count=withheld,
                llm_used=False,
                backend=backend,
                llm_context="",
                batch_failed=retrieval.batch_failed,
                titles={},
            )

        context = retrieval.llm_context
        # Tripwire: denied candidate text must not be copied into the prompt.
        allowed_text = {chunk.text for chunk in retrieval.allowed_chunks}
        for candidate in retrieval.candidates:
            if candidate.text in allowed_text:
                continue
            if candidate.text and candidate.text in context:
                raise RuntimeError("refusing to send withheld document text")

        if complete is not None:
            text = complete(question, context)
            used = False
        else:
            text, used = generate_answer(question, retrieval.allowed_chunks, context, self.settings)
        citations = [
            {
                "doc_id": chunk.doc_id,
                "title": chunk.title,
                "excerpt": _excerpt(chunk.text),
                "score": round(chunk.score, 4),
            }
            for chunk in retrieval.allowed_chunks
        ]
        allowed_ids = {item.doc_id for item in retrieval.trace if item.allowed}
        return AnswerResult(
            answer=text,
            citations=citations,
            trace=retrieval.trace,
            withheld_count=withheld,
            llm_used=used,
            backend=backend,
            llm_context=context,
            batch_failed=False,
            titles={
                doc_id: self.docs_by_id[doc_id].title
                for doc_id in allowed_ids
                if doc_id in self.docs_by_id
            },
        )


def generate_answer(
    question: str, chunks: list[Chunk], context: str, settings: Settings
) -> tuple[str, bool]:
    if settings.llm_enabled:
        try:
            return _complete_with_llm(question, context, settings), True
        except Exception:
            logger.warning("optional LLM failed; using the offline extractor")
    return extractive_answer(question, chunks), False


def extractive_answer(question: str, chunks: list[Chunk]) -> str:
    query_terms = content_tokens(question)
    lines = ["Here is what the documents you can access say.", ""]
    for chunk in chunks:
        chosen = _best_sentences(chunk.text, query_terms)
        lines.append(f"From {chunk.title}:")
        for sentence in chosen:
            lines.append(sentence)
        lines.append("")
    return "\n".join(lines).strip()


def _relevant_chunks(question: str, ranked: list[Chunk], allowed: list[Chunk]) -> list[Chunk]:
    """Drop allowed hits that only share a passing word with the question.

    Authorization already ran. This only decides which allowed text is worth
    putting in the prompt, so a salary question does not fall through to an
    unrelated sentence the user happens to be allowed to read.
    """
    if not allowed or not ranked:
        return []
    best = ranked[0].score or 1.0
    query_terms = set(content_tokens(question))
    kept = []
    for chunk in allowed:
        overlap = len(query_terms & set(content_tokens(f"{chunk.title}\n{chunk.text}")))
        if overlap >= 2 and chunk.score >= 0.45 * best:
            kept.append(chunk)
    return kept


def _plain(text: str) -> str:
    lines = []
    for line in text.splitlines():
        stripped = _HEADING.sub("", line).strip()
        if not stripped:
            continue
        if line.lstrip().startswith("#") and stripped[-1] not in ".!?":
            stripped += "."
        lines.append(stripped)
    return " ".join(lines)


def _best_sentences(text: str, query_terms: list[str]) -> list[str]:
    flat = _plain(text)
    sentences = [part.strip() for part in _SENTENCE.split(flat) if part.strip()]
    ranked: list[tuple[int, str]] = []
    for sentence in sentences:
        terms = set(tokenize(sentence))
        overlap = sum(1 for term in query_terms if term in terms)
        if overlap:
            ranked.append((overlap, sentence))
    ranked.sort(key=lambda item: item[0], reverse=True)
    substantial = [sentence for _score, sentence in ranked if len(sentence.split()) >= 6]
    if substantial:
        return substantial[:2]
    if ranked:
        return [sentence for _score, sentence in ranked[:2]]
    return [flat[:420]]


def _excerpt(text: str, limit: int = 360) -> str:
    flat = _plain(text)
    if len(flat) <= limit:
        return flat
    return flat[: limit - 1].rstrip() + "…"


def _complete_with_llm(question: str, context: str, settings: Settings) -> str:
    payload = {
        "model": settings.llm_model,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Context:\n{context}\n\nQuestion: {question}",
            },
        ],
    }
    with httpx.Client(timeout=30.0) as client:
        response = client.post(
            settings.llm_base_url.rstrip("/") + "/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.llm_api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        response.raise_for_status()
        body = response.json()
    return str(body["choices"][0]["message"]["content"]).strip()
