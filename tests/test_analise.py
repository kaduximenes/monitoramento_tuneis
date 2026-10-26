import numpy as np
import pandas as pd

from tuneis import analise

TS = 1_792_663_200  # 2026-10-22 (qui) 07:00 em Brasília


def _leituras(cfg, rota_id, atrasos, interditado=None, inicio=TS, passo=120):
    livre = cfg.rota(rota_id).tempo_fluxo_livre_s
    n = len(atrasos)
    return pd.DataFrame({
        "rota_id": rota_id,
        "ts": inicio + np.arange(n) * passo,
        "tempo_s": livre + np.asarray(atrasos, dtype=float),
        "jam_level": 0,
        "interditado": interditado if interditado is not None else [0] * n,
    })


def test_preparar_hora_local_e_tipo_de_dia(cfg):
    df = analise.preparar(_leituras(cfg, "reboucas_lagoa", [0, 30]), cfg)
    assert df["hora"].tolist() == [7, 7]
    assert df["tipo_dia"].unique().tolist() == ["util"]
    assert df["atraso_s"].tolist() == [0, 30]


def test_preparar_descarta_rota_fora_da_config(cfg):
    bruto = pd.concat([_leituras(cfg, "reboucas_lagoa", [0]), _leituras(cfg, "reboucas_lagoa", [0]).assign(rota_id="antiga")])
    assert analise.preparar(bruto, cfg)["rota_id"].unique().tolist() == ["reboucas_lagoa"]


def test_resumo_separa_interdicao_dos_tempos(cfg):
    df = analise.preparar(_leituras(cfg, "reboucas_lagoa", [0, 60, 120, 0], interditado=[0, 0, 0, 1]), cfg)
    r = analise.resumo_rotas(df, cfg).set_index("rota_id").loc["reboucas_lagoa"]
    assert r.leituras == 4
    assert r.atraso_medio_s == 60
    assert r.frac_lento == 2 / 3
    assert r.min_interditado == cfg.intervalo_coleta_s / 60
    sem = analise.resumo_rotas(df, cfg).set_index("rota_id").loc["santa_barbara_laranjeiras"]
    assert sem.leituras == 0 and np.isnan(sem.atraso_medio_s)


def test_mapa_calor_e_perfil(cfg):
    df = analise.preparar(_leituras(cfg, "reboucas_lagoa", [0, 0, 300, 300], passo=30 * 60), cfg)
    calor = analise.mapa_calor(df, cfg)
    assert calor.shape == (len(cfg.rotas), 24)
    assert calor.loc["reboucas_lagoa", 7] == 0 and calor.loc["reboucas_lagoa", 8] == 300
    assert np.isnan(calor.loc["reboucas_lagoa", 9])
    perfil = analise.perfil_diario(df, "reboucas_lagoa")
    assert perfil["slot"].tolist() == [28, 30, 32, 34]
    assert (perfil["dias"] == 1).all()
