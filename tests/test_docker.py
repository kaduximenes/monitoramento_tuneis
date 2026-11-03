"""Guardas do empacotamento: o volume precisa continuar apontando para os dados."""
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parent.parent


def test_volume_cobre_a_pasta_de_dados():
    """O volume deve montar /app/data (banco + feeds) e nunca ser um bind direto para o host."""
    compose = yaml.safe_load((RAIZ / "docker-compose.yml").read_text(encoding="utf-8"))
    servico = compose["services"]["tuneis"]

    assert "dados:/app/data" in servico["volumes"]
    assert "dados" in compose["volumes"]  # volume nomeado declarado
    assert "8501:8501" in servico["ports"]


def test_dockerfile_persiste_os_mesmos_caminhos_do_volume():
    docker = (RAIZ / "Dockerfile").read_text(encoding="utf-8")

    # o app grava onde o volume monta: banco e JSONs do feed
    assert "TUNEIS_DB=/app/data/tuneis.db" in docker
    assert "TUNEIS_FEEDS=/app/data/feeds" in docker
    # /app/data precisa existir na imagem com o dono do usuário da aplicação,
    # senão o volume nasce como root e o coletor não consegue gravar
    assert "chown -R tuneis:tuneis /app/data" in docker
    assert "USER tuneis" in docker


def test_dados_e_segredos_ficam_fora_da_imagem():
    ignorados = set((RAIZ / ".dockerignore").read_text(encoding="utf-8").split())

    assert {"data/", ".env", ".venv/"} <= ignorados
