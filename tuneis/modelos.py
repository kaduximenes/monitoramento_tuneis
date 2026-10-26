from __future__ import annotations

from dataclasses import dataclass, field
from typing import NamedTuple


@dataclass(frozen=True)
class Leitura:
    rota_id: str
    ts: int  # epoch (s, UTC)
    tempo_s: float
    historico_s: float | None  # "historicTime" do Waze
    comprimento_m: float | None
    jam_level: int | None
    fonte: str
    interditado: bool = False


@dataclass
class ResultadoColeta:
    leituras: list[Leitura] = field(default_factory=list)
    geometrias: dict[str, list[tuple[float, float]]] = field(default_factory=dict)
    ausentes: list[str] = field(default_factory=list)  # rotas configuradas que não vieram no feed
    rotas_feed: dict[str, dict] = field(default_factory=dict)  # rota_id -> atributos da rota no feed de rotas


class Baseline(NamedTuple):
    mediana_s: float
    mad_s: float
    amostras: int
    dias: int
