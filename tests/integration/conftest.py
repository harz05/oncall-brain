import os

import pytest

from oncall_brain.wiring import make_store


@pytest.fixture(scope="session")
def store():
    try:
        s = make_store()
        s.db.connection.ping()
    except Exception:
        pytest.skip("FalkorDB not reachable (run `make db`)")
    return s


@pytest.fixture
def tenant(store, request):
    name = f"itest_{os.getpid()}_{request.node.name[:20].lower()}"
    name = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in name)[:40]
    store.drop(name)
    yield name
    store.drop(name)
