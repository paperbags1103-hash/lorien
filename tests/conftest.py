import pytest

from lorien.schema import GraphStore


@pytest.fixture
def tmp_store(tmp_path):
    db_path = tmp_path / "test_db"
    store = GraphStore(db_path=str(db_path))
    yield store
