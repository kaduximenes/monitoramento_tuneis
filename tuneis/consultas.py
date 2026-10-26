"""Consultas de leitura usadas pelo painel e pela CLI."""
from __future__ import annotations

import sqlite3

import pandas as pd

from .config import Config
from .detector import ATENCAO, CRITICO, NORMAL, SEM_DADOS

# Ordem de exibição: o pior primeiro
PRIORIDADE = {CRITICO: 3, ATENCAO: 2, SEM_DADOS: 1, NORMAL: 0}


def status_atual(conn: sqlite3.Connection, cfg: Config, agora_ts: int) -> pd.DataFrame:
    rotas = pd.DataFrame(
        [{"rota_id": r.id, "tunel": r.tunel_nome, "sentido": r.sentido} for r in cfg.rotas],
        columns=["rota_id", "tunel", "sentido"],
    )
    ultimas = pd.read_sql_query(
        """
        SELECT a.* FROM avaliacoes a
        JOIN (SELECT rota_id, MAX(ts) AS ts FROM avaliacoes GROUP BY rota_id) u
          ON a.rota_id = u.rota_id AND a.ts = u.ts
        """,
        conn,
    )
    abertos = pd.read_sql_query(
        "SELECT rota_id, inicio_ts AS alerta_desde_ts, nivel_max AS alerta_nivel FROM alertas WHERE status = 'ABERTO'",
        conn,
    )
    df = rotas.merge(ultimas, on="rota_id", how="left").merge(abertos, on="rota_id", how="left")
    df["idade_min"] = (agora_ts - df["ts"]) / 60
    sem_dados = df["ts"].isna() | (df["idade_min"] > cfg.dado_ausente_min)
    df["status"] = df["nivel"].where(~sem_dados, SEM_DADOS)
    df["prioridade"] = df["status"].map(PRIORIDADE)
    return df.sort_values(["prioridade", "razao"], ascending=False, na_position="last").reset_index(drop=True)


def series(conn: sqlite3.Connection, desde_ts: int) -> pd.DataFrame:
    return pd.read_sql_query(
        "SELECT * FROM avaliacoes WHERE ts >= ? ORDER BY rota_id, ts", conn, params=(desde_ts,)
    )


def alertas(conn: sqlite3.Connection, desde_ts: int, rota_id: str | None = None) -> pd.DataFrame:
    sql = "SELECT * FROM alertas WHERE (fim_ts IS NULL OR fim_ts >= ?)"
    params: list = [desde_ts]
    if rota_id:
        sql += " AND rota_id = ?"
        params.append(rota_id)
    return pd.read_sql_query(sql + " ORDER BY inicio_ts DESC", conn, params=params)


def leituras(conn: sqlite3.Connection, desde_ts: int) -> pd.DataFrame:
    return pd.read_sql_query(
        "SELECT rota_id, ts, tempo_s, jam_level, interditado FROM leituras WHERE ts >= ? ORDER BY rota_id, ts",
        conn, params=(desde_ts,),
    )
