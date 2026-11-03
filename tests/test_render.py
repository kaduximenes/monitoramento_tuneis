"""Render: confere que o disco persistente existe e que os dados apontam para dentro dele."""
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parent.parent
MB_DIA_FEED = 180  # ordem de grandeza do JSON bruto do feed, citada no README e no tuneis.yaml


def _servico() -> dict:
    doc = yaml.safe_load((RAIZ / "render.yaml").read_text(encoding="utf-8"))
    return next(s for s in doc["services"] if s["type"] == "web")


def test_disco_persistente_montado():
    disco = _servico()["disk"]

    assert disco["mountPath"].startswith("/")  # caminho absoluto dentro do container
    assert disco["sizeGB"] >= 1
    assert disco["name"]  # o nome do disco é o que o Render mantém entre deploys


def test_disco_cabe_a_retencao_dos_feeds():
    """Disco cheio faz o coletor parar de gravar: o tamanho precisa cobrir a retenção configurada."""
    config = yaml.safe_load((RAIZ / "config" / "tuneis.yaml").read_text(encoding="utf-8"))
    dias = config["coleta"]["dias_feeds"]
    precisa_gb = dias * MB_DIA_FEED / 1000 + 0.5  # folga para o banco e o WAL

    assert _servico()["disk"]["sizeGB"] >= precisa_gb, (
        f"disco de {_servico()['disk']['sizeGB']} GB não cabe {dias} dias de feed (~{precisa_gb:.1f} GB)"
    )


def test_dados_gravados_dentro_do_disco():
    """Se os caminhos fugirem do mountPath, o Render grava no diretório do repositório e perde tudo."""
    servico = _servico()
    montagem = servico["disk"]["mountPath"]
    env = {e["key"]: e.get("value") for e in servico["envVars"]}

    for chave in ("TUNEIS_DB", "TUNEIS_FEEDS"):
        assert chave in env, f"{chave} precisa apontar para dentro de {montagem}"
        assert env[chave].startswith(montagem + "/"), f"{chave}={env[chave]} fora do disco {montagem}"


def test_disco_exige_plano_pago():
    """Disco no Render não existe no plano free: o serviço tem de estar em plano pago."""
    assert _servico()["plan"] != "free"
