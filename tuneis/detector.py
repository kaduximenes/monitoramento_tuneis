"""Classificação de anomalias no tempo de travessia.

Para cada leitura obtemos uma referência (tempo "típico" para aquela rota, tipo de dia
e faixa de 15 min) e uma dispersão robusta. A leitura é anômala quando está, ao mesmo
tempo, X vezes acima da referência (razão) e Z desvios acima dela (z robusto). Exigir os
dois evita alarmes em trechos muito estáveis (z alto com poucos segundos de diferença) e
em trechos muito voláteis (razão alta dentro da variação normal).
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .calendario import chave_temporal
from .config import ParametrosDeteccao, Rota
from .modelos import Baseline, Leitura

NORMAL, ATENCAO, CRITICO = "NORMAL", "ATENCAO", "CRITICO"
SEM_DADOS = "SEM_DADOS"  # status de exibição (não é um nível de avaliação)
GRAVIDADE = {NORMAL: 0, ATENCAO: 1, CRITICO: 2}

ABRIR, ENCERRAR = "ABRIR", "ENCERRAR"

# Fontes de referência, em ordem de preferência
REF_HISTORICO, REF_WAZE, REF_FLUXO_LIVRE = "historico", "waze", "fluxo_livre"

FATOR_MAD = 1.4826  # MAD -> desvio-padrão equivalente sob normalidade


@dataclass(frozen=True)
class Referencia:
    tempo_s: float
    dispersao_s: float
    fonte: str
    amostras: int = 0


@dataclass(frozen=True)
class Avaliacao:
    rota_id: str
    ts: int
    tempo_s: float
    referencia_s: float
    dispersao_s: float
    fonte_ref: str
    razao: float
    z: float
    nivel: str
    interditado: bool = False


def _dispersao(referencia_s: float, mad_s: float, p: ParametrosDeteccao) -> float:
    return max(FATOR_MAD * mad_s, p.piso_dispersao_frac * referencia_s, p.piso_dispersao_s)


def obter_referencia(
    rota: Rota, leitura: Leitura, baselines: Mapping[tuple[str, str, int], Baseline]
) -> Referencia:
    """Histórico próprio do slot -> historicTime do Waze -> tempo de fluxo livre."""
    p = rota.deteccao
    b = baselines.get((rota.id, *chave_temporal(leitura.ts)))
    if b is not None and b.amostras >= p.min_amostras and b.dias >= p.min_dias:
        return Referencia(b.mediana_s, _dispersao(b.mediana_s, b.mad_s, p), REF_HISTORICO, b.amostras)
    if leitura.historico_s and leitura.historico_s > 0:
        return Referencia(leitura.historico_s, _dispersao(leitura.historico_s, 0, p), REF_WAZE)
    livre = rota.tempo_fluxo_livre_s
    return Referencia(livre, _dispersao(livre, 0, p), REF_FLUXO_LIVRE)


def classificar(
    rota_id: str, ts: int, tempo_s: float, ref: Referencia, p: ParametrosDeteccao, interditado: bool = False
) -> Avaliacao:
    """Interdição é sempre CRÍTICO. Sem histórico (referência = fluxo livre), só alerta
    se `alertar_sem_historico`: o pico normal já fica bem acima do fluxo livre."""
    razao = tempo_s / ref.tempo_s
    z = (tempo_s - ref.tempo_s) / ref.dispersao_s
    if interditado:
        nivel = CRITICO
    elif ref.fonte == REF_FLUXO_LIVRE and not p.alertar_sem_historico:
        nivel = NORMAL
    elif razao >= p.razao_critico and z >= p.z_critico:
        nivel = CRITICO
    elif razao >= p.razao_atencao and z >= p.z_atencao:
        nivel = ATENCAO
    else:
        nivel = NORMAL
    return Avaliacao(rota_id, ts, tempo_s, ref.tempo_s, ref.dispersao_s, ref.fonte, razao, z, nivel, interditado)


def decidir_alerta(niveis: Sequence[str], alerta_aberto: bool, p: ParametrosDeteccao) -> str | None:
    """Histerese do alerta. `niveis` vem em ordem cronológica (mais recente por último)."""
    if not alerta_aberto:
        ultimos = niveis[-p.leituras_para_abrir:]
        if len(ultimos) == p.leituras_para_abrir and all(n != NORMAL for n in ultimos):
            return ABRIR
        return None
    ultimos = niveis[-p.leituras_para_fechar:]
    if len(ultimos) == p.leituras_para_fechar and all(n == NORMAL for n in ultimos):
        return ENCERRAR
    return None
