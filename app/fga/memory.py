"""In-memory OpenFGA check, batch check, and list objects.

Evaluation follows the rewrite tree produced from model.fga: direct tuples
(including usersets and wildcards), computed usersets, tuple-to-userset, and
union. It is the offline backend and the reference for the sample policy.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.fga.dsl import (
    ComputedUserset,
    Model,
    ModelError,
    RelationDef,
    This,
    TupleToUserset,
    Union,
)


@dataclass(frozen=True)
class Tuple:
    user: str
    relation: str
    object: str

    def as_dict(self) -> dict[str, str]:
        return {"user": self.user, "relation": self.relation, "object": self.object}


def split_object(value: str) -> tuple[str, str]:
    if ":" not in value or value.startswith(":") or value.endswith(":"):
        raise ModelError(f"invalid object id {value}")
    type_name, object_id = value.split(":", 1)
    if "#" in type_name or "#" in object_id or not type_name or not object_id:
        raise ModelError(f"invalid object id {value}")
    return type_name, object_id


def validate_tuples(model: Model, tuples: list[Tuple]) -> None:
    for item in tuples:
        object_type, _object_id = split_object(item.object)
        if object_type not in model.types:
            raise ModelError(f"unknown object type in {item.object}")
        relation = model.types[object_type].relations.get(item.relation)
        if relation is None:
            raise ModelError(f"{item.object} has no relation {item.relation}")
        if not relation.assigns_directly:
            raise ModelError(
                f"{item.relation} on {object_type} is computed and cannot be written"
            )
        if not _user_matches(item.user, relation):
            raise ModelError(
                f"user {item.user} is not assignable to {object_type}#{item.relation}"
            )


def _user_matches(user: str, relation: RelationDef) -> bool:
    wildcard = False
    userset_relation: str | None = None
    if "#" in user:
        left, userset_relation = user.split("#", 1)
        if not userset_relation:
            return False
        type_name, object_id = split_object(left)
    elif user.endswith(":*"):
        type_name = user[:-2]
        object_id = "*"
        wildcard = True
        if not type_name:
            return False
    else:
        type_name, object_id = split_object(user)
    if not object_id:
        return False
    for allowed in relation.direct_types:
        if allowed.type_name != type_name:
            continue
        if wildcard:
            if allowed.wildcard and allowed.relation is None:
                return True
            continue
        if userset_relation is not None:
            if allowed.relation == userset_relation:
                return True
            continue
        if allowed.relation is None and not allowed.wildcard:
            return True
    return False


class MemoryFga:
    """Evaluate checks locally. Callers must already have validated tuples."""

    def __init__(
        self,
        model: Model,
        tuples: list[Tuple],
        inventory: dict[str, list[str]] | None = None,
    ) -> None:
        self.model = model
        self.tuples = list(tuples)
        self.inventory = inventory or {}

    def check(self, user: str, relation: str, obj: str) -> bool:
        return self._check(user, relation, obj, set())

    def batch_check(self, user: str, relation: str, objects: list[str]) -> dict[str, bool]:
        return {obj: self.check(user, relation, obj) for obj in objects}

    def list_objects(self, user: str, relation: str, object_type: str) -> list[str]:
        prefix = object_type + ":"
        found: set[str] = set(self.inventory.get(object_type, []))
        for item in self.tuples:
            if item.object.startswith(prefix):
                found.add(item.object)
        allowed = [obj for obj in sorted(found) if self.check(user, relation, obj)]
        return allowed

    def _check(self, user: str, relation: str, obj: str, seen: set[tuple[str, str, str]]) -> bool:
        key = (user, relation, obj)
        if key in seen:
            return False
        seen.add(key)
        object_type, _object_id = split_object(obj)
        type_def = self.model.types.get(object_type)
        if type_def is None or relation not in type_def.relations:
            return False
        return self._eval(type_def.relations[relation].rewrite, user, relation, obj, seen)

    def _eval(self, rewrite, user: str, relation: str, obj: str, seen: set) -> bool:
        if isinstance(rewrite, This):
            return self._direct(user, relation, obj, seen)
        if isinstance(rewrite, ComputedUserset):
            return self._check(user, rewrite.relation, obj, seen)
        if isinstance(rewrite, TupleToUserset):
            for item in self.tuples:
                if item.object == obj and item.relation == rewrite.tupleset:
                    if self._check(user, rewrite.computed, item.user, seen):
                        return True
            return False
        if isinstance(rewrite, Union):
            return any(self._eval(child, user, relation, obj, seen) for child in rewrite.children)
        return False

    def _direct(self, user: str, relation: str, obj: str, seen: set) -> bool:
        for item in self.tuples:
            if item.relation != relation or item.object != obj:
                continue
            if item.user == user:
                return True
            if item.user.endswith(":*") and _wildcard_matches(item.user, user):
                return True
            if "#" in item.user:
                target, userset_relation = item.user.split("#", 1)
                if self._check(user, userset_relation, target, seen):
                    return True
        return False


def _wildcard_matches(pattern: str, user: str) -> bool:
    type_name = pattern[:-2]
    return user.startswith(type_name + ":") and "#" not in user and not user.endswith(":*")
