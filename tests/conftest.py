import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tuneis import storage  # noqa: E402
from tuneis.config import CONFIG_PADRAO, carregar_config  # noqa: E402


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("TUNEIS_DB", str(tmp_path / "teste.db"))
    monkeypatch.setenv("TUNEIS_FEEDS", str(tmp_path / "feeds"))
    yaml_testes = tmp_path / "tuneis.yaml"
    yaml_testes.write_text(CONFIG_PADRAO.read_text(encoding="utf-8").replace(
        "incluir_tuneis_yaml: false", "incluir_tuneis_yaml: true"), encoding="utf-8")
    return carregar_config(yaml_testes)


@pytest.fixture
def conn(cfg):
    c = storage.conectar(cfg.db_path)
    yield c
    c.close()
