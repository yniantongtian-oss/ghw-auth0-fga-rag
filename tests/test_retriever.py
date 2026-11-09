"""The retriever searches the full index, then drops documents FGA denies."""

from app.config import Settings
from app.fga.http import FgaError
from app.rag.engine import Engine
from app.rag.index import Chunk

SALARY = "SENTINEL_SALARY_L6_242000"
RETENTION = "SENTINEL_ENG_RETENTION_88000"
SUCCESSION = "SENTINEL_SUCCESSION_NINA_ONLY"
SALARY_QUESTION = "What is the L6 engineering base salary band?"


class OnlySalary:
    def search(self, query: str, k: int) -> list[Chunk]:
        return [
            Chunk(
                doc_id="salary_bands_2026",
                title="Salary Bands 2026",
                text=f"The L6 engineering base salary band is 242000 USD ({SALARY}).",
                score=0.91,
            )
        ][:k]


class BoomFga:
    def list_objects(self, user: str, relation: str, object_type: str) -> list[str]:
        raise FgaError("authorization service down")

    def batch_check(self, user: str, relation: str, objects: list[str]) -> dict[str, bool]:
        raise FgaError("authorization service down")


class ListAllowsBatchDenies:
    def list_objects(self, user: str, relation: str, object_type: str) -> list[str]:
        return ["document:salary_bands_2026"]

    def batch_check(self, user: str, relation: str, objects: list[str]) -> dict[str, bool]:
        return {obj: False for obj in objects}


class BatchAllowsListDenies:
    def list_objects(self, user: str, relation: str, object_type: str) -> list[str]:
        return []

    def batch_check(self, user: str, relation: str, objects: list[str]) -> dict[str, bool]:
        return {obj: True for obj in objects}


def test_manager_retrieves_salary_and_employee_is_denied(engine):
    order: list[str] = []
    real = engine.fga

    class Recording:
        def list_objects(self, user, relation, object_type):
            order.append("list_objects")
            return real.list_objects(user, relation, object_type)

        def batch_check(self, user, relation, objects):
            order.append("batch_check")
            return real.batch_check(user, relation, objects)

    engine.fga = Recording()

    def complete(question: str, context: str) -> str:
        order.append("llm")
        return context

    alice = engine.answer("alice", SALARY_QUESTION, complete=complete)
    assert any(chunk.doc_id == "salary_bands_2026" for chunk in engine.retrieve("alice", SALARY_QUESTION).candidates)
    # retrieve() above appended more events; check the answer path separately.
    assert SALARY in alice.llm_context
    assert "242000" in alice.answer
    assert any(item.doc_id == "salary_bands_2026" and item.allowed for item in alice.trace)

    order.clear()
    bob = engine.answer("bob", SALARY_QUESTION, complete=complete)
    assert order[0] == "list_objects"
    assert order[1] == "batch_check"
    assert (not order[2:] or order[2] == "llm")
    if "llm" in order:
        assert order.index("batch_check") < order.index("llm")
    assert SALARY not in bob.llm_context
    assert SALARY not in bob.answer
    assert "242000" not in bob.answer
    assert all(item.doc_id != "salary_bands_2026" or not item.allowed for item in bob.trace)
    bob_retrieval = engine.retrieve("bob", SALARY_QUESTION)
    assert any(chunk.doc_id == "salary_bands_2026" for chunk in bob_retrieval.candidates)
    assert all(chunk.doc_id != "salary_bands_2026" for chunk in bob_retrieval.allowed_chunks)


def test_salary_only_candidate_never_reaches_the_model_for_an_employee(engine):
    gated = Engine(OnlySalary(), engine.fga, Settings(), engine.documents, engine.users)
    seen: list[str] = []

    def complete(question: str, context: str) -> str:
        seen.append(context)
        return context

    bob = gated.answer("bob", SALARY_QUESTION, complete=complete)
    assert seen == []
    assert SALARY not in bob.answer
    assert bob.llm_context == ""
    assert bob.trace[0].doc_id == "salary_bands_2026"
    assert bob.trace[0].allowed is False

    alice = gated.answer("alice", SALARY_QUESTION, complete=complete)
    assert seen and SALARY in seen[0]
    assert alice.trace[0].allowed is True


def test_hr_employee_dave_is_denied_salary_text(engine):
    dave = engine.answer("dave", SALARY_QUESTION)
    assert SALARY not in dave.llm_context
    assert SALARY not in dave.answer
    assert "242000" not in dave.answer


def test_fail_closed_when_fga_errors(engine):
    gated = Engine(OnlySalary(), BoomFga(), Settings(), engine.documents, engine.users)
    seen: list[str] = []
    result = gated.answer("alice", SALARY_QUESTION, complete=lambda q, ctx: seen.append(ctx) or ctx)
    assert seen == []
    assert result.batch_failed is True
    assert SALARY not in result.answer
    assert "couldn't confirm" in result.answer


def test_either_check_can_withhold(engine):
    salary_index = OnlySalary()
    denied = Engine(salary_index, ListAllowsBatchDenies(), Settings(), engine.documents, engine.users)
    other = Engine(salary_index, BatchAllowsListDenies(), Settings(), engine.documents, engine.users)
    for gated in (denied, other):
        result = gated.answer("alice", SALARY_QUESTION, complete=lambda q, ctx: ctx)
        assert SALARY not in result.llm_context
        assert result.trace[0].allowed is False


def test_employee_can_read_leave_and_onboarding(engine):
    leave = engine.answer("bob", "How many vacation days do full-time employees receive?")
    assert "22" in leave.answer
    assert any(item.doc_id == "pto_and_leave" and item.allowed for item in leave.trace)

    badge = engine.answer("bob", "What is the engineering badge code?")
    assert "ENG-BADGE-4419" in badge.answer
    assert "ENG-BADGE-4419" not in engine.answer("alice", "What is the engineering badge code?").answer


def test_manager_scoped_documents_stay_in_their_lane(engine):
    carol = engine.answer("carol", "What retention grant can a staff engineer receive?")
    bob = engine.answer("bob", "What retention grant can a staff engineer receive?")
    assert RETENTION in carol.llm_context
    assert RETENTION not in bob.llm_context
    assert RETENTION not in bob.answer

    nina = engine.answer("nina", "What happens if Nina Petrov is unavailable for more than 30 days?")
    alice = engine.answer("alice", "What happens if Nina Petrov is unavailable for more than 30 days?")
    assert SUCCESSION in nina.llm_context
    assert SUCCESSION not in alice.llm_context
    assert SUCCESSION not in alice.answer


def test_salary_document_is_the_top_hit_in_the_index(engine):
    ranked = engine.index.search(SALARY_QUESTION, k=5)
    assert ranked[0].doc_id == "salary_bands_2026"
    assert SALARY in ranked[0].text
