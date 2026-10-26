"""Arquivo do JSON bruto de cada leitura dos feeds do Waze.

data/feeds/<feed>/ultimo.json                  a leitura mais recente, legível
data/feeds/<feed>/<AAAA-MM-DD>/<HHMMSS>.json.gz cada leitura, compactada (nome = updateTime local)

<feed> = 8 primeiros caracteres do id do feed na URL. Leituras repetidas (mesmo updateTime)
não são gravadas de novo, e as pastas de dias mais antigos que `dias` são apagadas.
"""
from __future__ import annotations

import gzip
import json
import logging
import shutil
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

from .calendario import TZ

log = logging.getLogger(__name__)


def nome_feed(url: str) -> str:
    return (urlparse(url).path.rstrip("/").rsplit("/", 1)[-1] or "feed")[:8]


def arquivar(feed: dict, url: str, pasta: Path, dias: int) -> Path | None:
    """Grava o feed e retorna o arquivo criado (None se essa leitura já estava gravada)."""
    base = pasta / nome_feed(url)
    ts = (feed.get("updateTime") or feed.get("endTimeMillis") or datetime.now().timestamp() * 1000) / 1000
    quando = datetime.fromtimestamp(ts, TZ)
    destino = base / f"{quando:%Y-%m-%d}" / f"{quando:%H%M%S}.json.gz"
    if destino.exists():
        return None
    destino.parent.mkdir(parents=True, exist_ok=True)
    texto = json.dumps(feed, ensure_ascii=False)
    with gzip.open(destino, "wt", encoding="utf-8") as f:
        f.write(texto)
    (base / "ultimo.json").write_text(texto, encoding="utf-8")
    _limpar(base, quando.date() - timedelta(days=dias))
    return destino


def _limpar(base: Path, antes_de: date) -> None:
    for d in base.iterdir():
        try:
            velho = d.is_dir() and date.fromisoformat(d.name) < antes_de
        except ValueError:
            continue
        if velho:
            shutil.rmtree(d, ignore_errors=True)
            log.info("Arquivo do feed: apagada a pasta %s", d)
