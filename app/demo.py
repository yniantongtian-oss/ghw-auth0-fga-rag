"""Print offline answers for the sample employees. Used by the README."""

from __future__ import annotations

from app.config import Settings
from app.runtime import build_engine


QUESTIONS = (
    ("alice", "What is the L6 engineering base salary band?"),
    ("bob", "What is the L6 engineering base salary band?"),
    ("dave", "What is the L6 engineering base salary band?"),
    ("bob", "How many vacation days do full-time employees receive?"),
    ("carol", "What retention grant can a staff engineer receive?"),
    ("bob", "What retention grant can a staff engineer receive?"),
    ("nina", "What happens if Nina Petrov is unavailable for more than 30 days?"),
    ("alice", "What happens if Nina Petrov is unavailable for more than 30 days?"),
)


def main() -> None:
    engine = build_engine(Settings())
    for user_id, question in QUESTIONS:
        result = engine.answer(user_id, question)
        employee = engine.users_by_id[user_id]
        print("=" * 72)
        print(f"{employee.name} ({employee.role}, {employee.department})")
        print(question)
        print("-" * 72)
        print(result.answer)
        print()
        trace = ", ".join(
            f"{item.doc_id}:{'allow' if item.allowed else 'deny'}" for item in result.trace
        )
        print(f"trace: {trace}")
        print(f"withheld: {result.withheld_count}  llm_used: {result.llm_used}")
        print()


if __name__ == "__main__":
    main()
