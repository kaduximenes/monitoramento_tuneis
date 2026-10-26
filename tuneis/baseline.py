"""Referência histórica robusta: mediana e MAD por rota x tipo de dia x slot de 15 min.

Cada slot usa as leituras dele e dos dois vizinhos (janela de 45 min) para ter amostras
suficientes. Mediana/MAD são pouco afetadas pelos próprios incidentes do histórico.
"""
from __future__ import annotations

import sqlite3
import time

import pandas as pd

from . import storage
from .calendario import MINUTOS_POR_SLOT, SLOTS_POR_DIA, TZ, tipo_dia
from .config import Config

SEMANA_S = 7 * 86400


def recalcular_baselines(conn: sqlite3.Connection, cfg: Config, agora_ts: int | None = None) -> int:
    agora = agora_ts or int(time.time())
    janelas = {r.id: r.deteccao.janela_baseline_semanas * SEMANA_S for r in cfg.rotas}
    if not janelas:  # nenhuma rota ainda (feed de rotas antes da 1ª coleta)
        return 0
    df = pd.read_sql_query(
        "SELECT rota_id, ts, tempo_s FROM leituras WHERE ts >= ? AND ts < ? AND tempo_s > 0",
        conn,
        params=(agora - max(janelas.values()), agora),
    )
    df = df[df["ts"] >= agora - df["rota_id"].map(janelas)]
    if df.empty:
        storage.substituir_baselines(conn, [])
        conn.commit()
        return 0

    local = pd.to_datetime(df["ts"], unit="s", utc=True).dt.tz_convert(TZ)
    datas = local.dt.date
    df["tipo_dia"] = datas.map({d: tipo_dia(d) for d in datas.unique()})
    df["data"] = datas
    df["slot"] = (local.dt.hour * 60 + local.dt.minute) // MINUTOS_POR_SLOT

    vizinhos = pd.concat(
        [df.assign(slot=(df["slot"] + d) % SLOTS_POR_DIA) for d in (-1, 0, 1)], ignore_index=True
    )
    chaves = ["rota_id", "tipo_dia", "slot"]
    vizinhos["mediana"] = vizinhos.groupby(chaves)["tempo_s"].transform("median")
    vizinhos["desvio"] = (vizinhos["tempo_s"] - vizinhos["mediana"]).abs()
    agg = vizinhos.groupby(chaves).agg(
        mediana_s=("mediana", "first"), mad_s=("desvio", "median"), amostras=("tempo_s", "size"),
        dias=("data", "nunique"),
    )

    storage.substituir_baselines(
        conn,
        [(r, t, int(s), float(m), float(d), int(n), int(nd)) for (r, t, s), (m, d, n, nd) in agg.iterrows()],
    )
    conn.commit()
    return len(agg)
