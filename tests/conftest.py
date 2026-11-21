import pytest
from app import store
from app.config import ROOT
from app.pipeline import calculate,load_sample
@pytest.fixture(autouse=True)
def isolated_database(tmp_path,monkeypatch):
    monkeypatch.setattr(store,"DATA_DIR",tmp_path)
    from app.evidence import store as evidence_store
    monkeypatch.setattr(evidence_store,"DATA_DIR",tmp_path)
@pytest.fixture
def sample(): return load_sample("dirty.csv")
@pytest.fixture
def result(sample): return calculate(sample)
@pytest.fixture
def client():
    from app.main import create_app
    return create_app().test_client()
@pytest.fixture
def evidence_raw():
    return (ROOT/"sample_data"/"shared_evidence.csv").read_bytes()
@pytest.fixture
def over_allocation_raw():
    return (ROOT/"sample_data"/"over_allocation.csv").read_bytes()
