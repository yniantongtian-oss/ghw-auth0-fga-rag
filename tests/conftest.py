import pytest

from app.config import Settings
from app.runtime import build_engine


@pytest.fixture
def engine():
    return build_engine(Settings())
