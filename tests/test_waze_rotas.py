import re
from dataclasses import replace

from tuneis import storage
from tuneis.coleta import ciclo
from tuneis.detector import REF_WAZE
from tuneis.waze import FonteWaze, carregar_rotas_feed

TS = 1_792_663_200


def _rota(rid, nome, tempo, historico, linha):
    return {"id": rid, "name": nome, "type": "STATIC", "fromName": "A", "toName": "B", "length": 15066,
            "time": tempo, "historicTime": historico, "jamLevel": 2,
            "line": [{"x": lon, "y": lat} for lat, lon in linha], "bbox": {},
            "subRoutes": [{"fromName": "A", "toName": "B", "length": 15066, "time": tempo, "historicTime": historico,
                           "jamLevel": 2, "line": [], "bbox": {}}]}


FEED = {
    "updateTime": TS * 1000,
    "routes": [
        _rota("1787166455405", "BR-101 N Ponte Rio-Niterói - Niteroi ", 2204, 2521, [(-22.889, -43.215), (-22.875, -43.119)]),
        _rota("1787166519721", "BR-101 S Ponte Rio-Niterói - Rio de Janeiro", 1958, 2518, [(-22.878, -43.114), (-22.889, -43.217)]),
        _rota("99", "Túnel Rebouças - Lagoa", 300, 240, [(-22.926, -43.204), (-22.957, -43.204)]),
    ],
    "irregularities": [],
}


class _Fonte(FonteWaze):
    def baixar_feed(self, url: str | None = None) -> dict:
        return FEED


def test_rotas_do_feed_viram_trechos(cfg, conn):
    cfg = replace(cfg, rotas=(), feed_rotas=replace(cfg.feed_rotas, filtro_nome=re.compile(".")))
    avs = ciclo(conn, cfg, _Fonte(cfg, url="x"), {})

    ponte = [r for r in cfg.rotas if r.tunel_nome == "BR-101 Ponte Rio-Niterói"]
    assert [r.sentido for r in ponte] == ["Niteroi", "Rio de Janeiro"]  # os dois sentidos num só trecho
    assert len({r.tunel_id for r in ponte}) == 1
    assert {a.rota_id: a.tempo_s for a in avs} == {"waze_1787166455405": 2204, "waze_1787166519721": 1958, "waze_99": 300}
    assert all(a.fonte_ref == REF_WAZE for a in avs)  # sem histórico próprio: referência = historicTime

    salvas = storage.carregar_rotas_feed(conn)
    assert salvas["waze_99"]["historicTime"] == 240 and "line" not in salvas["waze_99"]["subRoutes"][0]


def test_filtro_de_nome_deixa_so_tuneis(cfg, conn):
    todas = replace(cfg, rotas=(), feed_rotas=replace(cfg.feed_rotas, filtro_nome=re.compile(".")))
    ciclo(conn, todas, _Fonte(todas, url="x"), {})

    so_tuneis = replace(cfg, rotas=(), feed_rotas=replace(cfg.feed_rotas, filtro_nome=re.compile("T[uú]nel", re.I)))
    assert [a.rota_id for a in ciclo(conn, so_tuneis, _Fonte(so_tuneis, url="x"), {}, agora_ts=TS)] == []  # já lidas
    assert [r.id for r in so_tuneis.rotas] == ["waze_99"]
    # rotas guardadas no banco que não passam mais no filtro ficam de fora ao carregar
    novo = replace(so_tuneis, rotas=())
    assert [r.tunel_nome for r in carregar_rotas_feed(conn, novo)] == ["Túnel Rebouças"]


def test_padrao_de_nomes_dos_tuneis(cfg):
    """Nomes como o Partner Hub publica: prefixo "Rota:", "- Sentido X" e túneis de mão única."""
    from tuneis.config import carregar_config
    from tuneis.waze import rota_do_feed, rotas_do_feed

    filtro = carregar_config().feed_rotas.filtro_nome  # o do config/tuneis.yaml
    linha = [(-22.95, -43.19), (-22.96, -43.19)]
    nomes = {
        "Rota: Túnel Rebouças - Sentido Copacabana": ("Túnel Rebouças", "Copacabana"),
        "Rota: Túnel Acústico": ("Túnel Acústico", "sentido único"),
        "Rota: Túnel da Grota Funda x Estação BRT Magarça  -  Via Dom João VI": None,  # corredor
        "Rota: Túnel Santa Bárbara (Laranjeiras - S. Centro) - Radial Oeste (Maracanã) - Via Pres Vargas": None,
        "Rota: Aterro (SDU - S. Porto) - Rua Barão de Tefé - Via Túnel Rio 450": None,
    }
    feed = {"routes": [_rota(str(i), nome, 60, 50, linha) for i, nome in enumerate(nomes)]}
    cfg = replace(cfg, feed_rotas=replace(cfg.feed_rotas, filtro_nome=filtro))
    lidas = {rw["name"]: rota_do_feed(rw, cfg) for rw in rotas_do_feed(feed, cfg)}
    assert {n: (r.tunel_nome, r.sentido) for n, r in lidas.items()} == {n: v for n, v in nomes.items() if v}


def test_tuneis_fora_do_painel(cfg):
    """`feed_rotas.excluir` tira túneis do painel sem mexer no filtro de nome do feed."""
    from tuneis.config import carregar_config
    from tuneis.waze import rotas_do_feed

    fora = ["Rota: Túnel Velho - Sentido Copacabana", "Rota: Túnel Novo - Sentido Botafogo",
            "Rota: Túnel Noel Rosa - Sentido Riachuelo", "Rota: Túnel Nina Rabha - Sentido Centro",
            "Rota: Túnel Major Vaz", "Rota: Túnel João Ricardo - Sentido Laranjeiras",
            "Rota: Túnel Rua Alice - Sentido Cosme Velho"]
    dentro = ["Rota: Túnel Rebouças - Sentido Lagoa", "Rota: Túnel Santa Bárbara - Sentido Laranjeiras"]
    linha = [(-22.95, -43.19), (-22.96, -43.19)]
    feed = {"routes": [_rota(str(i), nome, 60, 50, linha) for i, nome in enumerate(fora + dentro)]}

    cfg = replace(cfg, feed_rotas=carregar_config().feed_rotas)  # o do config/tuneis.yaml
    assert [rw["name"] for rw in rotas_do_feed(feed, cfg)] == dentro

    # sem a exclusão, os mesmos nomes voltam a entrar (o filtro de nome continua aceitando todos)
    todos = replace(cfg.feed_rotas, excluir=())
    assert len(rotas_do_feed(feed, replace(cfg, feed_rotas=todos))) == len(fora) + len(dentro)


def test_segunda_mao_do_marcello_alencar(cfg):
    """A rota nova (sentido Rodoviária) entra no mesmo cartão da rota do sentido Aterro."""
    from tuneis.config import carregar_config
    from tuneis.waze import rota_do_feed, rotas_do_feed

    linha = [(-22.90, -43.18), (-22.89, -43.20)]
    feed = {"routes": [
        _rota("1", "Rota: Túnel Marcello Alencar - Sentido Aterro", 60, 50, linha),
        _rota("2", "Rota: Túnel Pref. Marcello Alencar - Sentido Rodoviária", 70, 60, linha),
        _rota("3", "Rota: Aterro (SDU - S. Porto) - Via Túnel Rio 450", 60, 50, linha),  # corredor
        _rota("4", "Rota: Túnel Pref. Marcello Alencar (Aterro - S. Centro) - Via Pres Vargas", 90, 50, linha),
    ]}
    cfg = replace(cfg, feed_rotas=carregar_config().feed_rotas)  # o do config/tuneis.yaml
    rotas = [rota_do_feed(rw, cfg) for rw in rotas_do_feed(feed, cfg)]

    assert sorted(r.sentido for r in rotas) == ["Aterro", "Rodoviária"]  # os corredores ficaram de fora
    assert {r.tunel_nome for r in rotas} == {"Túnel Marcello Alencar"}
    assert len({r.tunel_id for r in rotas}) == 1  # um cartão só, com as duas mãos
    assert sorted(r.id for r in rotas) == ["waze_1", "waze_2"]  # ids distintos para as duas séries
