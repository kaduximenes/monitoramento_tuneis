"""Gerador de feed no formato do Waze Traffic View, para desenvolvimento e demonstração.

O tempo de cada rota segue um perfil diário (picos da manhã/tarde conforme o sentido,
menores em fins de semana e feriados), com ruído e incidentes aleatórios, mas
determinísticos: o mesmo instante sempre gera o mesmo valor.
Incidentes podem ser forçados com `python -m tuneis simular-incidente`.
"""
from __future__ import annotations

import json
import math
import random
import time
import zlib
from datetime import date, datetime, timedelta
from datetime import time as hora
from pathlib import Path

from .calendario import DOMINGO_FERIADO, SABADO, TZ, UTIL, para_local, tipo_dia
from .config import Config, Rota
from .modelos import ResultadoColeta
from .waze import parse_feed

ESCALA_DIA = {UTIL: 1.0, SABADO: 0.45, DOMINGO_FERIADO: 0.3}
PICOS = {"manha": (1.6, 0.5), "tarde": (0.5, 1.6), "ambos": (1.2, 1.2), "nenhum": (0.3, 0.3)}
RAMPA_S = 600  # a fila leva ~10 min para se formar e para dissipar


def _sino(h: float, centro: float, largura: float) -> float:
    return math.exp(-0.5 * ((h - centro) / largura) ** 2)


def _poisson(rng: random.Random, media: float) -> int:
    limite, k, p = math.exp(-media), 0, rng.random()
    while p > limite:
        k += 1
        p *= rng.random()
    return k


def _jam_level(razao_fluxo_livre: float) -> int:
    for nivel, limite in enumerate((1.3, 1.7, 2.3, 3.2)):
        if razao_fluxo_livre < limite:
            return nivel
    return 4


class FonteSimulada:
    nome = "sim"

    def __init__(self, cfg: Config, taxa_incidentes_dia: float = 0.3, arquivo_forcados: Path | None = None):
        self.cfg = cfg
        self.taxa = taxa_incidentes_dia
        self.arquivo_forcados = arquivo_forcados or arquivo_incidentes_padrao(cfg)
        self._ids = {r.id: str(900000 + i) for i, r in enumerate(cfg.rotas)}
        self._cache_incidentes: dict[tuple[str, date], list[tuple[int, int, float]]] = {}

    def tempo_esperado(self, rota: Rota, ts: int) -> float:
        dt = para_local(ts)
        h = dt.hour + dt.minute / 60
        escala = ESCALA_DIA[tipo_dia(dt.date())]
        manha, tarde = PICOS[rota.pico_sim]
        fator = 1 + escala * (manha * _sino(h, 8.0, 1.1) + tarde * _sino(h, 18.3, 1.4) + 0.3 * _sino(h, 13, 3))
        return rota.tempo_fluxo_livre_s * 1.15 * fator

    def _incidentes(self, rota: Rota, d: date) -> list[tuple[int, int, float]]:
        chave = (rota.id, d)
        if chave not in self._cache_incidentes:
            rng = random.Random(zlib.crc32(f"inc|{rota.id}|{d.isoformat()}".encode()))
            lista = []
            for _ in range(_poisson(rng, self.taxa)):
                inicio = datetime.combine(d, hora(6), TZ) + timedelta(minutes=rng.uniform(0, 17 * 60))
                duracao = timedelta(minutes=rng.uniform(20, 90))
                lista.append((int(inicio.timestamp()), int((inicio + duracao).timestamp()), rng.uniform(1.8, 4.0)))
            self._cache_incidentes[chave] = lista
        return self._cache_incidentes[chave]

    def _forcados(self) -> list[dict]:
        try:
            return json.loads(self.arquivo_forcados.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []

    def fator_incidente(self, rota: Rota, ts: int, forcados: list[dict]) -> float:
        eventos = list(self._incidentes(rota, para_local(ts).date()))
        eventos += [(f["inicio_ts"], f["fim_ts"], f["fator"]) for f in forcados if f["rota_id"] == rota.id]
        fator = 1.0
        for inicio, fim, pico in eventos:
            if inicio <= ts < fim:
                rampa = min(1.0, (ts - inicio) / RAMPA_S, (fim - ts) / RAMPA_S)
                fator = max(fator, 1 + (pico - 1) * rampa)
        return fator

    def gerar_feed(self, ts: int) -> dict:
        forcados = self._forcados()
        rotas = []
        for rota in self.cfg.rotas:
            esperado = self.tempo_esperado(rota, ts)
            ruido = math.exp(random.Random(zlib.crc32(f"{rota.id}|{ts}".encode())).gauss(0, 0.08))
            tempo = esperado * ruido * self.fator_incidente(rota, ts, forcados)
            rotas.append(
                {
                    "id": self._ids[rota.id],
                    "name": rota.nome,
                    "type": "STATIC",
                    "time": round(tempo),
                    "historicTime": round(esperado),
                    "length": round(rota.comprimento_m),
                    "jamLevel": _jam_level(tempo / rota.tempo_fluxo_livre_s),
                    "line": [{"x": lon, "y": lat} for lat, lon in rota.coords],
                }
            )
        return {"areaName": "Rio de Janeiro (simulado)", "updateTime": ts * 1000, "routes": rotas}

    def coletar(self, agora_ts: int | None = None) -> ResultadoColeta:
        return parse_feed(self.gerar_feed(agora_ts or int(time.time())), self.cfg.rotas, ids=self._ids, fonte="sim")


def arquivo_incidentes_padrao(cfg: Config) -> Path:
    return cfg.db_path.parent / "incidentes_simulados.json"


def forcar_incidente(cfg: Config, rota_id: str, inicio_ts: int, minutos: float, fator: float) -> Path:
    cfg.rota(rota_id)  # valida o id
    arquivo = arquivo_incidentes_padrao(cfg)
    agora = int(time.time())
    try:
        eventos = [e for e in json.loads(arquivo.read_text(encoding="utf-8")) if e["fim_ts"] > agora]
    except FileNotFoundError:
        eventos = []
    eventos.append({"rota_id": rota_id, "inicio_ts": inicio_ts, "fim_ts": int(inicio_ts + minutos * 60), "fator": fator})
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    arquivo.write_text(json.dumps(eventos, indent=2), encoding="utf-8")
    return arquivo
