# Monitoramento de Túneis — Rio de Janeiro

**Manual do usuário:** [MANUAL_DO_USUARIO.md](MANUAL_DO_USUARIO.md)

Detecta anomalias no **tempo de travessia** dos túneis da cidade comparando cada leitura com o
tempo típico daquele trecho, sentido, tipo de dia e horário. Fonte de dados: feed **Traffic View
do Waze for Cities**.

```
Waze Traffic View ──► coletor (2 em 2 min) ──► SQLite ──► painel Streamlit
                          │                        ▲
                          ├─ referência histórica ─┘ (recalculada de hora em hora)
                          └─ alertas ──► log + webhook (opcional)
```

## Início rápido (com dados simulados)

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt

.venv\Scripts\python -m tuneis backfill-sim --dias 28        # histórico simulado p/ referências
.venv\Scripts\python -m tuneis coletar --fonte sim           # coletor contínuo (outro terminal)
.venv\Scripts\streamlit run dashboard/app.py                 # painel
```

Para ver um alerta acontecer:

```powershell
.venv\Scripts\python -m tuneis simular-incidente --rota reboucas_lagoa --fator 3 --minutos 40
```

## Fonte real: Waze for Cities

A URL do feed fica no `.env`, na variável `WAZE_TVT_FEED_URL`. Outros feeds lidos junto vão em
`WAZE_TVT_FEED_URL_EXTRA`, separados por vírgula (hoje: o feed com os dois sentidos da Ponte Rio-Niterói). O sistema aceita dois formatos e
detecta sozinho qual é:

- **Feed de trânsito:** traz alertas e congestionamentos, sem um tempo de travessia
  pronto. O tempo de cada sentido é estimado assim:
  `tempo = extensão / velocidade máxima (fluxo livre) + soma dos "delay" dos congestionamentos`.
  - **Quais congestionamentos contam:** os que estão no túnel (`street`) ou na fila de acesso
    que termina na boca dele (`endNode`), a até 3 km do túnel e no mesmo sentido da rota.
  - **Interdição:** um congestionamento de nível 5 ou um alerta `ROAD_CLOSED` no túnel vira
    **crítico** imediatamente.
  - **Nomes dos túneis:** ficam em `waze_rua` (regex) no `config/tuneis.yaml`. Para conferir o que
    o feed mostra agora, rode `python -m tuneis waze-rotas`.
- **Traffic View (em uso):** rotas cadastradas no Partner Hub, com o tempo de travessia
  calculado pelo próprio Waze (`time`), o tempo típico do horário (`historicTime`), a lentidão
  (`jamLevel`), a geometria (`line`) e os trechos (`subRoutes`).
  - **Quais rotas entram:** as que têm o `name` casando com `feed_rotas.filtro_nome` no
    `config/tuneis.yaml`. Elas entram sozinhas, sem precisar estar na lista de túneis.
    O filtro atual pega só os túneis em si (`Rota: Túnel X` ou `Rota: Túnel X - Sentido Y`) e deixa
    de fora os corredores que citam um túnel (com parênteses ou `- Via ...` no nome).
  - **Quais ficam de fora:** `feed_rotas.excluir` recebe uma regex por túnel (Túnel Velho, Túnel Novo,
    Noel Rosa, Nina Rabha, Major Vaz, João Ricardo, Rua Alice). Elas valem sobre o `name` do feed, então
    o túnel sai do painel mesmo continuando publicado no Waze — basta apagar a linha para ele voltar.
  - **Juntar as mãos de um túnel:** `feed_rotas.agrupar` força uma rota para um túnel e um sentido do
    painel, útil quando o nome no feed foge do padrão. O `tunel` define o cartão (rotas com o mesmo
    `tunel` ficam juntas, com uma coluna por sentido) e o `sentido` é o rótulo exibido. Exemplo em uso:
    as duas mãos do Marcello Alencar, `Aterro` e `Rodoviária`, caem no mesmo cartão. A rota entra por
    essa lista mesmo sem casar com o `filtro_nome`. Para conferir o resultado, rode
    `python -m tuneis waze-rotas`, que lista cada rota do feed com o túnel e o sentido que ela assume.
  - **Sentidos:** o nome segue o padrão `Rota: <túnel> - Sentido <destino>`. Os sentidos do mesmo
    túnel (ex.: `Rota: Túnel Rebouças - Sentido Lagoa` e `... - Sentido Rio Comprido`) viram um só
    trecho no painel. Sem sentido no nome, o túnel aparece como mão única.
  - **Referência:** até haver histórico próprio, vale o `historicTime` do Waze. O fluxo livre (usado
    na Análise) é estimado com `feed_rotas.velocidade_livre_kmh`.
  - **Túneis da lista:** com `feed_rotas.incluir_tuneis_yaml: false`, a lista `tuneis` do YAML fica
    fora do painel (ela depende do feed de trânsito). Também dá para vincular uma rota da lista a
    uma rota do feed com `waze_route_id`.
  - A visão **Análise** mostra todos os atributos de cada rota e de cada trecho em **Rotas do Waze**, e em
    **Cadastro das rotas no Waze** as rotas que parecem mal cadastradas no Partner Hub (vazias, com o mesmo
    percurso de outra ou longas demais para um túnel).
  - **Alertas do Waze:** o `leadAlert` de cada rota e de cada trecho (acidente, faixa interditada,
    via interditada, obra, alagamento etc.) aparece como ícone ao lado do nome do túnel, com a
    descrição e o sentido logo abaixo. Passe o mouse para ver a rua, as confirmações e a posição.
    Com "Problemas primeiro", túnel com alerta sobe entre os de mesmo status.
  - **JSON bruto:** cada leitura de cada feed fica em `data/feeds/<feed>/<AAAA-MM-DD>/<HHMMSS>.json.gz`,
    e a mais recente em `data/feeds/<feed>/ultimo.json`. Guarda `coleta.dias_feeds` dias (padrão 7).

**Calibração:** o feed de trânsito não traz histórico. A referência de cada horário passa a valer
depois de **3 dias distintos** de coleta (`min_dias`) para aquele tipo de dia. Até lá, a linha
de "tempo médio" mostra o tempo de fluxo livre e **só interdições geram alerta**. Isso evita que
todo horário de pico vire alarme. Na prática:
- **Dias úteis:** calibrados em cerca de 3 dias.
- **Sábados e domingos/feriados:** calibrados em cerca de 3 semanas.

## Como a anomalia é detectada

Para cada leitura:

1. **Referência**: mediana do tempo de travessia nas últimas 8 semanas para a mesma rota,
   mesmo **tipo de dia** (útil / sábado / domingo-feriado, incluindo feriados do RJ, São Sebastião,
   Carnaval e Corpus Christi) e mesma **faixa de 15 min** (com as faixas vizinhas, janela de 45 min).
   Sem histórico suficiente: `historicTime` do Waze; sem isso: tempo de fluxo livre.
2. **Dispersão robusta**: `max(1,4826 × MAD, 10% da referência, 10 s)`.
3. **Nível**: a leitura precisa estar acima da referência **por razão e por desvios ao mesmo tempo**:

   | Nível | Razão (tempo / referência) | z robusto |
   |---|---|---|
   | Atenção | ≥ 1,4 | ≥ 3 |
   | Crítico | ≥ 2,0 | ≥ 4 |

4. **Alerta com histerese**: abre após 2 leituras anômalas seguidas (~4 min), escala se piorar e
   encerra após 3 leituras normais seguidas (~6 min). Isso evita alarmes por uma leitura ruidosa e
   o "pisca-pisca" de abrir e fechar.

Todos os parâmetros ficam em `config/tuneis.yaml` e podem ser sobrescritos por túnel ou por rota.
Se uma rota fica mais de `dado_ausente_min` sem leitura nova, o painel mostra **Sem dados**. Isso
também pode indicar fechamento do túnel ou problema no feed.

## Painel

- Indicadores: trechos críticos, em atenção, sem dados e alertas abertos.
- Mapa colorido por status e tabela ordenada do pior para o melhor.
- Gráfico do tempo de travessia × referência × limiares, com os períodos de alerta sombreados.
- Histórico de alertas dos últimos 7 dias.
- **Análise** (seletor de visão): resumo dos tempos de travessia em 24 h, 7 ou 28 dias, filtrado por
  tipo de dia:
  - **Ranking de atraso** por sentido: atraso médio sobre o fluxo livre, mediana, P90, máximo, % de
    leituras lentas (atraso ≥ 60 s) e minutos interditado.
  - **Mapa de calor** do atraso médio por sentido × hora do dia.
  - **Perfil do dia** de um sentido: mediana e faixa P10–P90 a cada 15 min, contra o fluxo livre.
  Os cálculos ficam em `tuneis/analise.py`.

### Identidade visual

O painel segue o **Manual de Marca Prefeitura Rio 2025** (`.streamlit/config.toml`):
- **Cores:** azul-marinho `#13335a`, cinza `#eceded` e o degradê `#2a688f → #42b9eb`.
- **Tipografia:** Cera Pro, com Black nos títulos em caixa alta.

A Cera Pro é licenciada. Coloque os arquivos `.woff2` em `dashboard/static/fonts/` (veja o
`LEIAME.md` da pasta). Sem eles, o painel usa a Outfit (Google Fonts). As cores de status
(verde, amarelo e vermelho) continuam separadas das cores da marca, para não se confundirem.

## Webhook

Com `ALERTA_WEBHOOK_URL` definido, cada evento (`ABERTO`, `ESCALADO`, `ENCERRADO`) gera um `POST` JSON:

```json
{"evento": "ABERTO", "texto": "[ABERTO] Túnel Rebouças (...): 9.1 min (referência 3.8 min, 2.4x) — nível CRITICO",
 "alerta_id": 12, "rota_id": "reboucas_lagoa", "tunel": "Túnel Rebouças", "sentido": "Rio Comprido → Lagoa",
 "nivel": "CRITICO", "inicio_ts": 1792663200, "fim_ts": null, "tempo_s": 546, "referencia_s": 228, "razao": 2.39}
```

## Comandos

| Comando | O que faz |
|---|---|
| `coletar [--fonte waze\|sim] [--uma-vez]` | coleta contínua, detecção e alertas |
| `backfill-sim [--dias 28] [--limpar]` | gera histórico simulado |
| `baseline` | recalcula as referências agora |
| `simular-incidente --rota ID` | força um incidente no simulador |
| `waze-rotas` | lista as rotas do feed do Waze para fazer o vínculo |
| `status` | situação atual no terminal |

## Estrutura

```
config/tuneis.yaml     túneis, rotas por sentido, vínculo Waze e parâmetros
tuneis/waze.py         leitura do feed Traffic View
tuneis/simulador.py    feed simulado no mesmo formato
tuneis/baseline.py     referência histórica (mediana/MAD por slot)
tuneis/detector.py     classificação e histerese dos alertas
tuneis/analise.py      agregações da visão Análise (ranking, mapa de calor, perfil)
tuneis/monitor.py      pipeline por leitura + notificação
tuneis/coleta.py       laço do coletor e backfill
tuneis/storage.py      SQLite (WAL)
dashboard/app.py       painel Streamlit
tests/                 pytest
```

> As coordenadas em `config/tuneis.yaml` são aproximadas e servem só ao simulador. Com o Waze
> ligado, o mapa usa a geometria real de cada rota do feed.
