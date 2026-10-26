"""Análises de tempo de travessia sobre as leituras coletadas (usadas pela visão "Análise" do painel).

Atraso = tempo de travessia - tempo de fluxo livre do sentido. Leituras com o túnel interditado
não têm tempo de travessia real: entram só na contagem de minutos interditados.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .calendario import MINUTOS_POR_SLOT, TZ, tipo_dia
from .config import Config

LENTO_S = 60  # atraso a partir do qual a travessia conta como "lenta"


def preparar(leituras: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    """Acrescenta atraso, data/hora local, tipo de dia e slot de 15 min. Descarta rotas fora da configuração."""
    livre = {r.id: r.tempo_fluxo_livre_s for r in cfg.rotas}
    df = leituras[leituras["rota_id"].isin(livre)].copy()
    df["livre_s"] = df["rota_id"].map(livre)
    df["atraso_s"] = (df["tempo_s"] - df["livre_s"]).clip(lower=0)
    local = pd.to_datetime(df["ts"], unit="s", utc=True).dt.tz_convert(TZ)
    df["data"] = local.dt.date
    df["hora"] = local.dt.hour
    df["slot"] = (local.dt.hour * 60 + local.dt.minute) // MINUTOS_POR_SLOT
    df["tipo_dia"] = df["data"].map({d: tipo_dia(d) for d in df["data"].unique()})
    df["interditado"] = df["interditado"].fillna(0).astype(bool)
    return df


def resumo_rotas(df: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    """Uma linha por sentido configurado, na ordem da configuração."""
    passo_min = cfg.intervalo_coleta_s / 60
    linhas = []
    for r in cfg.rotas:
        s = df[df["rota_id"] == r.id]
        livres = s[~s["interditado"]]
        linhas.append({
            "rota_id": r.id,
            "tunel": r.tunel_nome,
            "sentido": r.sentido,
            "leituras": len(s),
            "livre_s": r.tempo_fluxo_livre_s,
            "mediana_s": livres["tempo_s"].median(),
            "p90_s": livres["tempo_s"].quantile(0.9),
            "max_s": livres["tempo_s"].max(),
            "atraso_medio_s": livres["atraso_s"].mean(),
            "frac_lento": (livres["atraso_s"] >= LENTO_S).mean() if len(livres) else np.nan,
            "min_interditado": float(s["interditado"].sum() * passo_min),
        })
    return pd.DataFrame(linhas)


def mapa_calor(df: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    """Atraso médio (s) por sentido × hora do dia; NaN onde não houve leitura."""
    livres = df[~df["interditado"]]
    tabela = livres.pivot_table(index="rota_id", columns="hora", values="atraso_s", aggfunc="mean")
    return tabela.reindex(index=[r.id for r in cfg.rotas], columns=range(24))


def perfil_diario(df: pd.DataFrame, rota_id: str) -> pd.DataFrame:
    """Mediana, P10 e P90 do tempo de travessia por slot de 15 min (um ponto por slot com leitura)."""
    s = df[(df["rota_id"] == rota_id) & ~df["interditado"]]
    g = s.groupby("slot")["tempo_s"]
    return pd.DataFrame({
        "mediana_s": g.median(),
        "p10_s": g.quantile(0.1),
        "p90_s": g.quantile(0.9),
        "dias": s.groupby("slot")["data"].nunique(),
    }).reset_index()
