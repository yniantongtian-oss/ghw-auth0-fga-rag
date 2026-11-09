"""The sample directory: who can view which document, computed from model.fga."""

from app.corpus import load_model_text, load_tuples
from app.fga.dsl import parse_model
from app.fga.memory import MemoryFga

# Document ids the in-memory engine must return for each directory user.
EXPECTED = {
    "alice": {
        "employee_handbook",
        "pto_and_leave",
        "hr_recruiting_playbook",
        "salary_bands_2026",
        "performance_review_rubric",
    },
    "bob": {
        "employee_handbook",
        "pto_and_leave",
        "engineering_onboarding",
    },
    "dave": {
        "employee_handbook",
        "pto_and_leave",
        "hr_recruiting_playbook",
    },
    "carol": {
        "employee_handbook",
        "pto_and_leave",
        "engineering_onboarding",
        "engineering_comp_exceptions",
        "performance_review_rubric",
    },
    "eve": {
        "employee_handbook",
        "pto_and_leave",
    },
    "frank": {
        "employee_handbook",
        "pto_and_leave",
        "performance_review_rubric",
    },
    "nina": {
        "employee_handbook",
        "pto_and_leave",
        "performance_review_rubric",
        "succession_notes",
    },
}


def _ids(objects: list[str]) -> set[str]:
    return {obj.split(":", 1)[1] for obj in objects}


def test_list_objects_matches_the_directory(engine):
    for user_id, expected in EXPECTED.items():
        visible = _ids(engine.fga.list_objects(f"user:{user_id}", "viewer", "document"))
        assert visible == expected, user_id


def test_hr_employee_is_not_an_hr_manager():
    model = parse_model(load_model_text())
    fga = MemoryFga(model, load_tuples())
    assert fga.check("user:alice", "viewer", "document:salary_bands_2026")
    assert not fga.check("user:dave", "viewer", "document:salary_bands_2026")
    assert not fga.check("user:bob", "viewer", "document:salary_bands_2026")
    assert not fga.check("user:nina", "viewer", "document:salary_bands_2026")
    assert not fga.check("user:mallory", "viewer", "document:employee_handbook")


def test_batch_check_agrees_with_list_objects(engine):
    objects = [f"document:{doc.id}" for doc in engine.documents]
    for user_id in EXPECTED:
        user = f"user:{user_id}"
        listed = set(engine.fga.list_objects(user, "viewer", "document"))
        batch = engine.fga.batch_check(user, "viewer", objects)
        allowed = {obj for obj, ok in batch.items() if ok}
        assert allowed == listed
