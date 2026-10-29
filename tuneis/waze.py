"""Leitura dos feeds do Waze for Cities (Partner Hub). Dois formatos são aceitos:

Traffic View (rotas com tempo de travessia pronto):
    {"updateTime": <ms>, "routes": [{"id", "name", "time", "historicTime",
                                      "length", "jamLevel", "line": [{"x": lon, "y": lat}]}]}

Feed de trânsito (alertas + congestionamentos), o feed padrão de parceiros:
    {"endTimeMillis": <ms>, "jams": [{"street", "endNode", "delay", "level", "length",
                                       "speedKMH", "line": [...]}], "alerts": [...]}
Nesse caso o tempo de travessia é estimado: fluxo livre + atrasos ("delay", em segundos)
dos congestionamentos no túnel e na fila de acesso, no mesmo sentido da rota.

No feed de rotas, além das rotas vinculadas no YAML, entram sozinhas as rotas cujo `name`
casa com `feed_rotas.filtro_nome`. O nome segue o padrão "Rota: <túnel> - Sentido <destino>"
(ou "<via> - <destino>"); os sentidos do mesmo túnel viram um só trecho no painel.
"""
from __future__ import annotations

import logging
import math
import re
import sqlite3
import time
import unicodedata
from collections.abc import Mapping, Sequence

import requests

from . import storage
from .arquivo import arquivar
from .config import Config, Rota
from .modelos import Leitura, ResultadoColeta

log = logging.getLogger(__name__)

RAIO_TUNEL_M = 3000  # congestionamentos mais distantes que isso são de outra via homônima
NIVEL_INTERDICAO = 5
PREFIXO_FEED = "waze_"
_LETRA_SENTIDO = re.compile(r"\s+[NSLO](?=\s)")  # "BR-101 N Ponte" -> "BR-101 Ponte"
_PREFIXO_ROTA = re.compile(r"^Rota\s*[:\-]\s*", re.I)  # "Rota: Túnel Velho" -> "Túnel Velho"
_SENTIDO = re.compile(r"^Sentido\s+", re.I)          # "Sentido Copacabana" -> "Copacabana"
SENTIDO_UNICO = "sentido único"  # rota sem sentido no nome (túnel de mão única)
TUNEL_LONGO_M = 4000  # o maior túnel monitorado tem ~3,4 km: rota mais longa mede um corredor


def _distancia_m(lat0: float, lon0: float, lat1: float, lon1: float) -> float:
    dx = (lon1 - lon0) * math.cos(math.radians((lat0 + lat1) / 2))
    return math.hypot(dx, lat1 - lat0) * 111_320


def _perto(rota: Rota, pontos: Sequence[dict]) -> bool:
    return any(
        _distancia_m(p["y"], p["x"], lat, lon) <= RAIO_TUNEL_M for p in pontos for lat, lon in rota.coords
    )


def _mesmo_sentido(rota: Rota, dx: float, dy: float) -> bool:
    rx, ry = rota.rumo
    return rx * dx + ry * dy > 0


def _sentido_linha(rota: Rota, linha: Sequence[dict]) -> bool:
    ini, fim = linha[0], linha[-1]
    return _mesmo_sentido(rota, (fim["x"] - ini["x"]) * math.cos(math.radians(ini["y"])), fim["y"] - ini["y"])


def _sentido_alerta(rota: Rota, magvar) -> bool:
    if magvar is None:  # sem direção informada: vale para os dois sentidos
        return True
    rad = math.radians(float(magvar))  # 0 = norte, sentido horário
    return _mesmo_sentido(rota, math.sin(rad), math.cos(rad))


def _da_rota(rota: Rota, *nomes: str | None) -> bool:
    return any(n and rota.waze_rua.search(n) for n in nomes)


def parse_feed_trafego(feed: dict, rotas: Sequence[Rota]) -> ResultadoColeta:
    ts = int(feed.get("endTimeMillis") or time.time() * 1000) // 1000
    jams = feed.get("jams") or []
    alertas = feed.get("alerts") or []
    resultado = ResultadoColeta()

    for rota in rotas:
        if rota.waze_rua is None:
            resultado.ausentes.append(rota.id)
            continue
        atraso, nivel, interditado = 0.0, 0, False
        for j in jams:
            linha = j.get("line") or []
            # street = trecho dentro do túnel; endNode = fila no acesso, terminando na boca
            if (len(linha) < 2 or not _da_rota(rota, j.get("street"), j.get("endNode"))
                    or not _perto(rota, linha) or not _sentido_linha(rota, linha)):
                continue
            nivel = max(nivel, j.get("level") or 0)
            if j.get("level") == NIVEL_INTERDICAO or (j.get("delay") or 0) < 0:
                interditado = True
            else:
                atraso += j.get("delay") or 0
        for a in alertas:
            if (a.get("type") == "ROAD_CLOSED" and _da_rota(rota, a.get("street"))
                    and a.get("location") and _perto(rota, [a["location"]]) and _sentido_alerta(rota, a.get("magvar"))):
                interditado = True

        resultado.leituras.append(
            Leitura(
                rota_id=rota.id,
                ts=ts,
                tempo_s=rota.tempo_fluxo_livre_s + atraso,
                historico_s=None,
                comprimento_m=rota.comprimento_m,
                jam_level=nivel,
                fonte="waze",
                interditado=interditado,
            )
        )
        resultado.geometrias[rota.id] = list(rota.coords)
    return resultado


def _encontrar(rota: Rota, por_id: Mapping[str, dict], rotas_waze: Sequence[dict], ids: Mapping[str, str]):
    rid = ids.get(rota.id, rota.waze_route_id)
    if rid is not None:
        return por_id.get(str(rid))
    if rota.waze_nome is not None:
        return next((r for r in rotas_waze if rota.waze_nome.search(r.get("name") or "")), None)
    return None


def parse_feed(feed: dict, rotas: Sequence[Rota], ids: Mapping[str, str] | None = None, fonte: str = "waze") -> ResultadoColeta:
    """Converte o feed em leituras das rotas configuradas.

    `ids` sobrepõe o `waze_route_id` da configuração (usado pelo simulador).
    """
    ts = int(feed.get("updateTime") or time.time() * 1000) // 1000
    rotas_waze = feed.get("routes") or []
    por_id = {str(r.get("id")): r for r in rotas_waze}
    resultado = ResultadoColeta()

    for rota in rotas:
        rw = _encontrar(rota, por_id, rotas_waze, ids or {})
        tempo = rw.get("time") if rw else None
        if not tempo or tempo <= 0:
            resultado.ausentes.append(rota.id)
            continue
        resultado.leituras.append(
            Leitura(
                rota_id=rota.id,
                ts=ts,
                tempo_s=float(tempo),
                historico_s=float(rw["historicTime"]) if rw.get("historicTime") else None,
                comprimento_m=float(rw["length"]) if rw.get("length") else None,
                jam_level=rw.get("jamLevel"),
                fonte=fonte,
            )
        )
        if rw.get("line"):
            resultado.geometrias[rota.id] = [(p["y"], p["x"]) for p in rw["line"]]
    return resultado


def _slug(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", sem_acento.lower()).strip("_")


def _nome(rw: dict) -> str:
    return " ".join((rw.get("name") or "").split())


def rota_do_feed(rw: dict, cfg: Config) -> Rota:
    """Monta a rota monitorada a partir de uma rota do feed Traffic View."""
    nome = _PREFIXO_ROTA.sub("", _nome(rw))
    via, _, destino = nome.rpartition(" - ")
    destino = _SENTIDO.sub("", destino)
    if not via:  # sem sentido no nome: mão única
        via, destino = nome, SENTIDO_UNICO
    tunel = _LETRA_SENTIDO.sub("", via)
    grupo = cfg.feed_rotas.grupo(_nome(rw))
    if grupo is not None:  # nome fora do padrão: entra no túnel/sentido definidos na configuração
        tunel = grupo.tunel
        destino = grupo.sentido or destino
    return Rota(
        id=f"{PREFIXO_FEED}{rw['id']}",
        tunel_id=f"{PREFIXO_FEED}{_slug(tunel)}",
        tunel_nome=tunel,
        sentido=destino,
        comprimento_m=float(rw.get("length") or 0),
        velocidade_max_kmh=cfg.feed_rotas.velocidade_livre_kmh,
        coords=tuple((p["y"], p["x"]) for p in rw["line"]),
        waze_route_id=str(rw["id"]),
        waze_nome=None,
        waze_rua=None,
        pico_sim="ambos",
        deteccao=cfg.deteccao_padrao,
        waze_feed_id=str(rw["id"]),
    )


def rotas_do_feed(feed: dict, cfg: Config) -> list[dict]:
    """Rotas do feed que passam no filtro de nome e têm geometria."""
    return [
        rw for rw in feed.get("routes") or []
        if rw.get("id") is not None and len(rw.get("line") or []) >= 2
        and cfg.feed_rotas.aceita(_nome(rw))
    ]


def _resumo_rota(rw: dict) -> dict:
    """Atributos guardados para o painel: a rota inteira e os trechos sem a geometria."""
    return {**{k: v for k, v in rw.items() if k not in ("subRoutes", "bbox", "alternateRoute")},
            "subRoutes": [{k: v for k, v in sr.items() if k not in ("line", "bbox")} for sr in rw.get("subRoutes") or []]}


def problemas_cadastro(feed: dict, cfg: Config) -> list[dict]:
    """Rotas que passam no filtro de nome mas parecem mal cadastradas no Partner Hub."""
    rotas = [rw for rw in feed.get("routes") or [] if cfg.feed_rotas.aceita(_nome(rw))]
    out, percursos = [], {}
    for rw in rotas:
        nome, linha, extensao = _nome(rw), rw.get("line") or [], rw.get("length") or 0
        if len(linha) < 2 or not extensao or not rw.get("time"):
            out.append({"nome": nome, "problema": "rota vazia no feed (sem extensão ou sem tempo): fica fora do painel"})
            continue
        chave = (extensao, round(linha[0]["x"], 4), round(linha[0]["y"], 4), round(linha[-1]["x"], 4), round(linha[-1]["y"], 4))
        if chave in percursos:
            out.append({"nome": nome, "problema": f"mesmo percurso de “{percursos[chave]}”: os números repetem os dela"})
        else:
            percursos[chave] = nome
        if extensao > TUNEL_LONGO_M and re.search(r"t[uú]nel", nome, re.I):
            out.append({"nome": nome, "problema": f"rota de {extensao / 1000:.1f} km: mede um corredor, não só o túnel".replace(".", ",", 1)})
    return out


def alertas_da_rota(rw: dict) -> list[dict]:
    """Alertas do Waze na rota (`leadAlert` da rota e dos trechos), sem repetir o mesmo alerta."""
    vistos, out = set(), []
    for a in [rw.get("leadAlert"), *(sr.get("leadAlert") for sr in rw.get("subRoutes") or [])]:
        if a and a.get("id") not in vistos:
            vistos.add(a.get("id"))
            out.append(a)
    return out


def carregar_rotas_feed(conn: sqlite3.Connection, cfg: Config) -> list[Rota]:
    """Inclui na configuração as rotas do feed já vistas (as que ainda passam no filtro)."""
    rotas = [rota_do_feed(rw, cfg) for rw in storage.carregar_rotas_feed(conn).values()
             if cfg.feed_rotas.aceita(_nome(rw))]
    cfg.incluir(rotas)
    return rotas


class FonteWaze:
    nome = "waze"

    def __init__(self, cfg: Config, url: str | None = None, sessao: requests.Session | None = None):
        self.cfg = cfg
        self.urls = [url] if url else [u for u in (cfg.waze_feed_url, *cfg.waze_feeds_extras) if u]
        if not self.urls:
            raise ValueError("Defina WAZE_TVT_FEED_URL (no .env ou no ambiente) com a URL do feed do Waze")
        self.sessao = sessao or requests.Session()

    def baixar_feed(self, url: str | None = None) -> dict:
        resp = self.sessao.get(url or self.urls[0], timeout=30)
        resp.raise_for_status()
        return resp.json()

    def ler_feed(self, feed: dict) -> ResultadoColeta:
        """Feed de rotas: rotas vinculadas no YAML + as descobertas pelo nome. Feed de trânsito: rotas do YAML."""
        do_yaml = [r for r in self.cfg.rotas if r.waze_feed_id is None]
        if "routes" not in feed:
            return parse_feed_trafego(feed, [r for r in do_yaml if r.waze_rua is not None])
        descobertas = rotas_do_feed(feed, self.cfg)
        rotas = [rota_do_feed(rw, self.cfg) for rw in descobertas]
        for nova in self.cfg.incluir(rotas):
            log.info("Rota nova no feed: %s (id %s) -> %s", nova.nome, nova.waze_feed_id, nova.id)
        vinculadas = [r for r in do_yaml if r.waze_route_id is not None or r.waze_nome is not None]
        res = parse_feed(feed, vinculadas + rotas)
        res.rotas_feed = {f"{PREFIXO_FEED}{rw['id']}": _resumo_rota(rw) for rw in descobertas}
        return res

    def coletar(self, agora_ts: int | None = None) -> ResultadoColeta:
        resultado, falhas = ResultadoColeta(), []
        for url in self.urls:  # um feed fora do ar não derruba os outros
            try:
                feed = self.baixar_feed(url)
            except requests.RequestException as e:
                falhas.append(e)
                log.error("Falha ao consultar o feed %s: %s", url.split("?")[0], e)
                continue
            if self.cfg.pasta_feeds is not None:
                try:
                    arquivar(feed, url, self.cfg.pasta_feeds, self.cfg.dias_feeds)
                except OSError:
                    log.exception("Falha ao gravar o JSON do feed")
            res = self.ler_feed(feed)
            resultado.leituras += res.leituras
            resultado.geometrias.update(res.geometrias)
            resultado.ausentes += res.ausentes
            resultado.rotas_feed.update(res.rotas_feed)
        if len(falhas) == len(self.urls):
            raise falhas[0]
        return resultado
