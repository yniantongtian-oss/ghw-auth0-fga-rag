"""Wire the corpus, the authorization model, and the retriever."""

from __future__ import annotations

from app.config import Settings
from app.corpus import load_documents, load_model_text, load_tuples, load_users
from app.fga.client import build_fga
from app.fga.dsl import parse_model
from app.rag.engine import Engine
from app.rag.index import TfidfIndex, chunk_documents


def build_engine(settings: Settings | None = None) -> Engine:
    settings = settings if settings is not None else Settings()
    documents = load_documents()
    users = load_users()
    tuples = load_tuples()
    model = parse_model(load_model_text())
    inventory = {"document": [f"document:{document.id}" for document in documents]}
    fga = build_fga(settings, model, tuples, inventory)
    index = TfidfIndex(chunk_documents(documents))
    return Engine(index=index, fga=fga, settings=settings, documents=documents, users=users)
