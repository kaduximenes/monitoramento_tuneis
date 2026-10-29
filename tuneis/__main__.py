"""CLI: python -m tuneis <comando>"""
from __future__ import annotations

import argparse
import logging
import re
import sys
import time
from collections import Counter

from . import consultas, storage
from .baseline import recalcular_baselines
from .coleta import backfill_simulado, executar
from .config import carregar_config
from .simulador import FonteSimulada, forcar_incidente
from .waze import FonteWaze, parse_feed, parse_feed_trafego, rota_do_feed, rotas_do_feed


def _fonte(cfg, args):
    if args.fonte == "sim":
        return FonteSimulada(cfg, taxa_incidentes_dia=args.taxa_incidentes)
    return FonteWaze(cfg)


def cmd_coletar(cfg, args):
    fonte = _fonte(cfg, args)
    if args.fonte == "waze":
        sem_vinculo = [r.id for r in cfg.rotas if r.waze_route_id is None and r.waze_nome is None and r.waze_rua is None]
        if sem_vinculo:
            logging.warning("Rotas sem vínculo com o Waze (rode 'waze-rotas'): %s", ", ".join(sem_vinculo))
    executar(cfg, fonte, args.intervalo or cfg.intervalo_coleta_s, uma_vez=args.uma_vez)


def cmd_backfill_sim(cfg, args):
    conn = storage.conectar(cfg.db_path)
    if storage.ha_leituras(conn):
        if not args.limpar:
            sys.exit("O banco já tem leituras. Use --limpar para apagar tudo e gerar de novo.")
        storage.limpar(conn)
    backfill_simulado(conn, cfg, FonteSimulada(cfg, args.taxa_incidentes), args.dias, args.passo)
    print(f"Histórico simulado de {args.dias} dias gravado em {cfg.db_path}")


def cmd_baseline(cfg, args):
    conn = storage.conectar(cfg.db_path)
    print(f"{recalcular_baselines(conn, cfg)} slots de referência calculados")


def cmd_simular_incidente(cfg, args):
    inicio = int(time.time() + args.em * 60)
    arquivo = forcar_incidente(cfg, args.rota, inicio, args.minutos, args.fator)
    print(f"Incidente em '{args.rota}' ({args.fator}x por {args.minutos} min) registrado em {arquivo}")


def _waze_trafego(cfg, feed):
    """Feed de trânsito: mostra as vias de túnel presentes e o que cada rota capturou."""
    jams = feed.get("jams") or []
    print(f"Feed de trânsito — {len(jams)} congestionamentos, {len(feed.get('alerts') or [])} alertas "
          f"(Rio de Janeiro: {sum(j.get('city') == 'Rio de Janeiro' for j in jams)})")
    tuneis = Counter(
        nome for j in jams if j.get("city") == "Rio de Janeiro"
        for nome in (j.get("street"), j.get("endNode")) if nome and re.search(r"t[uú]nel", nome, re.I)
    )
    print("\nVias de túnel no feed agora (street ou endNode):")
    for nome, n in tuneis.most_common():
        dono = next((r.tunel_id for r in cfg.rotas if r.waze_rua and r.waze_rua.search(nome)), "— sem túnel configurado")
        print(f"  {n:>3}x  {nome:<45} -> {dono}")
    print("\nLeitura de cada rota agora:")
    for leitura in parse_feed_trafego(feed, cfg.rotas).leituras:
        rota = cfg.rota(leitura.rota_id)
        atraso = leitura.tempo_s - rota.tempo_fluxo_livre_s
        extra = " INTERDITADO" if leitura.interditado else ""
        print(f"  {rota.nome:<60} {leitura.tempo_s / 60:5.1f} min (atraso {atraso:4.0f} s, nível {leitura.jam_level}){extra}")
    print("\nAjuste `waze_rua` em config/tuneis.yaml se algum túnel aparecer como 'sem túnel configurado'.")


def cmd_waze_rotas(cfg, args):
    feed = FonteWaze(cfg).baixar_feed()
    if "routes" not in feed:
        _waze_trafego(cfg, feed)
        return
    vinculadas = {r.id for r in cfg.rotas if parse_feed(feed, [r]).leituras}
    print(f"Feed: {feed.get('areaName', '?')} — {len(feed.get('routes') or [])} rotas")
    for r in feed.get("routes") or []:
        print(f"  id={r.get('id')!s:<12} {r.get('length', 0):>6} m  tempo={r.get('time')}s  hist={r.get('historicTime')}s  {r.get('name')}")
    faltando = [r.id for r in cfg.rotas if r.id not in vinculadas]
    print(f"\n{len(vinculadas)}/{len(cfg.rotas)} rotas configuradas encontradas no feed.")
    if faltando:
        print("Sem correspondência:", ", ".join(faltando))

    # Como cada rota do feed vai aparecer no painel (túnel = cartão; sentido = coluna do cartão)
    print("\nEntram no painel:")
    por_tunel: dict[str, list[str]] = {}
    for rw in rotas_do_feed(feed, cfg):
        rota = rota_do_feed(rw, cfg)
        por_tunel.setdefault(rota.tunel_nome, []).append(f"{rota.sentido} (id {rw['id']})")
    for tunel in sorted(por_tunel):
        print(f"  {tunel}: {' · '.join(por_tunel[tunel])}")
    fora = [rw for rw in feed.get("routes") or [] if not cfg.feed_rotas.aceita(" ".join((rw.get("name") or "").split()))]
    print(f"\n{len(feed.get('routes') or []) - len(fora)} de {len(feed.get('routes') or [])} rotas do feed "
          f"entram no painel ({len(fora)} fora do filtro ou na lista `excluir`).")


def cmd_status(cfg, args):
    conn = storage.conectar(cfg.db_path)
    df = consultas.status_atual(conn, cfg, int(time.time()))
    for _, r in df.iterrows():
        tempo = f"{r.tempo_s / 60:5.1f} min (ref {r.referencia_s / 60:4.1f}, {r.razao:.1f}x)" if r.tempo_s == r.tempo_s else "—"
        print(f"{r.status:<10} {r.tunel} ({r.sentido}): {tempo}")


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(prog="tuneis", description="Monitoramento de túneis do Rio por tempo de travessia")
    parser.add_argument("--config", help="caminho do YAML (padrão: config/tuneis.yaml)")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="comando", required=True)

    p = sub.add_parser("coletar", help="coleta contínua + detecção + alertas")
    p.add_argument("--fonte", choices=["waze", "sim"], default="waze")
    p.add_argument("--intervalo", type=int, help="segundos entre coletas (padrão: config)")
    p.add_argument("--uma-vez", action="store_true", help="faz um único ciclo e sai")
    p.add_argument("--taxa-incidentes", type=float, default=0.3, help="[sim] incidentes por rota por dia")
    p.set_defaults(func=cmd_coletar)

    p = sub.add_parser("backfill-sim", help="gera histórico simulado para calibrar as referências")
    p.add_argument("--dias", type=int, default=28)
    p.add_argument("--passo", type=int, default=300, help="segundos entre leituras")
    p.add_argument("--taxa-incidentes", type=float, default=0.3)
    p.add_argument("--limpar", action="store_true", help="apaga o banco antes")
    p.set_defaults(func=cmd_backfill_sim)

    p = sub.add_parser("baseline", help="recalcula as referências históricas")
    p.set_defaults(func=cmd_baseline)

    p = sub.add_parser("simular-incidente", help="[sim] força um aumento no tempo de uma rota")
    p.add_argument("--rota", required=True)
    p.add_argument("--minutos", type=float, default=40)
    p.add_argument("--fator", type=float, default=3.0, help="multiplicador do tempo no pico do incidente")
    p.add_argument("--em", type=float, default=0, help="começa daqui a N minutos")
    p.set_defaults(func=cmd_simular_incidente)

    p = sub.add_parser("waze-rotas", help="lista as rotas do feed do Waze para vincular na configuração")
    p.set_defaults(func=cmd_waze_rotas)

    p = sub.add_parser("status", help="situação atual de cada rota")
    p.set_defaults(func=cmd_status)

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    args.func(carregar_config(args.config), args)


if __name__ == "__main__":
    main()
