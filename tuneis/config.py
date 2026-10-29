"""Carga da configuração (config/tuneis.yaml + variáveis de ambiente)."""
from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent
CONFIG_PADRAO = RAIZ / "config" / "tuneis.yaml"


@dataclass(frozen=True)
class ParametrosDeteccao:
    janela_baseline_semanas: int = 8
    min_amostras: int = 20
    razao_atencao: float = 1.4
    z_atencao: float = 3.0
    razao_critico: float = 2.0
    z_critico: float = 4.0
    leituras_para_abrir: int = 2
    leituras_para_fechar: int = 3
    piso_dispersao_frac: float = 0.10
    piso_dispersao_s: float = 10.0
    min_dias: int = 3
    alertar_sem_historico: bool = False


@dataclass(frozen=True)
class Rota:
    """Um sentido de um túnel: a unidade monitorada."""

    id: str
    tunel_id: str
    tunel_nome: str
    sentido: str
    comprimento_m: float
    velocidade_max_kmh: float
    coords: tuple[tuple[float, float], ...]  # (lat, lon) na ordem do sentido
    waze_route_id: str | None
    waze_nome: re.Pattern | None
    waze_rua: re.Pattern | None  # feed de trânsito: nome da via (street/endNode)
    pico_sim: str
    deteccao: ParametrosDeteccao
    waze_feed_id: str | None = None  # rota descoberta no feed de rotas (Traffic View)

    @property
    def nome(self) -> str:
        return f"{self.tunel_nome} ({self.sentido})"

    @property
    def tempo_fluxo_livre_s(self) -> float:
        return self.comprimento_m / (self.velocidade_max_kmh / 3.6)

    @property
    def rumo(self) -> tuple[float, float]:
        """Vetor (leste, norte) do início ao fim do sentido, em graus aproximados."""
        (lat0, lon0), (lat1, lon1) = self.coords[0], self.coords[-1]
        return (lon1 - lon0) * math.cos(math.radians(lat0)), lat1 - lat0


@dataclass(frozen=True)
class GrupoRota:
    """Força uma rota do feed para um túnel/sentido do painel.

    Serve para nomes que fogem do padrão "Rota: <túnel> - Sentido <destino>": garante que as
    duas mãos caiam no mesmo cartão e que o sentido apareça com o nome usado na operação.
    """

    nome: re.Pattern  # regex no `name` da rota no feed
    tunel: str  # nome do túnel no painel (define o cartão)
    sentido: str | None = None  # rótulo do sentido; None = usa o que veio no nome


# Corredor que apenas cita o túnel no nome (mesmo critério do `filtro_nome`): um `agrupar`
# não deve trazê-lo para dentro do cartão do túnel.
_CORREDOR = re.compile(r"\(|\s-\s+Via\b", re.I)


@dataclass(frozen=True)
class ParametrosFeedRotas:
    """Rotas do feed Traffic View que entram no monitoramento sem estar no YAML."""

    filtro_nome: re.Pattern  # só as rotas cujo `name` casa com isso
    velocidade_livre_kmh: float  # o feed não traz o fluxo livre: estimado por extensão / velocidade
    excluir: tuple[re.Pattern, ...] = ()  # túneis tirados do painel, mesmo passando no filtro
    agrupar: tuple[GrupoRota, ...] = ()  # rotas que devem cair num túnel/sentido já existente

    def grupo(self, nome: str) -> GrupoRota | None:
        if _CORREDOR.search(nome):  # corredor que só cita o túnel: fica fora do cartão
            return None
        return next((g for g in self.agrupar if g.nome.search(nome)), None)

    def aceita(self, nome: str) -> bool:
        """Entra no painel: não está em `excluir` e casa com `filtro_nome` ou com um `agrupar`."""
        if any(p.search(nome) for p in self.excluir):
            return False
        return bool(self.filtro_nome.search(nome)) or self.grupo(nome) is not None


@dataclass
class Config:
    rotas: tuple[Rota, ...]
    intervalo_coleta_s: int
    dado_ausente_min: int
    db_path: Path
    waze_feed_url: str | None
    webhook_url: str | None
    waze_feeds_extras: tuple[str, ...] = ()  # outros feeds lidos junto (ex.: o da Ponte Rio-Niterói)
    pasta_feeds: Path | None = None  # onde guardar o JSON bruto de cada leitura (None = não guarda)
    dias_feeds: int = 7
    feed_rotas: ParametrosFeedRotas = field(
        default_factory=lambda: ParametrosFeedRotas(re.compile(r"T[uú]nel", re.I), 60.0))
    deteccao_padrao: ParametrosDeteccao = field(default_factory=ParametrosDeteccao)
    _por_id: dict[str, Rota] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._por_id = {r.id: r for r in self.rotas}
        if len(self._por_id) != len(self.rotas):
            raise ValueError("Há ids de rota duplicados na configuração")

    def rota(self, rota_id: str) -> Rota:
        return self._por_id[rota_id]

    def incluir(self, rotas) -> list[Rota]:
        """Acrescenta (ou atualiza) rotas descobertas no feed. Retorna as que eram novas."""
        novas = [r for r in rotas if r.id not in self._por_id]
        self._por_id.update({r.id: r for r in rotas})
        self.rotas = tuple(self._por_id.values())
        return novas

    def sincronizar_feed(self, rotas) -> tuple[list[Rota], list[Rota]]:
        """Substitui o conjunto de rotas vindas do feed pelos ids informados.

        As rotas do YAML não são tocadas. Retorna (novas, removidas): as que sumiram do feed
        (renomeadas ou recriadas no Partner Hub) saem do painel em vez de virar coluna vazia.
        """
        ids = {r.id for r in rotas}
        removidas = [r for r in self.rotas if r.waze_feed_id is not None and r.id not in ids]
        novas = [r for r in rotas if r.id not in self._por_id]
        self._por_id.update({r.id: r for r in rotas})
        for r in removidas:
            self._por_id.pop(r.id, None)
        self.rotas = tuple(self._por_id.values())
        return novas, removidas


def carregar_config(caminho: str | Path | None = None) -> Config:
    load_dotenv(RAIZ / ".env")
    caminho = Path(caminho or os.getenv("TUNEIS_CONFIG") or CONFIG_PADRAO)
    dados = yaml.safe_load(caminho.read_text(encoding="utf-8"))

    det_global = dados.get("deteccao") or {}
    rotas = []
    feed_rotas = dados.get("feed_rotas") or {}
    tuneis = dados["tuneis"] if feed_rotas.get("incluir_tuneis_yaml", True) else []
    for t in tuneis:
        det_tunel = {**det_global, **(t.get("deteccao") or {})}
        coords = tuple(tuple(c) for c in t["coords"])
        for r in t["rotas"]:
            waze_id = r.get("waze_route_id")
            rotas.append(
                Rota(
                    id=r["id"],
                    tunel_id=t["id"],
                    tunel_nome=t["nome"],
                    sentido=r["sentido"],
                    comprimento_m=float(r.get("comprimento_m", t["comprimento_m"])),
                    velocidade_max_kmh=float(t.get("velocidade_max_kmh", 60)),
                    coords=tuple(reversed(coords)) if r.get("invertido") else coords,
                    waze_route_id=str(waze_id) if waze_id is not None else None,
                    waze_nome=re.compile(r["waze_nome"]) if r.get("waze_nome") else None,
                    waze_rua=re.compile(rua, re.I) if (rua := r.get("waze_rua", t.get("waze_rua"))) else None,
                    pico_sim=r.get("pico_sim", "ambos"),
                    deteccao=ParametrosDeteccao(**{**det_tunel, **(r.get("deteccao") or {})}),
                )
            )

    coleta = dados.get("coleta") or {}
    db = Path(os.getenv("TUNEIS_DB") or coleta.get("db", "data/tuneis.db"))
    feeds = Path(os.getenv("TUNEIS_FEEDS") or coleta.get("pasta_feeds", "data/feeds"))
    return Config(
        rotas=tuple(rotas),
        intervalo_coleta_s=int(coleta.get("intervalo_s", 120)),
        dado_ausente_min=int(coleta.get("dado_ausente_min", 10)),
        db_path=db if db.is_absolute() else RAIZ / db,
        waze_feed_url=os.getenv("WAZE_TVT_FEED_URL") or None,
        webhook_url=os.getenv("ALERTA_WEBHOOK_URL") or None,
        pasta_feeds=feeds if feeds.is_absolute() else RAIZ / feeds,
        dias_feeds=int(coleta.get("dias_feeds", 7)),
        waze_feeds_extras=tuple(u for u in re.split(r"[,\s]+", os.getenv("WAZE_TVT_FEED_URL_EXTRA") or "") if u),
        feed_rotas=ParametrosFeedRotas(
            filtro_nome=re.compile(feed_rotas.get("filtro_nome", r"T[uú]nel"), re.I),
            velocidade_livre_kmh=float(feed_rotas.get("velocidade_livre_kmh", 60)),
            excluir=tuple(re.compile(p, re.I) for p in feed_rotas.get("excluir") or ()),
            agrupar=tuple(
                GrupoRota(nome=re.compile(g["nome"], re.I), tunel=g["tunel"], sentido=g.get("sentido"))
                for g in feed_rotas.get("agrupar") or ()
            ),
        ),
        deteccao_padrao=ParametrosDeteccao(**det_global),
    )
