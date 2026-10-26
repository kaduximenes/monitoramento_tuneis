from tuneis.config import ParametrosDeteccao
from tuneis.detector import CRITICO, NORMAL, REF_FLUXO_LIVRE, Referencia, classificar
from tuneis.waze import parse_feed_trafego

TS = 1_792_663_200


def _jam(street, linha, delay, level=3, end_node=None):
    return {"street": street, "endNode": end_node, "delay": delay, "level": level,
            "line": [{"x": lon, "y": lat} for lat, lon in linha]}


def _rotas(cfg, tunel_id):
    return [r for r in cfg.rotas if r.tunel_id == tunel_id]


def test_atraso_vai_para_o_sentido_certo(cfg):
    ida, volta = _rotas(cfg, "zuzu_angel")  # ida: Gávea -> São Conrado
    feed = {
        "endTimeMillis": TS * 1000,
        "jams": [
            _jam("Túnel Zuzu Angel", [(-22.9926, -43.2514), (-22.9839, -43.2382)], 180),  # São Conrado -> Gávea
            # fila no acesso terminando na boca do túnel, mesmo sentido
            _jam("Autoestrada Lagoa-Barra", [(-22.9960, -43.2560), (-22.9926, -43.2514)], 60, end_node="Túnel Zuzu Angel"),
            # mesmo nome, mas em outra cidade: ignorado
            _jam("Túnel Zuzu Angel", [(-22.50, -43.20), (-22.49, -43.19)], 999),
        ],
        "alerts": [],
    }
    res = parse_feed_trafego(feed, [ida, volta])
    tempos = {l.rota_id: l.tempo_s - cfg.rota(l.rota_id).tempo_fluxo_livre_s for l in res.leituras}
    assert res.leituras[0].ts == TS
    assert tempos == {ida.id: 0, volta.id: 240}


def test_interdicao_por_jam_e_por_alerta(cfg):
    ida, volta = _rotas(cfg, "reboucas")  # ida: Rio Comprido -> Lagoa (para o sul)
    feed = {
        "endTimeMillis": TS * 1000,
        "jams": [_jam("Túnel Antônio Rebouças", [(-22.9405, -43.2024), (-22.9585, -43.2045)], -1, level=5)],
        "alerts": [{"type": "ROAD_CLOSED", "street": "Túnel Antônio Rebouças",
                    "location": {"x": -43.2000, "y": -22.9400}, "magvar": 0}],  # rumo norte
    }
    res = {l.rota_id: l for l in parse_feed_trafego(feed, [ida, volta]).leituras}
    assert res[ida.id].interditado and res[volta.id].interditado
    assert res[ida.id].tempo_s == ida.tempo_fluxo_livre_s  # delay -1 não soma


def test_sem_historico_so_alerta_interdicao():
    p = ParametrosDeteccao()
    ref = Referencia(100, 10, REF_FLUXO_LIVRE)
    assert classificar("r", TS, 400, ref, p).nivel == NORMAL
    assert classificar("r", TS, 100, ref, p, interditado=True).nivel == CRITICO


def test_nomes_e_sentido_como_o_waze_publica(cfg):
    """Casos do feed real: 'Túnel André Rebouças' e o Acústico, mão única para São Conrado."""
    feed = {
        "endTimeMillis": TS * 1000,
        "jams": [
            _jam("Túnel André Rebouças", [(-22.958527, -43.204397), (-22.940537, -43.202224)], 67, level=1),
            _jam("Túnel Acústico Rafael Mascarenhas", [(-22.97892, -43.228896), (-22.981876, -43.234352)], 287,
                 level=4, end_node="Autoestrada Eng. Fernando Mac Dowell"),
        ],
        "alerts": [],
    }
    rotas = _rotas(cfg, "reboucas") + _rotas(cfg, "acustico")
    atraso = {l.rota_id: l.tempo_s - cfg.rota(l.rota_id).tempo_fluxo_livre_s for l in parse_feed_trafego(feed, rotas).leituras}
    assert atraso == {"reboucas_lagoa": 0, "reboucas_rio_comprido": 67, "acustico_sao_conrado": 287}
