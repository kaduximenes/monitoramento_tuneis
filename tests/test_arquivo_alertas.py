import gzip
import json

from tuneis.arquivo import arquivar, nome_feed
from tuneis.waze import alertas_da_rota

URL = "https://www.waze.com/row-partnerhub-api/feeds-tvt/0000feed-0000-4000-8000-000000000000?id=1"
TS_MS = 1_792_778_400_000  # 2026-10-23 15:00 em Brasília


def test_arquiva_compactado_sem_repetir_e_apaga_dias_antigos(tmp_path):
    antiga = tmp_path / "0000feed" / "2026-10-01"
    antiga.mkdir(parents=True)
    feed = {"updateTime": TS_MS, "routes": [{"id": "1", "name": "Rota: Túnel Velho"}]}

    destino = arquivar(feed, URL, tmp_path, dias=7)
    assert nome_feed(URL) == "0000feed"
    assert destino == tmp_path / "0000feed" / "2026-10-23" / "150000.json.gz"
    assert json.loads(gzip.open(destino, "rt", encoding="utf-8").read()) == feed
    assert json.loads((tmp_path / "0000feed" / "ultimo.json").read_text(encoding="utf-8")) == feed
    assert not antiga.exists()
    assert arquivar(feed, URL, tmp_path, dias=7) is None  # mesmo updateTime: não grava de novo


def test_alertas_da_rota_juntam_rota_e_trechos_sem_repetir():
    faixa = {"id": "a1", "type": "HAZARD", "subType": "HAZARD_ON_ROAD_LANE_CLOSED", "street": "Túnel André Rebouças"}
    acidente = {"id": "a2", "type": "ACCIDENT", "subType": "ACCIDENT_MINOR"}
    rw = {"leadAlert": faixa, "subRoutes": [{"leadAlert": faixa}, {"leadAlert": None}, {"leadAlert": acidente}]}
    assert alertas_da_rota(rw) == [faixa, acidente]
    assert alertas_da_rota({"subRoutes": []}) == []


def test_problemas_de_cadastro(cfg):
    import re
    from dataclasses import replace

    from tuneis.waze import problemas_cadastro

    def rota(nome, extensao, tempo, linha):
        return {"id": nome, "name": nome, "length": extensao, "time": tempo,
                "line": [{"x": x, "y": y} for x, y in linha]}

    perc = [(-43.18, -22.90), (-43.20, -22.89)]
    feed = {"routes": [
        rota("Rota: Túnel Rebouças - Sentido Copacabana", 2729, 151, perc),
        rota("Rota: Túnel Marcello Alencar - Sentido Aterro", 2729, 151, perc),   # mesmo percurso
        rota("Rota: Túnel Rebouças - Sentido Aterro", 0, 0, []),                   # vazia
        rota("Rota: Túnel Zuzu Angel - Sentido Barra", 15659, 1567, [(-43.23, -22.98), (-43.35, -23.0)]),
        rota("Rota: Túnel Santa Bárbara - Sentido Botafogo", 407, 36, [(-43.19, -22.95), (-43.19, -22.96)]),
    ]}
    cfg = replace(cfg, feed_rotas=replace(cfg.feed_rotas, filtro_nome=re.compile("T[uú]nel")))
    achados = {p["nome"]: p["problema"] for p in problemas_cadastro(feed, cfg)}
    assert set(achados) == {"Rota: Túnel Marcello Alencar - Sentido Aterro", "Rota: Túnel Rebouças - Sentido Aterro",
                            "Rota: Túnel Zuzu Angel - Sentido Barra"}
    assert "Túnel Rebouças - Sentido Copacabana" in achados["Rota: Túnel Marcello Alencar - Sentido Aterro"]
    assert "15,7 km" in achados["Rota: Túnel Zuzu Angel - Sentido Barra"]
