"""Fuso, tipo de dia (útil / sábado / domingo-feriado) e slots de 15 minutos."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

import holidays
from dateutil.easter import easter

TZ = ZoneInfo("America/Sao_Paulo")
MINUTOS_POR_SLOT = 15
SLOTS_POR_DIA = 24 * 60 // MINUTOS_POR_SLOT

UTIL, SABADO, DOMINGO_FERIADO = "util", "sabado", "domingo_feriado"


@lru_cache(maxsize=16)
def _feriados(ano: int) -> frozenset[date]:
    dias = set(holidays.Brazil(subdiv="RJ", years=ano).keys())
    dias.add(date(ano, 1, 20))  # São Sebastião, padroeiro da cidade
    pascoa = easter(ano)
    # Carnaval e Corpus Christi: pontos facultativos com tráfego de feriado
    dias.update({pascoa - timedelta(days=48), pascoa - timedelta(days=47), pascoa + timedelta(days=60)})
    return frozenset(dias)


def tipo_dia(d: date) -> str:
    if d.weekday() == 6 or d in _feriados(d.year):
        return DOMINGO_FERIADO
    if d.weekday() == 5:
        return SABADO
    return UTIL


def para_local(ts: int) -> datetime:
    return datetime.fromtimestamp(ts, TZ)


def slot(dt: datetime) -> int:
    return (dt.hour * 60 + dt.minute) // MINUTOS_POR_SLOT


def chave_temporal(ts: int) -> tuple[str, int]:
    dt = para_local(ts)
    return tipo_dia(dt.date()), slot(dt)
