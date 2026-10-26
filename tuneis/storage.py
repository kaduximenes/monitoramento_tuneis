"""Persistência em SQLite (modo WAL: o painel lê enquanto o coletor escreve)."""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from pathlib import Path

from .detector import GRAVIDADE, Avaliacao
from .modelos import Baseline, Leitura

SCHEMA = """
CREATE TABLE IF NOT EXISTS leituras (
    rota_id       TEXT    NOT NULL,
    ts            INTEGER NOT NULL,
    tempo_s       REAL    NOT NULL,
    historico_s   REAL,
    comprimento_m REAL,
    jam_level     INTEGER,
    fonte         TEXT    NOT NULL,
    interditado   INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (rota_id, ts)
);
CREATE INDEX IF NOT EXISTS ix_leituras_ts ON leituras (ts);

CREATE TABLE IF NOT EXISTS baselines (
    rota_id   TEXT    NOT NULL,
    tipo_dia  TEXT    NOT NULL,
    slot      INTEGER NOT NULL,
    mediana_s REAL    NOT NULL,
    mad_s     REAL    NOT NULL,
    amostras  INTEGER NOT NULL,
    dias      INTEGER NOT NULL,
    PRIMARY KEY (rota_id, tipo_dia, slot)
);

CREATE TABLE IF NOT EXISTS avaliacoes (
    rota_id      TEXT    NOT NULL,
    ts           INTEGER NOT NULL,
    tempo_s      REAL    NOT NULL,
    referencia_s REAL    NOT NULL,
    dispersao_s  REAL    NOT NULL,
    fonte_ref    TEXT    NOT NULL,
    razao        REAL    NOT NULL,
    z            REAL    NOT NULL,
    nivel        TEXT    NOT NULL,
    interditado  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (rota_id, ts)
);

CREATE TABLE IF NOT EXISTS alertas (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    rota_id      TEXT    NOT NULL,
    status       TEXT    NOT NULL,  -- ABERTO | ENCERRADO
    inicio_ts    INTEGER NOT NULL,
    fim_ts       INTEGER,
    ultima_ts    INTEGER NOT NULL,
    nivel_max    TEXT    NOT NULL,
    tempo_max_s  REAL    NOT NULL,
    referencia_s REAL    NOT NULL,
    razao_max    REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_alertas_rota_status ON alertas (rota_id, status);

CREATE TABLE IF NOT EXISTS geometrias (
    rota_id TEXT PRIMARY KEY,
    coords  TEXT NOT NULL  -- JSON [[lat, lon], ...]
);

CREATE TABLE IF NOT EXISTS rotas_feed (
    rota_id TEXT PRIMARY KEY,
    ts      INTEGER NOT NULL,  -- leitura mais recente em que a rota veio no feed
    dados   TEXT NOT NULL      -- JSON: a rota como o Waze publica (trechos sem geometria)
);
"""

TABELAS = ("leituras", "baselines", "avaliacoes", "alertas", "geometrias", "rotas_feed")


def conectar(caminho: str | Path) -> sqlite3.Connection:
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(caminho, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(SCHEMA)
    return conn


def limpar(conn: sqlite3.Connection) -> None:
    for tabela in TABELAS:
        conn.execute(f"DELETE FROM {tabela}")
    conn.commit()


def ha_leituras(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT 1 FROM leituras LIMIT 1").fetchone() is not None


# --- leituras -----------------------------------------------------------------

def _tupla(l: Leitura) -> tuple:
    return (l.rota_id, l.ts, l.tempo_s, l.historico_s, l.comprimento_m, l.jam_level, l.fonte, int(l.interditado))


def inserir_leitura(conn: sqlite3.Connection, leitura: Leitura) -> bool:
    """Retorna False se a leitura já existia (feed do Waze ainda não atualizou)."""
    cur = conn.execute("INSERT OR IGNORE INTO leituras VALUES (?, ?, ?, ?, ?, ?, ?, ?)", _tupla(leitura))
    return cur.rowcount == 1


def inserir_leituras(conn: sqlite3.Connection, leituras: Iterable[Leitura]) -> None:
    conn.executemany("INSERT OR IGNORE INTO leituras VALUES (?, ?, ?, ?, ?, ?, ?, ?)", map(_tupla, leituras))


# --- geometrias ---------------------------------------------------------------

def salvar_geometria(conn: sqlite3.Connection, rota_id: str, coords: list[tuple[float, float]]) -> None:
    conn.execute("INSERT OR REPLACE INTO geometrias VALUES (?, ?)", (rota_id, json.dumps(coords)))


def carregar_geometrias(conn: sqlite3.Connection) -> dict[str, list[list[float]]]:
    return {r["rota_id"]: json.loads(r["coords"]) for r in conn.execute("SELECT * FROM geometrias")}


# --- rotas do feed -------------------------------------------------------------

def salvar_rotas_feed(conn: sqlite3.Connection, ts: int, rotas: dict[str, dict]) -> None:
    conn.executemany("INSERT OR REPLACE INTO rotas_feed VALUES (?, ?, ?)",
                     [(rota_id, ts, json.dumps(dados, ensure_ascii=False)) for rota_id, dados in rotas.items()])


def carregar_rotas_feed(conn: sqlite3.Connection) -> dict[str, dict]:
    return {r["rota_id"]: {**json.loads(r["dados"]), "_visto_ts": r["ts"]}
            for r in conn.execute("SELECT * FROM rotas_feed ORDER BY rota_id")}


# --- baselines ----------------------------------------------------------------

def substituir_baselines(conn: sqlite3.Connection, linhas: Iterable[tuple]) -> None:
    conn.execute("DELETE FROM baselines")
    conn.executemany("INSERT INTO baselines VALUES (?, ?, ?, ?, ?, ?, ?)", linhas)


def carregar_baselines(conn: sqlite3.Connection) -> dict[tuple[str, str, int], Baseline]:
    return {
        (r["rota_id"], r["tipo_dia"], r["slot"]): Baseline(r["mediana_s"], r["mad_s"], r["amostras"], r["dias"])
        for r in conn.execute("SELECT * FROM baselines")
    }


# --- avaliações e alertas -----------------------------------------------------

def salvar_avaliacao(conn: sqlite3.Connection, av: Avaliacao) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO avaliacoes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (av.rota_id, av.ts, av.tempo_s, av.referencia_s, av.dispersao_s, av.fonte_ref, av.razao, av.z, av.nivel,
         int(av.interditado)),
    )


def ultimas_avaliacoes(conn: sqlite3.Connection, rota_id: str, n: int) -> list[tuple[int, str]]:
    """(ts, nivel) das n avaliações mais recentes, em ordem cronológica."""
    linhas = conn.execute(
        "SELECT ts, nivel FROM avaliacoes WHERE rota_id = ? ORDER BY ts DESC LIMIT ?", (rota_id, n)
    ).fetchall()
    return [(r["ts"], r["nivel"]) for r in reversed(linhas)]


def _alerta(conn: sqlite3.Connection, alerta_id: int) -> dict:
    return dict(conn.execute("SELECT * FROM alertas WHERE id = ?", (alerta_id,)).fetchone())


def alerta_aberto(conn: sqlite3.Connection, rota_id: str) -> dict | None:
    r = conn.execute(
        "SELECT * FROM alertas WHERE rota_id = ? AND status = 'ABERTO' ORDER BY id DESC LIMIT 1", (rota_id,)
    ).fetchone()
    return dict(r) if r else None


def abrir_alerta(conn: sqlite3.Connection, inicio_ts: int, nivel: str, av: Avaliacao) -> dict:
    cur = conn.execute(
        "INSERT INTO alertas (rota_id, status, inicio_ts, ultima_ts, nivel_max, tempo_max_s, referencia_s, razao_max)"
        " VALUES (?, 'ABERTO', ?, ?, ?, ?, ?, ?)",
        (av.rota_id, inicio_ts, av.ts, nivel, av.tempo_s, av.referencia_s, av.razao),
    )
    return _alerta(conn, cur.lastrowid)


def atualizar_alerta(conn: sqlite3.Connection, alerta: dict, av: Avaliacao) -> dict:
    nivel = av.nivel if GRAVIDADE[av.nivel] > GRAVIDADE[alerta["nivel_max"]] else alerta["nivel_max"]
    conn.execute(
        "UPDATE alertas SET ultima_ts = ?, nivel_max = ?, tempo_max_s = MAX(tempo_max_s, ?),"
        " razao_max = MAX(razao_max, ?) WHERE id = ?",
        (av.ts, nivel, av.tempo_s, av.razao, alerta["id"]),
    )
    return _alerta(conn, alerta["id"])


def encerrar_alerta(conn: sqlite3.Connection, alerta: dict, fim_ts: int, ultima_ts: int) -> dict:
    conn.execute(
        "UPDATE alertas SET status = 'ENCERRADO', fim_ts = ?, ultima_ts = ? WHERE id = ?",
        (fim_ts, ultima_ts, alerta["id"]),
    )
    return _alerta(conn, alerta["id"])
