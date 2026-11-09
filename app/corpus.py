"""Load the sample HR corpus, employee directory, and relationship tuples."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from app.config import ROOT
from app.fga.memory import Tuple

DOCS_DIR = ROOT / "data" / "docs"
USERS_PATH = ROOT / "data" / "users.json"
TUPLES_PATH = ROOT / "data" / "tuples.json"
MODEL_PATH = ROOT / "model.fga"

_HEADING = re.compile(r"^#\s+(.+)$", re.MULTILINE)


@dataclass(frozen=True)
class Document:
    id: str
    title: str
    body: str


@dataclass(frozen=True)
class Employee:
    id: str
    name: str
    title: str
    department: str
    role: str

    def as_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "name": self.name,
            "title": self.title,
            "department": self.department,
            "role": self.role,
        }


def load_documents(directory: Path | None = None) -> list[Document]:
    folder = directory or DOCS_DIR
    documents: list[Document] = []
    for path in sorted(folder.glob("*.md")):
        text = path.read_text(encoding="utf-8").strip()
        match = _HEADING.search(text)
        title = match.group(1).strip() if match else path.stem.replace("_", " ").title()
        body = text
        if match and match.start() == 0:
            body = text[match.end() :].strip()
        documents.append(Document(id=path.stem, title=title, body=body))
    if len(documents) < 8:
        raise RuntimeError(f"expected at least 8 HR documents, found {len(documents)}")
    return documents


def load_users(path: Path | None = None) -> list[Employee]:
    payload = json.loads((path or USERS_PATH).read_text(encoding="utf-8"))
    return [
        Employee(
            id=item["id"],
            name=item["name"],
            title=item["title"],
            department=item["department"],
            role=item["role"],
        )
        for item in payload
    ]


def load_tuples(path: Path | None = None) -> list[Tuple]:
    payload = json.loads((path or TUPLES_PATH).read_text(encoding="utf-8"))
    return [Tuple(user=item["user"], relation=item["relation"], object=item["object"]) for item in payload]


def load_model_text(path: Path | None = None) -> str:
    return (path or MODEL_PATH).read_text(encoding="utf-8")
