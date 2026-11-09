import json

from app.corpus import load_model_text, load_tuples
from app.fga.dsl import model_to_json, parse_model
from app.fga.memory import MemoryFga, Tuple, validate_tuples


def test_model_has_the_challenge_types():
    model = parse_model(load_model_text())
    assert set(model.types) == {"user", "department", "document"}
    viewer = model.relation("document", "viewer")
    names = {item.type_name for item in viewer.direct_types}
    assert "user" in names
    assert "department" in names
    blob = json.dumps(model_to_json(model))
    assert "tupleToUserset" in blob
    assert '"relation": "owner"' in blob or '"relation":"owner"' in blob
    assert "manager_department" in blob
    assert "member" in blob


def test_sample_tuples_match_the_model():
    model = parse_model(load_model_text())
    tuples = load_tuples()
    validate_tuples(model, tuples)
    users = {(item.user, item.relation, item.object) for item in tuples}
    assert ("user:alice", "manager", "department:hr") in users
    assert ("user:bob", "employee", "department:engineering") in users
    assert ("department:hr", "manager_department", "document:salary_bands_2026") in users


def test_direct_share_and_wildcard_are_evaluated():
    model = parse_model(load_model_text())
    base = load_tuples()
    shared = list(base) + [Tuple("user:bob", "viewer", "document:hr_recruiting_playbook")]
    fga = MemoryFga(model, shared, {"document": ["document:hr_recruiting_playbook"]})
    assert fga.check("user:bob", "viewer", "document:hr_recruiting_playbook")

    poster = [Tuple("user:*", "viewer", "document:poster")]
    open_board = MemoryFga(
        model,
        poster,
        {"document": ["document:poster", "document:employee_handbook"]},
    )
    assert open_board.check("user:mallory", "viewer", "document:poster")
    assert not open_board.check("user:mallory", "viewer", "document:employee_handbook")
