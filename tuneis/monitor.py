"""Pipeline por leitura: referência -> classificação -> ciclo de vida do alerta."""
from __future__ import annotations

import logging
import sqlite3
from collections.abc import Mapping

import requests

from . import storage
from .config import Config, Rota
from .detector import ABRIR, ENCERRAR, GRAVIDADE, Avaliacao, classificar, decidir_alerta, obter_referencia
from .modelos import Baseline, Leitura

log = logging.getLogger(__name__)


class Notificador:
    """Registra eventos de alerta no log e, se configurado, envia para um webhook (JSON)."""

    def __init__(self, webhook_url: str | None = None, sessao: requests.Session | None = None):
        self.webhook_url = webhook_url
        self.sessao = sessao or requests.Session()

    def enviar(self, evento: str, rota: Rota, alerta: dict, av: Avaliacao) -> None:
        texto = (
            f"[{evento}] {rota.nome}: {'INTERDITADO, ' if av.interditado else ''}{av.tempo_s / 60:.1f} min "
            f"(referência {av.referencia_s / 60:.1f} min, {av.razao:.1f}x) — nível {alerta['nivel_max']}"
        )
        log.warning(texto)
        if not self.webhook_url:
            return
        payload = {
            "evento": evento,
            "texto": texto,
            "alerta_id": alerta["id"],
            "rota_id": rota.id,
            "tunel": rota.tunel_nome,
            "sentido": rota.sentido,
            "nivel": alerta["nivel_max"],
            "inicio_ts": alerta["inicio_ts"],
            "fim_ts": alerta["fim_ts"],
            "tempo_s": av.tempo_s,
            "referencia_s": av.referencia_s,
            "razao": round(av.razao, 2),
            "interditado": av.interditado,
        }
        try:
            self.sessao.post(self.webhook_url, json=payload, timeout=10).raise_for_status()
        except requests.RequestException:
            log.exception("Falha ao enviar alerta para o webhook")


def processar_leitura(
    conn: sqlite3.Connection,
    cfg: Config,
    leitura: Leitura,
    baselines: Mapping[tuple[str, str, int], Baseline],
    notificador: Notificador | None = None,
) -> Avaliacao:
    rota = cfg.rota(leitura.rota_id)
    p = rota.deteccao
    ref = obter_referencia(rota, leitura, baselines)
    av = classificar(rota.id, leitura.ts, leitura.tempo_s, ref, p, leitura.interditado)
    storage.salvar_avaliacao(conn, av)

    recentes = storage.ultimas_avaliacoes(conn, rota.id, max(p.leituras_para_abrir, p.leituras_para_fechar))
    niveis = [n for _, n in recentes]
    aberto = storage.alerta_aberto(conn, rota.id)
    acao = decidir_alerta(niveis, aberto is not None, p)

    evento = alerta = None
    if acao == ABRIR:
        sequencia = recentes[-p.leituras_para_abrir:]
        nivel = max((n for _, n in sequencia), key=GRAVIDADE.__getitem__)
        alerta, evento = storage.abrir_alerta(conn, sequencia[0][0], nivel, av), "ABERTO"
    elif aberto is not None and acao == ENCERRAR:
        fim_ts = recentes[-p.leituras_para_fechar][0]  # primeira leitura normal da sequência
        alerta, evento = storage.encerrar_alerta(conn, aberto, fim_ts, av.ts), "ENCERRADO"
    elif aberto is not None:
        alerta = storage.atualizar_alerta(conn, aberto, av)
        if alerta["nivel_max"] != aberto["nivel_max"]:
            evento = "ESCALADO"

    if evento and notificador:
        notificador.enviar(evento, rota, alerta, av)
    return av
