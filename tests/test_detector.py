from datetime import date

from tuneis.calendario import DOMINGO_FERIADO, SABADO, UTIL, chave_temporal, tipo_dia
from tuneis.config import ParametrosDeteccao
from tuneis.detector import (
    ABRIR, ATENCAO, CRITICO, ENCERRAR, NORMAL, REF_FLUXO_LIVRE, REF_HISTORICO, REF_WAZE,
    Referencia, classificar, decidir_alerta, obter_referencia,
)
from tuneis.modelos import Baseline, Leitura

P = ParametrosDeteccao()
TS = 1_792_663_200  # 2026-10-22 (quinta) 07:00 em Brasília


def test_tipo_dia():
    assert tipo_dia(date(2026, 10, 22)) == UTIL
    assert tipo_dia(date(2026, 10, 24)) == SABADO
    assert tipo_dia(date(2026, 10, 25)) == DOMINGO_FERIADO
    assert tipo_dia(date(2026, 1, 20)) == DOMINGO_FERIADO  # São Sebastião
    assert tipo_dia(date(2026, 2, 17)) == DOMINGO_FERIADO  # terça de Carnaval
    assert tipo_dia(date(2026, 4, 23)) == DOMINGO_FERIADO  # São Jorge (estadual)


def test_chave_temporal_usa_horario_local():
    assert chave_temporal(TS) == (UTIL, 28)  # 07:00 -> slot 28


def test_classificacao():
    ref = Referencia(tempo_s=200, dispersao_s=20, fonte=REF_HISTORICO)
    assert classificar("r", TS, 220, ref, P).nivel == NORMAL
    assert classificar("r", TS, 300, ref, P).nivel == ATENCAO
    assert classificar("r", TS, 420, ref, P).nivel == CRITICO


def test_classificacao_exige_razao_e_z():
    # trecho muito volátil: 1,5x a referência ainda está dentro de 3 desvios
    volatil = Referencia(tempo_s=200, dispersao_s=60, fonte=REF_HISTORICO)
    assert classificar("r", TS, 300, volatil, P).nivel == NORMAL


def test_referencia_cai_para_waze_e_fluxo_livre(cfg):
    rota = cfg.rotas[0]
    leitura = Leitura(rota.id, TS, 300, historico_s=250, comprimento_m=None, jam_level=None, fonte="t")
    chave = (rota.id, *chave_temporal(TS))

    assert obter_referencia(rota, leitura, {chave: Baseline(240, 15, 100, 10)}).fonte == REF_HISTORICO
    assert obter_referencia(rota, leitura, {chave: Baseline(240, 15, 3, 1)}).fonte == REF_WAZE
    sem_hist = Leitura(rota.id, TS, 300, None, None, None, "t")
    ref = obter_referencia(rota, sem_hist, {})
    assert ref.fonte == REF_FLUXO_LIVRE and ref.tempo_s == rota.tempo_fluxo_livre_s


def test_histerese_do_alerta():
    assert decidir_alerta([NORMAL, NORMAL, ATENCAO], False, P) is None
    assert decidir_alerta([NORMAL, ATENCAO, CRITICO], False, P) == ABRIR
    assert decidir_alerta([ATENCAO, NORMAL, NORMAL], True, P) is None
    assert decidir_alerta([NORMAL, NORMAL, NORMAL], True, P) == ENCERRAR
