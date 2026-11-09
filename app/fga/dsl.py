"""Parse a small slice of the OpenFGA DSL and emit API JSON.

The slice covers this project's model: direct types (including usersets and
wildcards), computed usersets, tuple-to-userset, and top-level unions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


class ModelError(ValueError):
    """The authorization model text is not valid for this parser."""


@dataclass(frozen=True)
class DirectType:
    type_name: str
    relation: str | None = None
    wildcard: bool = False


@dataclass(frozen=True)
class This:
    pass


@dataclass(frozen=True)
class ComputedUserset:
    relation: str


@dataclass(frozen=True)
class TupleToUserset:
    tupleset: str
    computed: str


@dataclass(frozen=True)
class Union:
    children: list


Rewrite = This | ComputedUserset | TupleToUserset | Union


@dataclass
class RelationDef:
    name: str
    rewrite: Rewrite
    direct_types: list[DirectType] = field(default_factory=list)

    @property
    def assigns_directly(self) -> bool:
        return _contains_this(self.rewrite)


@dataclass
class TypeDef:
    name: str
    relations: dict[str, RelationDef]


@dataclass
class Model:
    schema_version: str
    types: dict[str, TypeDef]

    def relation(self, type_name: str, name: str) -> RelationDef:
        try:
            return self.types[type_name].relations[name]
        except KeyError as exc:
            raise ModelError(f"{type_name} has no relation {name}") from exc


_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _contains_this(rewrite: Rewrite) -> bool:
    if isinstance(rewrite, This):
        return True
    if isinstance(rewrite, Union):
        return any(_contains_this(child) for child in rewrite.children)
    return False


def strip_comment(line: str) -> str:
    """Drop a comment whose # is at the start or after whitespace.

    `department#member` stays intact because that # is not a comment.
    """
    out: list[str] = []
    for index, char in enumerate(line):
        if char == "#" and (index == 0 or line[index - 1].isspace()):
            break
        out.append(char)
    return "".join(out).rstrip()


def parse_direct_type(token: str) -> DirectType:
    if "#" in token:
        type_name, relation = token.split("#", 1)
        if not _IDENT.fullmatch(type_name) or not _IDENT.fullmatch(relation):
            raise ModelError(f"invalid userset type {token}")
        return DirectType(type_name=type_name, relation=relation)
    if token.endswith(":*"):
        type_name = token[:-2]
        if not _IDENT.fullmatch(type_name):
            raise ModelError(f"invalid wildcard type {token}")
        return DirectType(type_name=type_name, wildcard=True)
    if not _IDENT.fullmatch(token):
        raise ModelError(f"invalid type {token}")
    return DirectType(type_name=token)


def parse_rewrite(expr: str) -> tuple[Rewrite, list[DirectType]]:
    parts = [part.strip() for part in expr.split(" or ") if part.strip()]
    if not parts:
        raise ModelError("empty relation definition")
    children: list[Rewrite] = []
    direct: list[DirectType] = []
    for part in parts:
        if part.startswith("["):
            if not part.endswith("]"):
                raise ModelError(f"unclosed type restriction: {part}")
            inner = part[1:-1].strip()
            if not inner:
                raise ModelError("empty type restriction")
            for token in inner.split(","):
                direct.append(parse_direct_type(token.strip()))
            children.append(This())
            continue
        if " from " in part:
            computed, tupleset = [piece.strip() for piece in part.split(" from ", 1)]
            if not _IDENT.fullmatch(computed) or not _IDENT.fullmatch(tupleset):
                raise ModelError(f"invalid tupleset rewrite: {part}")
            children.append(TupleToUserset(tupleset=tupleset, computed=computed))
            continue
        if not _IDENT.fullmatch(part):
            raise ModelError(f"invalid rewrite term: {part}")
        children.append(ComputedUserset(relation=part))
    rewrite: Rewrite = children[0] if len(children) == 1 else Union(children=children)
    if any(isinstance(child, This) for child in children) and not direct:
        raise ModelError("direct assignment is missing type restrictions")
    return rewrite, direct


def parse_model(text: str) -> Model:
    lines = [strip_comment(raw).strip() for raw in text.splitlines()]
    lines = [line for line in lines if line]
    if not lines or lines[0] != "model":
        raise ModelError("model file must start with 'model'")
    if len(lines) < 2 or not lines[1].startswith("schema "):
        raise ModelError("model file must declare a schema")
    schema_version = lines[1].split(None, 1)[1].strip()
    if schema_version != "1.1":
        raise ModelError(f"unsupported schema {schema_version}")

    types: dict[str, TypeDef] = {}
    index = 2
    while index < len(lines):
        line = lines[index]
        if not line.startswith("type "):
            raise ModelError(f"expected type definition, found: {line}")
        type_name = line.split(None, 1)[1].strip()
        if not _IDENT.fullmatch(type_name):
            raise ModelError(f"invalid type name {type_name}")
        if type_name in types:
            raise ModelError(f"duplicate type {type_name}")
        index += 1
        relations: dict[str, RelationDef] = {}
        if index < len(lines) and lines[index] == "relations":
            index += 1
            while index < len(lines) and lines[index].startswith("define "):
                define = lines[index][len("define ") :]
                if ":" not in define:
                    raise ModelError(f"invalid define: {lines[index]}")
                name, expr = define.split(":", 1)
                name = name.strip()
                if not _IDENT.fullmatch(name):
                    raise ModelError(f"invalid relation name {name}")
                rewrite, direct = parse_rewrite(expr.strip())
                relations[name] = RelationDef(name=name, rewrite=rewrite, direct_types=direct)
                index += 1
        types[type_name] = TypeDef(name=type_name, relations=relations)
    if "user" not in types:
        raise ModelError("model must define type user")
    return Model(schema_version=schema_version, types=types)


def _rewrite_json(rewrite: Rewrite) -> dict:
    if isinstance(rewrite, This):
        return {"this": {}}
    if isinstance(rewrite, ComputedUserset):
        return {"computedUserset": {"relation": rewrite.relation}}
    if isinstance(rewrite, TupleToUserset):
        return {
            "tupleToUserset": {
                "tupleset": {"relation": rewrite.tupleset},
                "computedUserset": {"relation": rewrite.computed},
            }
        }
    if isinstance(rewrite, Union):
        return {"union": {"child": [_rewrite_json(child) for child in rewrite.children]}}
    raise ModelError(f"unknown rewrite {rewrite!r}")


def _direct_json(direct: DirectType) -> dict:
    if direct.wildcard:
        return {"type": direct.type_name, "wildcard": {}}
    if direct.relation:
        return {"type": direct.type_name, "relation": direct.relation}
    return {"type": direct.type_name}


def model_to_json(model: Model) -> dict:
    """Authorization model body accepted by the OpenFGA write API."""
    type_definitions = []
    for type_def in model.types.values():
        entry: dict = {"type": type_def.name}
        if type_def.relations:
            entry["relations"] = {
                name: _rewrite_json(rel.rewrite) for name, rel in type_def.relations.items()
            }
            entry["metadata"] = {
                "relations": {
                    name: {
                        "directly_related_user_types": [
                            _direct_json(item) for item in rel.direct_types
                        ]
                    }
                    for name, rel in type_def.relations.items()
                }
            }
        type_definitions.append(entry)
    return {"schema_version": model.schema_version, "type_definitions": type_definitions}
