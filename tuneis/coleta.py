"""Laço de coleta e carga histórica simulada."""
from __future__ import annotations

import logging
import sqlite3
import time
from collections import Counter
from typing import Protocol

import requests

from . import storage
from .baseline import recalcular_baselines
from .config import Config
from .detector import Avaliacao
from .modelos import ResultadoColeta
from .monitor import Notificador, processar_leitura
from .waze import carregar_rotas_feed

log = logging.getLogger(__name__)

RECALCULO_BASELINE_S = 3600


class Fonte(Protocol):
    nome: str

    def coletar(self, agora_ts: int | None = None) -> ResultadoColeta: ...


def ciclo(
    conn: sqlite3.Connection,
    cfg: Config,
    fonte: Fonte,
    baselines: dict,
    notificador: Notificador | None = None,
    agora_ts: int | None = None,
) -> list[Avaliacao]:
    res = fonte.coletar(agora_ts)
    for rota_id, coords in res.geometrias.items():
        storage.salvar_geometria(conn, rota_id, coords)
    if res.rotas_feed:
        storage.salvar_rotas_feed(conn, max((l.ts for l in res.leituras), default=int(time.time())), res.rotas_feed)
    avaliacoes = [
        processar_leitura(conn, cfg, leitura, baselines, notificador)
        for leitura in res.leituras
        if storage.inserir_leitura(conn, leitura)
    ]
    conn.commit()
    if res.ausentes:
        log.warning("Rotas sem dados no feed: %s", ", ".join(res.ausentes))
    return avaliacoes


def executar(cfg: Config, fonte: Fonte, intervalo_s: int, uma_vez: bool = False) -> None:
    conn = storage.conectar(cfg.db_path)
    if fonte.nome == "waze":  # rotas do feed já vistas entram na referência desde o 1º recálculo
        carregar_rotas_feed(conn, cfg)
    notificador = Notificador(cfg.webhook_url)
    baselines: dict = {}
    ultimo_recalculo = 0.0
    log.info("Coletando de '%s' a cada %ss -> %s", fonte.nome, intervalo_s, cfg.db_path)

    while True:
        inicio = time.time()
        try:
            if inicio - ultimo_recalculo >= RECALCULO_BASELINE_S:
                n = recalcular_baselines(conn, cfg)
                baselines = storage.carregar_baselines(conn)
                ultimo_recalculo = inicio
                log.info("Referências recalculadas (%d slots)", n)
            avaliacoes = ciclo(conn, cfg, fonte, baselines, notificador)
            if avaliacoes:
                niveis = Counter(a.nivel for a in avaliacoes)
                log.info("%d leituras novas: %s", len(avaliacoes), dict(niveis))
            else:
                log.info("Feed sem atualização")
        except requests.RequestException as e:
            log.error("Falha ao consultar o feed: %s", e)
        except Exception:
            log.exception("Erro no ciclo de coleta")

        if uma_vez:
            break
        time.sleep(max(1.0, intervalo_s - (time.time() - inicio)))
    conn.close()


def backfill_simulado(
    conn: sqlite3.Connection, cfg: Config, fonte: Fonte, dias: int, passo_s: int, horas_avaliadas: int = 24
) -> None:
    """Gera `dias` de histórico. As últimas `horas_avaliadas` passam pelo pipeline completo
    (avaliações e alertas), para que o painel já tenha série e histórico de alertas."""
    agora = int(time.time()) // passo_s * passo_s
    corte = agora - horas_avaliadas * 3600

    for ts in range(agora - dias * 86400, corte, passo_s):
        res = fonte.coletar(ts)
        storage.inserir_leituras(conn, res.leituras)
    for rota_id, coords in res.geometrias.items():
        storage.salvar_geometria(conn, rota_id, coords)
    conn.commit()

    log.info("Calculando referências...")
    recalcular_baselines(conn, cfg, agora_ts=corte)
    baselines = storage.carregar_baselines(conn)

    log.info("Avaliando as últimas %dh...", horas_avaliadas)
    for ts in range(corte, agora + 1, passo_s):
        ciclo(conn, cfg, fonte, baselines, agora_ts=ts)
