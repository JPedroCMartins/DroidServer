import pytest


@pytest.fixture(autouse=True)
def _bancos_isolados(monkeypatch, tmp_path_factory):
    """Os workers de banco (banco.py) nunca leem o ~/.local da máquina de testes."""
    monkeypatch.setenv("DROID_BANCOS_DIR", str(tmp_path_factory.mktemp("bancos")))
