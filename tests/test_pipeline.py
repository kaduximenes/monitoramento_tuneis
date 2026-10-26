import re
from dataclasses import replace

from tuneis import consultas, storage
from tuneis.baseline import recalcular_baselines
from tuneis.calendario import chave_temporal
from tuneis.coleta import ciclo
from tuneis.detector import CRITICO, NORMAL
from tuneis.modelos import Baseline, Leitura
from tuneis.monitor import processar_leitura
from tuneis.simulador import FonteSimulada
from tuneis.waze import parse_feed

TS = 1_792_663_200


def test_parse_feed_por_id_e_por_nome(cfg):
    a, b, c = cfg.rotas[:3]
    a = replace(a, waze_route_id="111")
    b = replace(b, waze_nome=re.compile("(?i)rebou.*centro"))
    feed = {
        "updateTime": TS * 1000,
        "routes": [
            {"id": 111, "name": "X", "time": 240, "historicTime": 200, "length": 3500, "jamLevel": 2,
             "line": [{"x": -43.2, "y": -22.9}, {"x": -43.21, "y": -22.95}]},
            {"id": 222, "name": "Rebouças sentido Centro", "time": 0},
        ],
    }
    res = parse_feed(feed, [a, b, c])
    assert [l.rota_id for l in res.leituras] == [a.id]
    assert res.leituras[0].ts == TS and res.leituras[0].historico_s == 200
    assert res.geometrias[a.id][0] == (-22.9, -43.2)
    assert res.ausentes == [b.id, c.id]  # b veio com time=0, c não tem vínculo


def test_alerta_abre_escala_e_encerra(cfg, conn):
    rota = cfg.rotas[0]
    base = {(rota.id, *chave_temporal(TS + i * 120)): Baseline(240, 10, 100, 10) for i in range(12)}
    tempos = [240, 600, 600, 900, 250, 245, 240]

    for i, tempo in enumerate(tempos):
        leitura = Leitura(rota.id, TS + i * 120, tempo, None, None, None, "t")
        storage.inserir_leitura(conn, leitura)
        processar_leitura(conn, cfg, leitura, base)

    alertas = consultas.alertas(conn, 0)
    assert len(alertas) == 1
    a = alertas.iloc[0]
    assert a.status == "ENCERRADO"
    assert a.nivel_max == CRITICO
    assert a.inicio_ts == TS + 120 and a.fim_ts == TS + 4 * 120
    assert a.tempo_max_s == 900


def test_simulador_ponta_a_ponta(cfg, conn):
    fonte = FonteSimulada(cfg, taxa_incidentes_dia=0)
    for i in range(0, 14 * 86400, 1800):
        storage.inserir_leituras(conn, fonte.coletar(TS - 14 * 86400 + i).leituras)
    conn.commit()
    assert recalcular_baselines(conn, cfg, agora_ts=TS) > 0
    avs = ciclo(conn, cfg, fonte, storage.carregar_baselines(conn), agora_ts=TS)
    assert len(avs) == len(cfg.rotas)
    assert all(a.nivel == NORMAL for a in avs)

    status = consultas.status_atual(conn, cfg, TS)
    assert set(status["status"]) == {NORMAL}
