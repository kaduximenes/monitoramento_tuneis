"""Painel de monitoramento dos túneis — streamlit run dashboard/app.py

Tela pensada para a sala de operação: uma faixa por túnel com o tempo atual de cada
sentido e o gráfico do dia (tempo real sobre o tempo típico). A visão "Análise" resume os
tempos de travessia de vários dias: ranking de atraso, mapa de calor por hora e perfil do dia.
As rotas do feed Traffic View aparecem também com todos os atributos que o Waze publica.
"""
from __future__ import annotations

import base64
import html
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pydeck as pdk  # noqa: E402
import streamlit as st  # noqa: E402

from tuneis import analise, consultas, storage  # noqa: E402
from tuneis.calendario import DOMINGO_FERIADO, SABADO, TZ, UTIL  # noqa: E402
from tuneis.config import carregar_config  # noqa: E402
from tuneis.detector import ATENCAO, CRITICO, NORMAL, REF_FLUXO_LIVRE, SEM_DADOS  # noqa: E402
from tuneis.arquivo import nome_feed  # noqa: E402
from tuneis.waze import SENTIDO_UNICO, alertas_da_rota, carregar_rotas_feed, problemas_cadastro  # noqa: E402

DESTAQUE_PCT = 0.20  # % sobre o típico a partir do qual a variação fica em destaque, mesmo em "Normal"
CALIBRANDO = "CALIBRANDO"  # sem histórico suficiente: não dá para dizer se está normal
INTERDITADO = "INTERDITADO"

# Status: cor sempre acompanhada do nome escrito (vermelho e verde se confundem em daltonismo)
COR = {NORMAL: "#0ca30c", ATENCAO: "#fab219", CRITICO: "#d03b3b", SEM_DADOS: "#8c8c8c",
       CALIBRANDO: "#7a8ea3", INTERDITADO: "#d03b3b"}
NOME_STATUS = {NORMAL: "Normal", ATENCAO: "Atenção", CRITICO: "Crítico", SEM_DADOS: "Sem dados",
               CALIBRANDO: "Calibrando", INTERDITADO: "Interditado"}
PRIORIDADE = {INTERDITADO: 5, CRITICO: 4, ATENCAO: 3, SEM_DADOS: 2, CALIBRANDO: 1, NORMAL: 0}

# Manual de Marca Prefeitura Rio 2025
AZUL_MARINHO, AZUL_CLARO, CINZA_MARCA = "#13335a", "#42b9eb", "#eceded"
COR_REAL, COR_TIPICO, COR_EXCESSO = AZUL_CLARO, CINZA_MARCA, AZUL_CLARO
FONTE = "'Cera Pro', Outfit, sans-serif"
DIAS = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]
# Mapa de calor do atraso: uma só matiz (azul da marca), mais claro = mais atraso.
# Rampa validada (ordinal, sobre o painel #13335a) com o validador de paletas do skill de dataviz.
FAIXAS_ATRASO = [(15, "rgba(236,237,237,.06)", "< 15 s"), (30, "#2a688f", "15–30 s"), (60, "#3590bd", "30 s–1 min"),
                 (120, "#42b9eb", "1–2 min"), (300, "#8fd5f3", "2–5 min"), (float("inf"), "#d4f0fb", "≥ 5 min")]
TIPOS_DIA = {"Todos os dias": None, "Dias úteis": UTIL, "Sábados": SABADO, "Domingos e feriados": DOMINGO_FERIADO}
MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
# Alertas do Waze (leadAlert das rotas): ícone ao lado do nome do túnel + descrição.
# Cor própria, violeta (não é status do túnel): forte para acidente e interdição, clara para o resto.
COR_AVISO_FORTE, COR_AVISO = "#ff5fd2", "#c9a0ff"
TIPO_ALERTA = {"ACCIDENT": "Acidente", "ROAD_CLOSED": "Via interditada", "HAZARD": "Perigo na via",
               "WEATHERHAZARD": "Perigo na via", "JAM": "Congestionamento", "CONSTRUCTION": "Obra",
               "MISC": "Alerta"}
SUBTIPO_ALERTA = {
    "ACCIDENT_MAJOR": "Acidente grave", "ACCIDENT_MINOR": "Acidente leve",
    "HAZARD_ON_ROAD_LANE_CLOSED": "Faixa interditada", "HAZARD_ON_ROAD_CAR_STOPPED": "Veículo parado na via",
    "HAZARD_ON_SHOULDER_CAR_STOPPED": "Veículo parado no acostamento", "HAZARD_ON_ROAD_CONSTRUCTION": "Obra na via",
    "HAZARD_ON_ROAD_OBJECT": "Objeto na via", "HAZARD_ON_ROAD_POT_HOLE": "Buraco na via",
    "HAZARD_ON_ROAD_ROAD_KILL": "Animal na via", "HAZARD_ON_ROAD_TRAFFIC_LIGHT_FAULT": "Semáforo com defeito",
    "HAZARD_ON_SHOULDER_ANIMALS": "Animais no acostamento", "HAZARD_ON_ROAD_EMERGENCY_VEHICLE": "Veículo de emergência",
    "HAZARD_WEATHER_FLOOD": "Alagamento", "HAZARD_WEATHER_FOG": "Neblina", "HAZARD_WEATHER_HEAVY_RAIN": "Chuva forte",
    "HAZARD_WEATHER_HAIL": "Granizo", "ROAD_CLOSED_EVENT": "Via interditada (evento)",
    "ROAD_CLOSED_CONSTRUCTION": "Via interditada (obra)", "ROAD_CLOSED_HAZARD": "Via interditada (perigo)",
    "JAM_STAND_STILL_TRAFFIC": "Trânsito parado", "JAM_HEAVY_TRAFFIC": "Trânsito intenso",
    "JAM_MODERATE_TRAFFIC": "Trânsito moderado",
}
_SVG = '<svg viewBox="0 0 16 16" width="{t}" height="{t}" aria-hidden="true">{d}</svg>'
ICONE_ALERTA = {  # formas diferentes por tipo, para não depender só da cor
    "ACCIDENT": '<path d="M8 .8l1.6 3.9 3.9-1.6-1.6 3.9 3.3 1-3.3 1 1.6 3.9-3.9-1.6L8 15.2l-1.6-3.9-3.9 1.6 1.6-3.9'
                '-3.3-1 3.3-1-1.6-3.9 3.9 1.6z" fill="currentColor"/>',
    "ROAD_CLOSED": '<circle cx="8" cy="8" r="7" fill="currentColor"/><rect x="3.5" y="6.8" width="9" height="2.4" '
                   'fill="#0c2340"/>',
    "CONSTRUCTION": '<path d="M6.6 1.5h2.8l4.6 12.5H2z" fill="currentColor"/><path d="M5.2 6.5h5.6M4 10h8" '
                    'stroke="#0c2340" stroke-width="1.4"/>',
    "AVISO": '<path d="M8 1l7.5 13.5H.5z" fill="currentColor"/><path d="M8 5.5v4.2" stroke="#0c2340" '
             'stroke-width="1.8" stroke-linecap="round"/><circle cx="8" cy="12" r="1" fill="#0c2340"/>',
}


def _icone_alerta(a: dict, tamanho: int = 16) -> str:
    tipo, sub = a.get("type") or "", a.get("subType") or ""
    chave = ("CONSTRUCTION" if tipo == "CONSTRUCTION" or "CONSTRUCTION" in sub
             else tipo if tipo in ("ACCIDENT", "ROAD_CLOSED") else "AVISO")
    cor = COR_AVISO_FORTE if tipo in ("ACCIDENT", "ROAD_CLOSED") else COR_AVISO
    # <img> em base64: o st.html remove <svg> embutido (mesmo recurso dos gráficos)
    svg = _SVG.format(t=tamanho, d=ICONE_ALERTA[chave]).replace("currentColor", cor)
    svg = svg.replace("<svg ", '<svg xmlns="http://www.w3.org/2000/svg" ', 1)
    imagem = base64.b64encode(svg.encode()).decode()
    return (f'<img class="ic" alt="{_esc(_rotulo_alerta(a))}" width="{tamanho}" height="{tamanho}" '
            f'src="data:image/svg+xml;base64,{imagem}"/>')


def _rotulo_alerta(a: dict) -> str:
    return SUBTIPO_ALERTA.get(a.get("subType") or "") or TIPO_ALERTA.get(a.get("type") or "", "Alerta")


# jamLevel do Waze (0 = livre ... 4 = parado), escrito junto com a cor
LENTIDAO = {0: ("livre", NORMAL), 1: ("leve", ATENCAO), 2: ("moderada", ATENCAO), 3: ("intensa", CRITICO),
            4: ("parado", CRITICO)}

st.set_page_config(page_title="Túneis · COR Rio", page_icon="🚇", layout="wide", initial_sidebar_state="collapsed")


@st.cache_resource
def _config():
    return carregar_config()


cfg = _config()


def _incluir_rotas_feed(conn) -> None:
    """Rotas do feed Traffic View já vistas pelo coletor entram na configuração do painel."""
    carregar_rotas_feed(conn, cfg)


def _tuneis() -> list[tuple[str, str]]:
    return list(dict.fromkeys((r.tunel_id, r.tunel_nome) for r in cfg.rotas))


_conn = storage.conectar(cfg.db_path)
try:
    _incluir_rotas_feed(_conn)
finally:
    _conn.close()

ESTILO = f"""
<style>
:root {{
  --fundo:#0c2340; --painel:{AZUL_MARINHO}; --linha:rgba(236,237,237,.10); --texto:{CINZA_MARCA};
  --mudo:#93a9c2; --real:{COR_REAL}; --tipico:{COR_TIPICO};
}}
[data-testid="stHeader"], [data-testid="stToolbar"], [data-testid="stDecoration"],
[data-testid="stSidebarCollapsedControl"] {{ display:none !important; }}
.block-container, [data-testid="stMainBlockContainer"] {{ padding:1.4rem 2.2rem 3rem !important; max-width:none !important; }}
.pcrj {{ font-family:{FONTE}; color:var(--texto); font-variant-numeric:tabular-nums; }}

.topo {{ display:flex; align-items:flex-end; justify-content:space-between; gap:32px; flex-wrap:wrap;
        border-bottom:3px solid var(--texto); padding-bottom:16px; }}
.voltar-painel {{ display:inline-flex; align-items:center; margin-bottom:10px; color:var(--real); font-size:.75rem;
                 font-weight:700; letter-spacing:.1em; text-transform:uppercase; text-decoration:none; }}
.voltar-painel:hover, .voltar-painel:focus-visible {{ color:var(--texto); text-decoration:underline; }}
.marca .pref {{ display:block; font-weight:500; font-size:.78rem; letter-spacing:.16em; color:var(--mudo); text-transform:uppercase; }}
.marca .titulo {{ font-weight:900; font-size:3.6rem; line-height:1; letter-spacing:-.01em; text-transform:uppercase;
                  margin-top:6px; }}
.marca .titulo span {{ color:var(--real); }}
.resumo {{ display:flex; gap:34px; flex-wrap:wrap; }}
.resumo-nota {{ font-size:.72rem; letter-spacing:.1em; color:var(--mudo); text-transform:uppercase; margin-top:8px; }}
.resumo .k b {{ display:block; font-size:2.6rem; font-weight:900; line-height:1; }}
.resumo .k span {{ display:flex; align-items:center; gap:6px; font-size:.7rem; letter-spacing:.14em; color:var(--mudo); text-transform:uppercase; }}
.resumo .k span i {{ width:9px; height:9px; display:inline-block; }}
.resumo .k.zero b {{ color:rgba(236,237,237,.28); }}
.relogio {{ text-align:right; }}
.relogio .hora {{ font-size:3.6rem; font-weight:900; line-height:.85; letter-spacing:-.03em; }}
.relogio .info {{ font-size:.72rem; letter-spacing:.12em; color:var(--mudo); text-transform:uppercase; margin-top:6px; }}
.vivo {{ color:var(--texto); font-weight:700; }}
.vivo::before {{ content:""; display:inline-block; width:8px; height:8px; border-radius:50%; background:#0ca30c;
                margin-right:6px; animation:pulso 1.6s ease-in-out infinite; vertical-align:1px; }}
@keyframes pulso {{ 0%,100% {{ opacity:1 }} 50% {{ opacity:.25 }} }}

.legenda {{ display:flex; gap:22px; flex-wrap:wrap; font-size:.72rem; letter-spacing:.08em; color:var(--mudo);
           text-transform:uppercase; margin:16px 0 10px; }}
.legenda.fixa {{ position:sticky; top:0; z-index:5; background:var(--fundo); margin:10px 0 0; padding:10px 0 8px;
                color:var(--texto); }}
.legenda i {{ display:inline-block; vertical-align:middle; margin-right:6px; }}
.legenda .l-real {{ width:22px; height:3px; background:var(--real); }}
.legenda .l-tip {{ width:22px; border-top:2px dashed var(--tipico); }}
.legenda .l-exc {{ width:14px; height:10px; background:{COR_EXCESSO}; opacity:.35; }}

.quadro {{ display:flex; flex-direction:column; gap:6px; }}
.tunel {{ display:grid; grid-template-columns:7px minmax(170px,230px) 160px 160px 1fr; background:var(--painel);
         min-height:104px; }}
.faixa {{ background:var(--cor); }}
.nome {{ padding:16px 18px 14px; }}
.nome .n1 {{ font-weight:900; font-size:1.45rem; line-height:.95; letter-spacing:-.025em; text-transform:uppercase; }}
.nome .n2 {{ font-size:.76rem; color:var(--mudo); margin-top:5px; }}
.nome .n1 .ic {{ display:inline-block; vertical-align:2px; margin-left:6px; }}
.nome .n1 .ic + .ic {{ margin-left:3px; }}
.avisos {{ margin-top:9px; display:flex; flex-direction:column; gap:4px; }}
.aviso {{ display:flex; align-items:flex-start; gap:6px; font-size:.72rem; line-height:1.25; cursor:help; }}
.aviso .ic {{ flex:none; margin-top:1px; }}
.aviso b {{ font-weight:700; }}
.aviso span {{ color:var(--mudo); }}
.tag {{ display:inline-flex; align-items:center; gap:7px; margin-top:12px; font-size:.72rem; font-weight:700;
       letter-spacing:.14em; text-transform:uppercase; }}
.tag i {{ width:9px; height:9px; background:var(--cor); display:inline-block; }}
.sentido {{ padding:14px 14px 12px; border-left:1px solid var(--linha); position:relative; }}
.sentido.ativo::after {{ content:""; position:absolute; left:0; right:0; bottom:0; height:3px; background:var(--real); }}
.sentido[data-rota] {{ cursor:pointer; }}
.sentido[data-rota]:hover, .sentido[data-rota]:focus-visible {{ background:rgba(236,237,237,.06); outline:none; }}
.tunel.compacto {{ min-height:0; }}
.tunel.compacto .nome {{ padding:10px 18px 8px; }}
.tunel.compacto .nome .n1 {{ font-size:1.1rem; }}
.tunel.compacto .nome .n2 {{ display:none; }}
.tunel.compacto .tag {{ margin-top:6px; }}
.tunel.compacto .sentido {{ padding:8px 14px 7px; }}
.tunel.compacto .sentido .dest {{ min-height:0; }}
.tunel.compacto .sentido .tempo {{ font-size:1.45rem; }}
.tunel.compacto .sentido .ref {{ display:none; }}
.tunel.compacto .graf {{ padding:6px 18px; justify-content:center; }}
.tunel.compacto .graf .eixo {{ display:none; }}
.tunel.compacto .plot {{ height:34px; }}
.graf .auto {{ display:none; margin-left:12px; color:var(--real); text-decoration:underline; cursor:pointer;
              text-transform:none; letter-spacing:0; }}
.tunel.fixado .graf .auto {{ display:inline; }}
.gs {{ display:none; flex-direction:column; flex:1; min-width:0; }}
.gs.on {{ display:flex; }}
.sentido .dest {{ font-size:.74rem; letter-spacing:.1em; color:var(--mudo); text-transform:uppercase; line-height:1.25;
                 min-height:1.7em; }}
.sentido .tempo {{ font-size:2.3rem; font-weight:900; line-height:1.05; letter-spacing:-.03em; }}
.sentido .delta {{ font-size:.8rem; font-weight:700; display:flex; align-items:center; gap:5px; }}
.sentido .delta i {{ width:0; height:0; border-left:5px solid transparent; border-right:5px solid transparent;
                    border-bottom:7px solid var(--cor); display:inline-block; }}
.sentido .delta.baixo i {{ border-bottom:none; border-top:7px solid var(--mudo); }}
.sentido .delta.neutro i {{ display:none; }}
.sentido .delta.cor {{ color:var(--cor); }}
.sentido .ref {{ font-size:.72rem; color:var(--mudo); margin-top:2px; }}
.sentido.unico {{ grid-column:span 2; }}
.sentido.vazio {{ display:flex; align-items:center; color:var(--mudo); font-size:.72rem; letter-spacing:.12em; text-transform:uppercase; }}
.fechado {{ font-size:1.25rem !important; color:#fff; background:{COR[CRITICO]}; display:inline-block; padding:2px 6px; margin:6px 0 4px; }}
.graf {{ padding:12px 18px 8px; border-left:1px solid var(--linha); display:flex; flex-direction:column; min-width:0; }}
.graf .esc {{ font-size:.74rem; color:var(--mudo); letter-spacing:.08em; display:flex; justify-content:space-between;
              gap:12px; flex-wrap:wrap; }}
.plot {{ position:relative; height:118px; margin:4px 0 3px; }}
.plot img {{ width:100%; height:100%; display:block; }}
.hov {{ position:absolute; inset:0; display:flex; }}
.hov span {{ flex:1; }}
.hov span[title]:hover {{ background:rgba(236,237,237,.10); }}
.graf .eixo {{ display:flex; justify-content:space-between; font-size:.74rem; color:var(--mudo); }}
.graf .semserie {{ flex:1; display:flex; align-items:center; color:var(--mudo); font-size:.75rem; }}

.ocorr {{ margin-top:34px; }}
.ocorr h2 {{ font-weight:900; font-size:1rem; letter-spacing:.16em; text-transform:uppercase; border-bottom:3px solid var(--texto);
            padding-bottom:8px; margin:0 0 4px; }}
.ev {{ display:grid; grid-template-columns:62px 7px minmax(200px,1.4fr) 110px 1fr 130px; gap:14px; align-items:center;
      padding:9px 0; border-bottom:1px solid var(--linha); font-size:.86rem; }}
.ev .h {{ font-weight:900; font-size:1.05rem; }}
.ev .c {{ align-self:stretch; background:var(--cor); }}
.ev .t b {{ text-transform:uppercase; letter-spacing:-.01em; }}
.ev .t span, .ev .m {{ color:var(--mudo); }}
.ev .s {{ font-size:.68rem; font-weight:700; letter-spacing:.14em; text-transform:uppercase; }}
.ev .d {{ text-align:right; }}
.ev .d.aberto {{ font-weight:700; }}
.nada {{ color:var(--mudo); font-size:.85rem; padding:12px 0; }}
.secao {{ margin-top:30px; }}
.secao h2 {{ font-weight:900; font-size:1rem; letter-spacing:.16em; text-transform:uppercase; border-bottom:3px solid var(--texto);
            padding-bottom:8px; margin:0 0 4px; display:flex; justify-content:space-between; align-items:baseline;
            gap:16px; flex-wrap:wrap; }}
.secao h2 small {{ font-weight:500; font-size:.68rem; letter-spacing:.1em; color:var(--mudo); }}
.secao .nota {{ font-size:.72rem; color:var(--mudo); margin-top:8px; line-height:1.5; }}
.rk {{ display:grid; grid-template-columns:minmax(190px,1.3fr) minmax(150px,2fr) repeat(5,82px); gap:14px; align-items:center;
      padding:8px 0; border-bottom:1px solid var(--linha); font-size:.86rem; }}
.rk.cab {{ font-size:.7rem; letter-spacing:.12em; color:var(--mudo); text-transform:uppercase; padding:10px 0 6px; }}
.rk .t b {{ text-transform:uppercase; letter-spacing:-.01em; }}
.rk .t span, .rk .zero {{ color:var(--mudo); }}
.rk .num {{ text-align:right; }}
.rk .barra {{ display:flex; align-items:center; gap:10px; }}
.rk .barra i {{ height:8px; background:var(--real); border-radius:0 4px 4px 0; display:block; }}
.rk .barra b {{ min-width:44px; }}
.calor {{ overflow-x:auto; padding-top:10px; }}
.calor .grade {{ display:grid; grid-template-columns:minmax(170px,220px) repeat(24,minmax(22px,1fr)); gap:2px; min-width:760px; }}
.calor .rot {{ font-size:.76rem; padding-right:10px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; align-self:center; }}
.calor .rot b {{ text-transform:uppercase; }}
.calor .c {{ height:24px; }}
.calor .c:hover {{ outline:2px solid var(--texto); outline-offset:-2px; }}
.calor .hh {{ font-size:.7rem; color:var(--mudo); text-align:center; padding-top:4px; }}
.escala {{ display:flex; gap:16px; flex-wrap:wrap; font-size:.68rem; color:var(--mudo); margin-top:10px; }}
.escala i {{ width:14px; height:10px; display:inline-block; vertical-align:middle; margin-right:5px; }}
.perfil {{ position:relative; height:230px; margin:14px 0 4px 44px; }}
.perfil img {{ width:100%; height:100%; display:block; }}
.perfil .yl {{ position:absolute; left:-44px; width:36px; text-align:right; font-size:.7rem; color:var(--mudo);
              transform:translateY(-50%); }}
.perfil-eixo {{ margin-left:44px; display:flex; justify-content:space-between; font-size:.7rem; color:var(--mudo); }}
.legenda .l-faixa {{ width:14px; height:10px; background:var(--real); opacity:.25; }}
.cad {{ display:grid; grid-template-columns:minmax(260px,1fr) 2fr; gap:14px; padding:8px 0;
       border-bottom:1px solid var(--linha); font-size:.86rem; }}
.cad span {{ color:var(--mudo); }}
.rw {{ border-bottom:1px solid var(--linha); }}
.rw summary {{ display:grid; grid-template-columns:minmax(230px,1.6fr) repeat(6,minmax(78px,1fr)); gap:14px;
              align-items:center; padding:10px 0; cursor:pointer; list-style:none; font-size:.86rem; }}
.rw summary::-webkit-details-marker {{ display:none; }}
.rw summary .t b {{ text-transform:uppercase; letter-spacing:-.01em; }}
.rw summary .t b::before {{ content:"▸"; display:inline-block; width:1em; color:var(--mudo); }}
.rw[open] summary .t b::before {{ content:"▾"; }}
.rw summary .t span, .rw .mudo {{ color:var(--mudo); }}
.rw .num {{ text-align:right; }}
.rw .cab {{ font-size:.7rem; letter-spacing:.12em; color:var(--mudo); text-transform:uppercase; }}
.rw .jam {{ display:inline-flex; align-items:center; gap:6px; justify-content:flex-end; }}
.rw .jam i {{ width:9px; height:9px; background:var(--cor); display:inline-block; }}
.rw .attrs {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(210px,1fr)); gap:4px 18px;
             font-size:.76rem; padding:2px 0 12px 1em; }}
.rw .attrs code {{ font-family:inherit; color:var(--mudo); }}
.rw .trechos {{ padding:0 0 14px 1em; }}
.rw .tr {{ display:grid; grid-template-columns:28px minmax(220px,2fr) repeat(5,minmax(70px,1fr)); gap:14px;
          align-items:center; padding:6px 0; border-top:1px solid var(--linha); font-size:.8rem; }}
.rw .tr.cab {{ border-top:none; padding-bottom:4px; font-size:.7rem; letter-spacing:.12em; color:var(--mudo); text-transform:uppercase; }}
.rw-cab .num {{ text-align:right; }}
.rw-cab {{ display:grid; grid-template-columns:minmax(230px,1.6fr) repeat(6,minmax(78px,1fr)); gap:14px;
              padding:10px 0 6px; font-size:.7rem; letter-spacing:.12em; color:var(--mudo); text-transform:uppercase; }}

.rodape {{ margin-top:22px; font-size:.7rem; color:var(--mudo); line-height:1.6; }}

@media (max-width: 980px) {{
  .tunel {{ grid-template-columns:7px 1fr 1fr; }}
  .faixa {{ grid-row:1 / span 3; grid-column:1; }}
  .nome, .graf {{ grid-column:2 / 4; }}
  .sentido {{ border-top:1px solid var(--linha); }}
  .sentido:nth-of-type(3) {{ border-left:none; }}
  .graf {{ border-left:none; border-top:1px solid var(--linha); }}
  .ev {{ grid-template-columns:52px 6px 1fr 90px; }}
  .ev .m, .ev .d {{ display:none; }}
  .rk {{ grid-template-columns:1fr 1fr 70px; }}
  .rk > :nth-child(n+4) {{ display:none; }}
  .rw summary, .rw-cab {{ grid-template-columns:1fr 70px 70px; }}
  .rw summary > :nth-child(n+4), .rw-cab > :nth-child(n+4) {{ display:none; }}
  .rw .tr {{ grid-template-columns:24px 1fr 60px 60px; }}
  .rw .tr > :nth-child(n+5) {{ display:none; }}
}}
</style>
"""


# Clique num sentido mostra o gráfico dele. A escolha fica no sessionStorage da aba e é
# reaplicada a cada atualização automática do quadro.
SCRIPT_SENTIDO = """
<script>
(() => {
  const CHAVE = "tuneis.sentido";
  let escolhas = {};
  try { escolhas = JSON.parse(sessionStorage.getItem(CHAVE) || "{}"); } catch (e) {}
  const salvar = () => { try { sessionStorage.setItem(CHAVE, JSON.stringify(escolhas)); } catch (e) {} };
  const mostrar = (tunel, rota) => {
    const alvo = tunel.querySelector('.gs[data-rota="' + rota + '"]');
    if (!alvo) return false;
    tunel.querySelectorAll(".gs").forEach(g => g.classList.toggle("on", g === alvo));
    tunel.querySelectorAll(".sentido[data-rota]").forEach(c => c.classList.toggle("ativo", c.dataset.rota === rota));
    tunel.classList.toggle("fixado", rota !== tunel.dataset.padrao);  // diferente do automático (pior sentido)
    return true;
  };
  const tecla = (el, fn) => el.addEventListener("keydown", ev => {
    if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); fn(ev); }
  });
  document.querySelectorAll(".tunel[data-tunel]").forEach(tunel => {
    const id = tunel.dataset.tunel;
    if (escolhas[id] && !mostrar(tunel, escolhas[id])) delete escolhas[id];
    tunel.querySelectorAll(".sentido[data-rota]").forEach(card => {
      const escolher = () => {
        if (!mostrar(tunel, card.dataset.rota)) return;
        if (card.dataset.rota === tunel.dataset.padrao) delete escolhas[id]; else escolhas[id] = card.dataset.rota;
        salvar();
      };
      card.addEventListener("click", escolher);
      tecla(card, escolher);
    });
    tunel.querySelectorAll(".auto").forEach(bt => {
      const voltar = ev => { ev.stopPropagation(); delete escolhas[id]; salvar(); mostrar(tunel, tunel.dataset.padrao); };
      bt.addEventListener("click", voltar);
      tecla(bt, voltar);
    });
  });
})();
</script>
"""


# --- formatação -----------------------------------------------------------------

def _mmss(segundos) -> str:
    if pd.isna(segundos):
        return "—"
    m, s = divmod(int(round(abs(segundos))), 60)
    return f"{m}:{s:02d}"


def _pct(x) -> str:
    if pd.isna(x):
        return "—"
    sinal = "+" if x > 0 else ("−" if x < 0 else "")
    return f"{sinal}{abs(x) * 100:.1f}%".replace(".", ",")


def _hhmm(ts) -> str:
    return datetime.fromtimestamp(int(ts), TZ).strftime("%H:%M") if pd.notna(ts) else "—"


def _nome_curto(nome: str) -> tuple[str, str]:
    """'Túnel Velho (Alaor Prata)' -> ('Velho', 'Alaor Prata')."""
    m = re.match(r"T[úu]nel (?:do |da |de |Prefeito )?(.*?)(?: \((.*)\))?$", nome)
    principal, sub = (m.group(1), m.group(2) or "") if m else (nome, "")
    return principal, sub


def _destino(sentido: str) -> str:
    return sentido.split("→")[-1].strip()


def _rotulo_sentido(sentido: str) -> str:
    return "mão única" if sentido == SENTIDO_UNICO else f"sentido {_destino(sentido)}"


def _esc(texto) -> str:
    return html.escape(str(texto))


# --- dados ------------------------------------------------------------------------

def _status(conn, agora: int) -> pd.DataFrame:
    df = consultas.status_atual(conn, cfg, agora)
    df.loc[(df["status"] == NORMAL) & (df["fonte_ref"] == REF_FLUXO_LIVRE), "status"] = CALIBRANDO
    df.loc[df["interditado"] == 1, "status"] = INTERDITADO
    df["prioridade"] = df["status"].map(PRIORIDADE)
    return df


# --- gráfico (SVG) ----------------------------------------------------------------

def _segmentos(s: pd.DataFrame, lacuna_s: int = 600):
    """Quebra a série onde faltam leituras, para não ligar pontos distantes com uma reta."""
    quebra = [0, *(np.flatnonzero(np.diff(s["ts"].to_numpy()) > lacuna_s) + 1), len(s)]
    return [s.iloc[a:b] for a, b in zip(quebra, quebra[1:])]


def _svg(s: pd.DataFrame, desde: int, agora: int, y_min: float, y_max: float) -> str:
    W, H = 1000, 100
    span = max(agora - desde, 1)

    def X(ts):
        return (np.asarray(ts, dtype=float) - desde) / span * W

    def Y(minutos):
        return H - 3 - (np.asarray(minutos, dtype=float) - y_min) / (y_max - y_min) * (H - 8)

    def pts(xs, ys):
        return " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))

    partes = []
    for seg in _segmentos(s):
        xs = X(seg["ts"])
        real, tip = seg["tempo_s"].to_numpy() / 60, seg["referencia_s"].to_numpy() / 60
        topo = np.maximum(real, tip)
        poligono = pts(xs, Y(topo)) + " " + pts(xs[::-1], Y(tip)[::-1])
        partes.append(f'<polygon points="{poligono}" fill="{COR_EXCESSO}" opacity=".22"/>')
        partes.append(f'<polyline points="{pts(xs, Y(tip))}" fill="none" stroke="{COR_TIPICO}" stroke-width="1.5" '
                      'stroke-dasharray="5 4" vector-effect="non-scaling-stroke" opacity=".75"/>')
        partes.append(f'<polyline points="{pts(xs, Y(real))}" fill="none" stroke="{COR_REAL}" stroke-width="2.4" '
                      'stroke-linejoin="round" vector-effect="non-scaling-stroke"/>')

    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" preserveAspectRatio="none">'
           f'{"".join(partes)}</svg>')
    imagem = base64.b64encode(svg.encode()).decode()

    # camada de dicas ao passar o mouse: uma faixa por intervalo, com a última leitura dele
    ts = s["ts"].to_numpy()
    faixas = []
    for i in range(72):
        b0, b1 = desde + span * i / 72, desde + span * (i + 1) / 72
        j = np.searchsorted(ts, b1) - 1
        if j < 0 or ts[j] < b0:
            faixas.append("<span></span>")
            continue
        r = s.iloc[j]
        dica = f"{_hhmm(r.ts)} · real {_mmss(r.tempo_s)} · típico {_mmss(r.referencia_s)}"
        faixas.append(f'<span title="{_esc(dica)}"></span>')
    return (f'<div class="plot"><img alt="" src="data:image/svg+xml;base64,{imagem}"/>'
            f'<div class="hov">{"".join(faixas)}</div></div>')


def _faixa_y(menor_min: float, maior_min: float) -> tuple[float, float]:
    """Escala vertical justa aos valores (não começa em zero), em passos redondos de tempo."""
    folga = max((maior_min - menor_min) * 0.15, maior_min * 0.05, 0.05)
    lo, hi = max(menor_min - folga, 0), maior_min + folga
    passo = next(p for p in (0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 15, 30, 60) if (hi - lo) / p <= 4)
    return float(np.floor(lo / passo) * passo), float(np.ceil(hi / passo) * passo)


def _escala(y_max: float) -> float:
    for passo in (1, 2, 3, 5, 10, 15, 20, 30, 45, 60):
        if y_max <= passo:
            return float(passo)
    return float(np.ceil(y_max / 30) * 30)


# --- blocos HTML -----------------------------------------------------------------

def _html_topo(status: pd.DataFrame, agora: int) -> str:
    agora_dt = datetime.fromtimestamp(agora, TZ)
    por_tunel = status.sort_values("prioridade", ascending=False).drop_duplicates("tunel")  # pior sentido
    contagem = por_tunel["status"].value_counts()
    ultima = status["ts"].max()
    idade = "sem leitura" if pd.isna(ultima) else (
        "waze agora" if agora - ultima < 90 else f"waze há {int((agora - ultima) // 60)} min")
    itens = []
    for chave in (CRITICO, ATENCAO, CALIBRANDO, SEM_DADOS, NORMAL):
        n = int(contagem.get(chave, 0)) + (int(contagem.get(INTERDITADO, 0)) if chave == CRITICO else 0)
        itens.append(f'<div class="k{" zero" if n == 0 else ""}"><b>{n}</b>'
                     f'<span><i style="background:{COR[chave]}"></i>{NOME_STATUS[chave]}</span></div>')
    return (
        '<div class="pcrj"><div class="topo">'
        '<div class="marca"><a class="voltar-painel" href="https://painel-cor.netlify.app/" '
        'aria-label="Voltar ao painel de projetos COR">← Voltar ao painel</a>'
        '<span class="pref">Prefeitura Rio · Centro de Operações</span>'
        '<div class="titulo">Túneis<span>.</span></div></div>'
        f'<div class="resumo-bloco"><div class="resumo">{"".join(itens)}</div>'
        f'<div class="resumo-nota">{len(por_tunel)} túneis e ponte · status do pior sentido · '
        f'{len(status)} sentidos</div></div>'
        f'<div class="relogio"><div class="hora">{agora_dt:%H:%M}</div>'
        f'<div class="info"><span class="vivo">ao vivo</span> · {DIAS[agora_dt.weekday()]} {agora_dt.day} '
        f'{MESES[agora_dt.month - 1]} · {idade}</div></div>'
        "</div></div>"
    )


def _html_sentido(r, ativo: bool, clicavel: bool) -> str:
    cls = "sentido ativo" if ativo else "sentido"
    if clicavel:  # vira atributos extras no mesmo class="..."
        cls += f'" data-rota="{_esc(r.rota_id)}" role="button" tabindex="0" title="ver o gráfico deste sentido'
    if r.sentido == SENTIDO_UNICO:
        dest = '<div class="dest">mão única</div>'
    else:
        dest = f'<div class="dest">→ {_esc(_destino(r.sentido))}</div>'
    if pd.isna(r.tempo_s):
        return f'<div class="{cls}">{dest}<div class="tempo">—</div><div class="ref">sem leituras</div></div>'
    rotulo_ref = "livre" if r.fonte_ref == REF_FLUXO_LIVRE else "típico"
    ref = f'<div class="ref">{rotulo_ref} {_mmss(r.referencia_s)}</div>'
    if r.status == INTERDITADO:
        return f'<div class="{cls}">{dest}<div class="tempo fechado">Interditado</div>{ref}</div>'
    if r.status == SEM_DADOS:
        return (f'<div class="{cls}">{dest}<div class="tempo">{_mmss(r.tempo_s)}</div>'
                f'<div class="ref">última leitura {_hhmm(r.ts)}</div></div>')
    dif = r.tempo_s - r.referencia_s
    sentido_delta = "neutro" if abs(dif) < 15 else ("alto" if dif > 0 else "baixo")
    var = r.tempo_s / r.referencia_s - 1 if r.referencia_s else np.nan
    if r.status in (ATENCAO, CRITICO):
        cor_delta, destaque = COR[r.status], " cor"
    elif var >= DESTAQUE_PCT:  # ainda abaixo do limiar de alerta, mas bem acima do típico
        cor_delta, destaque = COR[ATENCAO], " cor"
    else:
        cor_delta, destaque = "var(--mudo)", ""
    sinal = "+" if dif >= 0 else "−"
    return (f'<div class="{cls}" style="--cor:{cor_delta}">{dest}<div class="tempo">{_mmss(r.tempo_s)}</div>'
            f'<div class="delta {sentido_delta}{destaque}"><i></i>{sinal}{_mmss(dif)} · {_pct(var)}</div>{ref}</div>')


def _avisos_por_tunel(conn, agora: int) -> dict[str, list[tuple[str, dict]]]:
    """tunel_id -> [(sentido, alerta)] dos alertas do Waze na leitura mais recente de cada rota."""
    rotas = {r.id: r for r in cfg.rotas}
    out: dict[str, list[tuple[str, dict]]] = {}
    for rota_id, rw in storage.carregar_rotas_feed(conn).items():
        rota = rotas.get(rota_id)
        if rota is None or agora - (rw.get("_visto_ts") or 0) > cfg.dado_ausente_min * 60:
            continue  # rota fora do painel ou sem leitura recente: o alerta pode já ter acabado
        out.setdefault(rota.tunel_id, []).extend((rota.sentido, a) for a in alertas_da_rota(rw))
    return out


def _html_avisos(avisos: list[tuple[str, dict]], mostrar: int = 3) -> tuple[str, str]:
    """(ícones para o lado do nome, lista de descrições). Mesmo alerta em dois sentidos aparece uma vez."""
    por_id: dict[str, tuple[list[str], dict]] = {}
    for sentido, a in avisos:
        sentidos, _ = por_id.setdefault(a.get("id") or id(a), ([], a))
        if sentido not in sentidos:
            sentidos.append(sentido)
    itens = sorted(por_id.values(), key=lambda v: v[1].get("type") not in ("ACCIDENT", "ROAD_CLOSED"))
    if not itens:
        return "", ""
    icones = "".join(_icone_alerta(a, 18) for _, a in itens[:mostrar])
    linhas = []
    for sentidos, a in itens[:mostrar]:
        onde = " · ".join(f"→ {_destino(x)}" for x in sentidos)
        dica = (f"Alerta do Waze: {_rotulo_alerta(a)} · {a.get('street') or 'via não informada'} · sentido {onde} · "
                f"{a.get('numThumbsUp', 0)} confirmação(ões), {a.get('numNotThereReports', 0)} “não está lá”"
                f" · posição {a.get('position', '?')}")
        linhas.append(f'<div class="aviso" title="{_esc(dica)}">{_icone_alerta(a)}<div><b>{_esc(_rotulo_alerta(a))}</b> '
                      f'<span>{_esc(onde)}</span></div></div>')
    if len(itens) > mostrar:
        linhas.append(f'<div class="aviso"><span>+{len(itens) - mostrar} alerta(s) do Waze</span></div>')
    return icones, f'<div class="avisos">{"".join(linhas)}</div>'


def _tem_problema(rotas: pd.DataFrame, alertas: dict, avisos) -> bool:
    """Problema = status fora do normal, alerta na janela, alerta do Waze ou % em destaque."""
    if rotas["status"].isin([ATENCAO, CRITICO, INTERDITADO, SEM_DADOS]).any() or avisos:
        return True
    if any(r in alertas for r in rotas["rota_id"]):
        return True
    return bool((rotas["tempo_s"] / rotas["referencia_s"] - 1 >= DESTAQUE_PCT).any())


def _grafico(r, series: dict, desde: int, agora: int) -> str:
    s = series.get(r.rota_id)
    if s is None or s.empty:
        return '<div class="semserie">sem leituras na janela</div>'
    inicio = max(desde, int(s["ts"].min()))  # coleta mais curta que a janela: eixo começa na 1ª leitura
    valores = s[["tempo_s", "referencia_s"]].to_numpy() / 60
    y_min, y_max = _faixa_y(valores.min(), valores.max())
    meio = datetime.fromtimestamp((inicio + agora) // 2, TZ)
    titulo = "gráfico" if r.sentido == SENTIDO_UNICO else f"gráfico: → {_esc(_destino(r.sentido))}"
    return (
        f'<div class="esc"><span>{titulo}<span class="auto" role="button" tabindex="0">fixado · voltar ao automático</span></span>'
        f'<span>escala {_mmss(y_min * 60)} a {_mmss(y_max * 60)}</span></div>'
        + _svg(s, inicio, agora, y_min, y_max)
        + f'<div class="eixo"><span>{_hhmm(inicio)}</span><span>{meio:%H:%M}</span><span>agora</span></div>'
    )


def _html_tunel(tunel_id: str, tunel_nome: str, rotas: pd.DataFrame, series: dict,
                desde: int, agora: int, avisos: list[tuple[str, dict]] | None = None, compacto: bool = False) -> str:
    pior = rotas.sort_values(["prioridade", "razao"], ascending=False).iloc[0]
    principal, sub = _nome_curto(tunel_nome)
    varios = len(rotas) > 1
    sentidos = [_html_sentido(r, r.rota_id == pior.rota_id and varios, varios) for r in rotas.itertuples()]
    if not varios:  # um cartão só, ocupando as duas colunas de sentido
        sentidos = [sentidos[0].replace('class="sentido', 'class="sentido unico', 1)]
    graficos = "".join(
        f'<div class="gs{" on" if r.rota_id == pior.rota_id else ""}" data-rota="{_esc(r.rota_id)}">'
        f"{_grafico(r, series, desde, agora)}</div>"
        for r in rotas.itertuples()
    )
    icones, lista_avisos = _html_avisos(avisos or [])
    return (
        f'<div class="tunel{" compacto" if compacto else ""}" data-tunel="{_esc(tunel_id)}" '
        f'data-padrao="{_esc(pior.rota_id)}" style="--cor:{COR[pior.status]}"><div class="faixa"></div>'
        f'<div class="nome"><div class="n1">{_esc(principal)}{icones}</div><div class="n2">{_esc(sub)}</div>'
        f'<div class="tag"><i></i>{NOME_STATUS[pior.status]}</div>{lista_avisos}</div>'
        f'{"".join(sentidos)}<div class="graf">{graficos}</div></div>'
    )


def _html_ocorrencias(conn, agora: int) -> str:
    df = consultas.alertas(conn, agora - 24 * 3600)
    df = df[df["rota_id"].isin([r.id for r in cfg.rotas])]
    if df.empty:
        corpo = '<div class="nada">Nenhuma ocorrência nas últimas 24 horas.</div>'
    else:
        linhas = []
        rotas = {r.id: r for r in cfg.rotas}
        for a in df.itertuples():
            rota = rotas.get(a.rota_id)
            if rota is None:
                continue
            aberto = pd.isna(a.fim_ts)
            minutos = int(((agora if aberto else a.fim_ts) - a.inicio_ts) // 60)
            duracao = f"em aberto · {minutos} min" if aberto else f"encerrado · {minutos} min"
            linhas.append(
                f'<div class="ev" style="--cor:{COR[a.nivel_max]}"><div class="h">{_hhmm(a.inicio_ts)}</div><div class="c"></div>'
                f'<div class="t"><b>{_esc(_nome_curto(rota.tunel_nome)[0])}</b> <span>{_esc(_rotulo_sentido(rota.sentido))}</span></div>'
                f'<div class="s">{NOME_STATUS[a.nivel_max]}</div>'
                f'<div class="m">pico {_mmss(a.tempo_max_s)} · típico {_mmss(a.referencia_s)} · {a.razao_max:.1f}×</div>'
                f'<div class="d{" aberto" if aberto else ""}">{duracao}</div></div>'
            )
        corpo = "".join(linhas)
    return f'<div class="pcrj ocorr"><h2>Ocorrências · 24 h</h2>{corpo}</div>'


def _html_jam(nivel) -> str:
    if pd.isna(nivel):
        return '<span class="mudo">—</span>'
    nome, status = LENTIDAO.get(int(nivel), (str(nivel), SEM_DADOS))
    return f'<span class="jam" style="--cor:{COR[status]}"><i></i>{int(nivel)} · {nome}</span>'


def _km(metros) -> str:
    return "—" if not metros else f"{metros / 1000:.1f} km".replace(".", ",")


def _kmh(metros, segundos) -> str:
    return "—" if not metros or not segundos else f"{metros / segundos * 3.6:.0f} km/h"


def _de_para(de, para) -> str:
    return f"{_esc(de or '—')} <span class='mudo'>→</span> {_esc(para or '—')}"


def _html_cadastro() -> str:
    """Rotas que parecem mal cadastradas no Partner Hub, a partir do último JSON de cada feed."""
    if cfg.pasta_feeds is None:
        return ""
    linhas = []
    for url in (cfg.waze_feed_url, *cfg.waze_feeds_extras):
        arq = cfg.pasta_feeds / nome_feed(url or "") / "ultimo.json"
        if not url or not arq.exists():
            continue
        try:
            feed = json.loads(arq.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        linhas += [f'<div class="cad"><b>{_esc(p["nome"])}</b><span>{_esc(p["problema"])}</span></div>'
                   for p in problemas_cadastro(feed, cfg)]
    corpo = "".join(linhas) or '<div class="nada">Nenhum problema encontrado nas rotas do painel.</div>'
    return ('<div class="pcrj secao"><h2>Cadastro das rotas no Waze<small>confira e corrija no Partner Hub</small></h2>'
            f"{corpo}<div class=\"nota\">Verificado no último JSON de cada feed (data/feeds). Rota vazia não aparece no "
            "painel; rota com o mesmo percurso de outra mostra os números da outra; rota longa mede também o trânsito "
            "fora do túnel.</div></div>")


def _html_rotas_feed(conn) -> str:
    """Todas as rotas do feed Traffic View que estão no painel, com os atributos e os trechos (subRoutes)."""
    ids = {r.id for r in cfg.rotas if r.waze_feed_id}
    rotas = {k: v for k, v in storage.carregar_rotas_feed(conn).items() if k in ids}
    if not rotas:
        return ""
    cab = ('<div class="rw-cab"><span>Rota (name) · id</span><span class="num">time</span><span class="num">historicTime</span>'
           '<span class="num">diferença</span><span class="num">jamLevel</span><span class="num">length</span>'
           '<span class="num">vel. média</span></div>')
    blocos = []
    for rota_id, rw in rotas.items():
        tempo, hist = rw.get("time"), rw.get("historicTime")
        dif = (tempo - hist) if tempo and hist else None
        sinal = "" if dif is None else ("+" if dif >= 0 else "−")
        resumo = (
            f'<summary><div class="t"><b>{_esc((rw.get("name") or "").strip())}</b> <span>id {_esc(rw.get("id"))}</span></div>'
            f'<div class="num">{_mmss(tempo)}</div><div class="num">{_mmss(hist)}</div>'
            f'<div class="num">{sinal}{_mmss(dif)}</div><div class="num">{_html_jam(rw.get("jamLevel"))}</div>'
            f'<div class="num">{_km(rw.get("length"))}</div><div class="num">{_kmh(rw.get("length"), tempo)}</div></summary>'
        )
        atributos = [("id", rw.get("id")), ("type", rw.get("type")), ("fromName", rw.get("fromName") or "—"),
                     ("toName", rw.get("toName") or "—"), ("length", f'{rw.get("length")} m'),
                     ("time", f"{tempo} s"), ("historicTime", f"{hist} s"), ("jamLevel", rw.get("jamLevel")),
                     ("line", f'{len(rw.get("line") or [])} pontos'), ("subRoutes", f'{len(rw.get("subRoutes") or [])} trechos'),
                     ("atualizado", _hhmm(rw.get("_visto_ts")))]
        attrs = "".join(f"<div><code>{k}</code> {_esc(v)}</div>" for k, v in atributos)
        linhas = ['<div class="tr cab"><span>#</span><span>fromName → toName</span><span class="num">length</span>'
                  '<span class="num">time</span><span class="num">historicTime</span><span class="num">jamLevel</span>'
                  '<span class="num">vel. média</span></div>']
        for i, sr in enumerate(rw.get("subRoutes") or []):
            linhas.append(
                f'<div class="tr"><span class="mudo">{i + 1}</span><span>{_de_para(sr.get("fromName"), sr.get("toName"))}</span>'
                f'<span class="num">{_km(sr.get("length"))}</span><span class="num">{_mmss(sr.get("time"))}</span>'
                f'<span class="num">{_mmss(sr.get("historicTime"))}</span><span class="num">{_html_jam(sr.get("jamLevel"))}</span>'
                f'<span class="num">{_kmh(sr.get("length"), sr.get("time"))}</span></div>'
            )
        blocos.append(f'<details class="rw">{resumo}<div class="attrs">{attrs}</div>'
                      f'<div class="trechos">{"".join(linhas)}</div></details>')
    ultima = max(rw.get("_visto_ts") or 0 for rw in rotas.values())
    return (f'<div class="pcrj secao"><h2>Rotas do Waze · Traffic View<small>leitura das {_hhmm(ultima)} · '
            f'clique numa rota para ver os trechos</small></h2>{cab}{"".join(blocos)}'
            '<div class="nota">Tempos em min:s. time = tempo atual; historicTime = tempo típico do Waze para o horário; '
            "jamLevel = lentidão (0 livre a 4 parado); vel. média = length / time.</div></div>")


# --- análise ----------------------------------------------------------------------

def _rotulo(rota_id: str) -> str:
    rota = cfg.rota(rota_id)
    return f"{_nome_curto(rota.tunel_nome)[0]} → {_destino(rota.sentido)}"


def _html_ranking(resumo: pd.DataFrame) -> str:
    df = resumo.sort_values("atraso_medio_s", ascending=False, na_position="last")
    escala = max(df["atraso_medio_s"].max(), 1) if df["atraso_medio_s"].notna().any() else 1
    linhas = ['<div class="rk cab"><span>Túnel · sentido</span><span>Atraso médio</span><span class="num">Mediana</span>'
              '<span class="num">P90</span><span class="num">Máximo</span><span class="num">Lento</span>'
              '<span class="num">Interditado</span></div>']
    for r in df.itertuples():
        nome = f'<div class="t"><b>{_esc(_nome_curto(r.tunel)[0])}</b> <span>→ {_esc(_destino(r.sentido))}</span></div>'
        if pd.isna(r.atraso_medio_s):
            vazio = "sem leituras no período" if r.leituras == 0 else "só leituras interditado"
            linhas.append(f'<div class="rk">{nome}<div class="zero">{vazio}</div></div>')
            continue
        largura = r.atraso_medio_s / escala * 100
        barra = f'<i style="width:{largura:.1f}%"></i>' if largura >= 0.5 else ""
        interd = f"{r.min_interditado:.0f} min" if r.min_interditado else '<span class="zero">—</span>'
        linhas.append(
            f'<div class="rk">{nome}<div class="barra"><b>{_mmss(r.atraso_medio_s)}</b>{barra}</div>'
            f'<div class="num">{_mmss(r.mediana_s)}</div><div class="num">{_mmss(r.p90_s)}</div>'
            f'<div class="num">{_mmss(r.max_s)}</div><div class="num">{r.frac_lento:.0%}</div>'
            f'<div class="num">{interd}</div></div>'
        )
    return "".join(linhas)


def _cor_atraso(segundos: float) -> str:
    return next(cor for limite, cor, _ in FAIXAS_ATRASO if segundos < limite)


def _html_calor(tabela: pd.DataFrame) -> str:
    celulas = []
    for rota_id, linha in tabela.iterrows():
        rotulo = _rotulo(rota_id)
        principal, _, destino = rotulo.partition(" → ")
        celulas.append(f'<div class="rot" title="{_esc(rotulo)}"><b>{_esc(principal)}</b> → {_esc(destino)}</div>')
        for hora, valor in linha.items():
            if pd.isna(valor):
                celulas.append(f'<div class="c" title="{_esc(rotulo)} · {hora}h · sem leituras"></div>')
            else:
                dica = f"{rotulo} · {hora}h–{hora + 1}h · atraso médio {_mmss(valor)}"
                celulas.append(f'<div class="c" style="background:{_cor_atraso(valor)}" title="{_esc(dica)}"></div>')
    celulas.append("<div></div>")
    celulas += [f'<div class="hh">{h if h % 3 == 0 else ""}</div>' for h in range(24)]
    escala = "".join(f'<span><i style="background:{cor}"></i>{nome}</span>' for _, cor, nome in FAIXAS_ATRASO)
    return (f'<div class="calor"><div class="grade">{"".join(celulas)}</div></div>'
            f'<div class="escala"><span>atraso médio:</span>{escala}<span>vazio = sem leituras</span></div>')


def _html_perfil(perfil: pd.DataFrame, livre_s: float) -> str:
    if perfil.empty:
        return '<div class="nada">Sem leituras deste sentido no período.</div>'
    W, H = 1000, 230
    y_max = _escala(max(perfil["p90_s"].max(), livre_s) * 1.15 / 60)

    def X(slot):
        return (np.asarray(slot, dtype=float) + 0.5) / 96 * W

    def Y(segundos):
        return H - np.asarray(segundos, dtype=float) / 60 / y_max * H

    def pts(xs, ys):
        return " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))

    def linha_h(segundos, estilo):
        y = float(Y(segundos))
        return f'<line x1="0" x2="{W}" y1="{y:.1f}" y2="{y:.1f}" {estilo} vector-effect="non-scaling-stroke"/>'

    passo = next(p for p in (0.5, 1, 2, 5, 10, 15, 30, 60) if y_max / p <= 5)
    marcas = np.arange(0, y_max + 1e-9, passo)
    partes = [linha_h(m * 60, f'stroke="{CINZA_MARCA}" stroke-opacity=".10"') for m in marcas]
    partes.append(linha_h(livre_s, f'stroke="{COR_TIPICO}" stroke-width="1.5" stroke-dasharray="5 4" opacity=".7"'))
    quebra = [0, *(np.flatnonzero(np.diff(perfil["slot"].to_numpy()) > 1) + 1), len(perfil)]
    for a, b in zip(quebra, quebra[1:]):
        seg = perfil.iloc[a:b]
        xs = X(seg["slot"])
        faixa = pts(xs, Y(seg["p90_s"])) + " " + pts(xs[::-1], Y(seg["p10_s"])[::-1])
        partes.append(f'<polygon points="{faixa}" fill="{COR_REAL}" opacity=".22"/>')
        partes.append(f'<polyline points="{pts(xs, Y(seg["mediana_s"]))}" fill="none" stroke="{COR_REAL}" '
                      'stroke-width="2.4" stroke-linejoin="round" vector-effect="non-scaling-stroke"/>')
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" preserveAspectRatio="none">'
           f'{"".join(partes)}</svg>')
    imagem = base64.b64encode(svg.encode()).decode()

    # camada de dicas: uma faixa por slot de 15 min
    por_slot = perfil.set_index("slot")
    faixas = []
    for slot in range(96):
        if slot not in por_slot.index:
            faixas.append("<span></span>")
            continue
        r = por_slot.loc[slot]
        h, m = divmod(slot * 15, 60)
        dica = (f"{h:02d}:{m:02d} · mediana {_mmss(r.mediana_s)} · P10–P90 {_mmss(r.p10_s)}–{_mmss(r.p90_s)}"
                f" · livre {_mmss(livre_s)} · {int(r.dias)} dia(s)")
        faixas.append(f'<span title="{_esc(dica)}"></span>')
    rotulos_y = "".join(f'<span class="yl" style="top:{(1 - m / y_max) * 100:.2f}%">{m:g} min</span>' for m in marcas)
    eixo_x = "".join(f"<span>{h}h</span>" for h in range(0, 25, 3))
    return (f'<div class="perfil"><img alt="" src="data:image/svg+xml;base64,{imagem}"/>{rotulos_y}'
            f'<div class="hov">{"".join(faixas)}</div></div><div class="perfil-eixo">{eixo_x}</div>')


@st.cache_data(ttl=120, show_spinner=False)
def _dados_analise(dias: int, tipo: str | None, agora_ts: int) -> pd.DataFrame:
    conn = storage.conectar(cfg.db_path)
    try:
        df = analise.preparar(consultas.leituras(conn, agora_ts - dias * 86400), cfg)
    finally:
        conn.close()
    return df if tipo is None else df[df["tipo_dia"] == tipo]


# --- mapa ---------------------------------------------------------------------------

def _mapa(status: pd.DataFrame, geometrias: dict) -> None:
    linhas, pontos = [], []
    for r in status.sort_values("prioridade").itertuples():  # o pior desenhado por último
        coords = geometrias.get(r.rota_id)
        if not coords:
            continue
        info = (f"<b>{_esc(r.tunel)}</b><br/>{_esc(_rotulo_sentido(r.sentido))}<br/>"
                f"{NOME_STATUS[r.status]} · {_mmss(r.tempo_s)} (típico {_mmss(r.referencia_s)})")
        cor = [int(COR[r.status][i:i + 2], 16) for i in (1, 3, 5)]
        linhas.append({"path": [[lon, lat] for lat, lon in coords], "cor": cor, "info": info})
        lat, lon = coords[len(coords) // 2]
        pontos.append({"pos": [lon, lat], "cor": cor, "info": info})
    st.pydeck_chart(
        pdk.Deck(
            layers=[
                pdk.Layer("PathLayer", linhas, get_path="path", get_color="cor", get_width=40,
                          width_min_pixels=5, cap_rounded=True, pickable=True),
                pdk.Layer("ScatterplotLayer", pontos, get_position="pos", get_fill_color="cor",
                          get_radius=120, radius_min_pixels=7, stroked=True, get_line_color=[12, 35, 64],
                          line_width_min_pixels=2, pickable=True),
            ],
            initial_view_state=pdk.ViewState(latitude=-22.96, longitude=-43.33, zoom=10.4),
            tooltip={"html": "{info}"},
            map_style=None,
        ),
        height=620,
    )


# --- página -----------------------------------------------------------------------

st.html(ESTILO)


@st.fragment(run_every=60)
def topo() -> None:
    agora = int(time.time())
    conn = storage.conectar(cfg.db_path)
    try:
        _incluir_rotas_feed(conn)
        st.html(_html_topo(_status(conn, agora), agora))
    finally:
        conn.close()


topo()

c1, c2, c3, c4 = st.columns([1.9, 2.6, 1.6, 2.4], vertical_alignment="center")
visao = c1.segmented_control("Visão", ["Quadro", "Mapa", "Análise"], default="Quadro",
                             label_visibility="collapsed") or "Quadro"
if visao == "Análise":
    dias = c2.segmented_control("Período", [1, 7, 28], default=7, format_func=lambda d: "24 h" if d == 1 else f"{d} dias",
                                label_visibility="collapsed") or 7
    nome_tipo = c3.selectbox("Tipo de dia", list(TIPOS_DIA), label_visibility="collapsed")
else:
    # janela do gráfico: o padrão mostra o momento atual; as maiores trazem o passado
    horas = c2.segmented_control("Janela", [0.5, 1, 3, 6, 12, 24], default=0.5,
                                 format_func=lambda h: "30 min" if h < 1 else f"{h:g} h",
                                 label_visibility="collapsed") or 1
    ordenar = c3.toggle("Problemas primeiro", value=True)
    compactar = c4.toggle("Compactar os normais", value=True,
                          help="Túneis sem alerta, sem alerta do Waze e a menos de 20% do típico ficam numa linha baixa.")


@st.fragment(run_every=60)
def quadro() -> None:
    agora = int(time.time())
    desde = int(agora - horas * 3600)
    conn = storage.conectar(cfg.db_path)
    try:
        status = _status(conn, agora)
        if status["ts"].isna().all():
            st.info("Ainda não há dados. Rode `python -m tuneis coletar`.")
            return
        if visao == "Mapa":
            _mapa(status, storage.carregar_geometrias(conn))
            st.html(_html_ocorrencias(conn, agora))
            return

        series = dict(tuple(consultas.series(conn, desde).groupby("rota_id")))
        alertas = dict(tuple(consultas.alertas(conn, desde).groupby("rota_id")))
        tuneis = _tuneis()
        avisos = _avisos_por_tunel(conn, agora)
        por_rota = status.set_index("rota_id")
        rotas_do = {t: por_rota.loc[[r.id for r in cfg.rotas if r.tunel_id == t]].reset_index() for t, _ in tuneis}
        problema = {t: _tem_problema(rotas_do[t], alertas, avisos.get(t)) for t, _ in tuneis}
        if ordenar:  # pior status primeiro; no mesmo status, alerta do Waze e depois os outros problemas
            pior = status.groupby("tunel")["prioridade"].max()
            tuneis = sorted(tuneis, key=lambda t: (-pior.get(t[1], 0), not avisos.get(t[0]), not problema[t[0]]))

        faixas = []
        for tunel_id, tunel_nome in tuneis:
            rotas = rotas_do[tunel_id]
            compacto = compactar and not problema[tunel_id]
            faixas.append(_html_tunel(tunel_id, tunel_nome, rotas, series, desde, agora,
                                      avisos.get(tunel_id), compacto))

        legenda = (
            '<div class="legenda fixa"><span><i class="l-real"></i>tempo agora (Waze)</span>'
            '<span><i class="l-tip"></i>tempo típico do horário</span><span><i class="l-exc"></i>acima do típico</span>'
            f'<span>{_icone_alerta({"type": "ACCIDENT"}, 13)} acidente / interdição no Waze</span>'
            f'<span>{_icone_alerta({"type": "HAZARD"}, 13)} outro alerta do Waze (passe o mouse para detalhes)</span>'
            '<span>linha sob o sentido = sentido mostrado no gráfico · clique no outro sentido para trocar</span></div>'
        )
        st.html(f'<div class="pcrj">{legenda}<div class="quadro">{"".join(faixas)}</div></div>{SCRIPT_SENTIDO}',
                unsafe_allow_javascript=True)
        st.html(_html_ocorrencias(conn, agora))
        st.html(
            '<div class="pcrj rodape">Tempo típico: mediana do tempo de travessia no mesmo sentido, tipo de dia '
            "(útil, sábado, domingo/feriado) e horário, nas últimas 8 semanas. Enquanto não há 3 dias de histórico "
            "naquele horário, o típico é o historicTime do Waze (rotas do Traffic View) ou o fluxo livre, marcado como "
            "“livre” (aí só interdições geram alerta). Fonte: Waze for Cities.</div>"
        )
    finally:
        conn.close()


@st.fragment(run_every=300)
def painel_analise() -> None:
    df = _dados_analise(dias, TIPOS_DIA[nome_tipo], int(time.time()) // 120 * 120)  # cache por 2 min
    periodo = "últimas 24 h" if dias == 1 else f"últimos {dias} dias"
    if df.empty:
        st.info(f"Sem leituras ({nome_tipo.lower()}) nos {periodo}.")
        return
    resumo = analise.resumo_rotas(df, cfg)
    contexto = f"{periodo} · {nome_tipo.lower()} · {df['data'].nunique()} dia(s) com coleta"
    st.html(
        f'<div class="pcrj secao"><h2>Ranking de atraso<small>{_esc(contexto)}</small></h2>{_html_ranking(resumo)}'
        '<div class="nota">Atraso = tempo de travessia − tempo de fluxo livre. Mediana, P90 e máximo são tempos de '
        f"travessia. Lento = leituras com atraso de {analise.LENTO_S} s ou mais. Leituras com o túnel interditado "
        "contam só em “Interditado”.</div></div>"
    )
    st.html(f'<div class="pcrj secao"><h2>Atraso médio por hora do dia<small>{_esc(contexto)}</small></h2>'
            f"{_html_calor(analise.mapa_calor(df, cfg))}</div>")

    st.html('<div class="pcrj secao"><h2>Perfil do dia por sentido</h2></div>')
    ordem = resumo.sort_values("atraso_medio_s", ascending=False, na_position="last")["rota_id"].tolist()
    rota_id = st.selectbox("Sentido", ordem, format_func=_rotulo, label_visibility="collapsed")
    st.html(
        '<div class="pcrj"><div class="legenda"><span><i class="l-real"></i>mediana</span>'
        '<span><i class="l-faixa"></i>faixa P10–P90 (80% das leituras)</span>'
        '<span><i class="l-tip"></i>fluxo livre</span></div>'
        f"{_html_perfil(analise.perfil_diario(df, rota_id), cfg.rota(rota_id).tempo_fluxo_livre_s)}</div>"
    )
    conn = storage.conectar(cfg.db_path)
    try:
        st.html(_html_rotas_feed(conn))
    finally:
        conn.close()
    st.html(_html_cadastro())
    st.html('<div class="pcrj rodape">Leituras do Waze for Cities a cada 2 min. Rotas do Traffic View: tempo de travessia '
            f"do próprio Waze; fluxo livre estimado a {cfg.feed_rotas.velocidade_livre_kmh:g} km/h. Túneis do feed de "
            "trânsito: fluxo livre + atrasos dos congestionamentos no túnel e na fila de acesso. Com poucos dias de "
            "coleta, o perfil mostra só os dias disponíveis: a dica de cada horário diz quantos.</div>")


if visao == "Análise":
    painel_analise()
else:
    quadro()
