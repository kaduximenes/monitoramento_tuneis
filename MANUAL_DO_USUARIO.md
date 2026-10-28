# Manual do usuário

## Para que serve

O sistema acompanha o tempo de travessia por túnel e sentido, compara cada leitura com um tempo típico e destaca situações fora do padrão. Os dados vêm do Waze for Cities; o painel e os indicadores se atualizam automaticamente.

O tempo de travessia é um indicador de trânsito, não uma medição física do tempo gasto exclusivamente entre as bocas do túnel. A extensão e a geometria usadas são as fornecidas pelo Waze para cada rota. Embora o filtro atual selecione rotas identificadas como túneis e descarte nomes que parecem indicar corredores maiores, a rota cadastrada pode incluir vias de acesso. Consulte **Rotas do Waze** e **Cadastro das rotas no Waze** na visão **Análise** para verificar o percurso e eventuais problemas de cadastro.

## Cabeçalho e atualização

No topo do painel aparecem:

- **Crítico, Atenção, Calibrando, Sem dados e Normal:** quantidade de túneis/trechos nessa situação. Cada túnel é contado uma vez, pelo pior status entre os sentidos; **Interditado** entra na contagem de **Crítico**.
- **Túneis e ponte / sentidos:** total de estruturas e de sentidos monitorados naquele momento. As rotas podem ser descobertas pelo feed do Waze.
- **Relógio, ao vivo e “Waze há X min”:** horário local do painel e idade da leitura mais recente recebida. “Waze agora” indica leitura com menos de 90 segundos.

O coletor busca dados aproximadamente a cada 2 minutos. O cabeçalho e o quadro são atualizados a cada minuto. Atrasos na publicação ou indisponibilidade do feed podem deixar a leitura mais antiga.

## Escolha da visão

### Quadro

Mostra os túneis e os sentidos monitorados, com o status atual e o gráfico de cada sentido.

- **Janela:** escolhe quanto histórico aparece no gráfico: 30 min, 1 h, 3 h, 6 h, 12 h ou 24 h. O padrão ao abrir é **30 min**.
- **Problemas primeiro:** ordena os túneis pelo pior status. Em situações equivalentes, dá prioridade a alertas do Waze e a outros problemas identificados pelo painel.
- **Compactar os normais:** reduz o espaço dos túneis sem alerta, sem alerta do Waze e com tempo até 20% acima do típico.
- **Status do túnel:** resume a situação do pior sentido. Para entender a diferença entre sentidos, leia os valores de cada sentido no cartão.

Em cada sentido:

- **Tempo grande:** tempo atual de travessia informado pelo Waze.
- **Diferença e percentual:** quanto o tempo atual está acima ou abaixo do tempo típico. Um valor positivo indica travessia mais demorada; um valor negativo, mais rápida.
- **Típico:** referência usada para aquele horário. Quando a referência ainda é o fluxo livre estimado, o rótulo aparece como **livre**.
- **Interditado:** indicação de interdição recebida/registrada para o sentido. Nesse estado, o tempo de travessia não deve ser interpretado como uma medição normal.
- **Sem leituras:** ainda não há leitura para o sentido.

O gráfico usa uma linha contínua para o tempo atual, uma linha tracejada para o tempo típico e uma área sombreada para o intervalo acima do típico. Passe o mouse sobre o gráfico para consultar horário, tempo atual e referência. Em túneis com mais de um sentido, clique no sentido desejado para exibir seu gráfico. O painel seleciona automaticamente o sentido com pior status; para voltar a essa seleção, clique no sentido que estava selecionado automaticamente.

Uma diferença destacada em cor pode ser apenas um aviso visual: valores a partir de 20% acima do típico podem receber destaque mesmo sem alcançar os critérios estatísticos de **Atenção**.

### Mapa

Exibe a geometria recebida do Waze, colorida pelo status do sentido. Selecione uma linha ou um ponto para ver túnel, sentido, status, tempo atual e tempo típico. O mapa ajuda a localizar a rota, mas não garante que o desenho esteja limitado ao interior do túnel.

### Ocorrências

Ao final do Quadro e do Mapa, **Ocorrências · 24 h** lista os alertas de trânsito registrados pelo sistema nas últimas 24 horas. A linha informa horário de início, túnel, sentido, nível máximo, pico observado, referência, razão entre os tempos e duração. A duração aparece como **em aberto** enquanto o alerta não foi encerrado; caso contrário, aparece como **encerrado**.

Ícones junto ao nome do túnel são ocorrências fornecidas pelo próprio Waze, como acidente, interdição, obra ou outro perigo. Passe o mouse para ver tipo, via, sentido e confirmações. Esses avisos são distintos do alerta estatístico gerado pela comparação dos tempos.

## Visão Análise

Selecione o período (**24 h**, **7 dias** ou **28 dias**) e o tipo de dia. O contexto informa quantos dias tiveram coleta. Os cálculos consideram o horário local do Rio de Janeiro.

### Ranking de atraso

Cada linha representa um túnel e sentido. O ranking é ordenado pelo maior atraso médio.

- **Atraso médio:** média de `máximo(tempo de travessia - fluxo livre, 0)`. Leituras interditadas são excluídas.
- **Mediana:** tempo de travessia que divide as leituras válidas do período ao meio.
- **P90:** percentil 90 do tempo de travessia; 90% das leituras válidas ficaram nesse tempo ou abaixo.
- **Máximo:** maior tempo de travessia válido no período.
- **Lento:** percentual de leituras cujo atraso sobre o fluxo livre foi de pelo menos 60 segundos.
- **Interditado:** minutos estimados em condição de interdição, com base no intervalo de coleta.

Se aparecer **sem leituras no período**, não houve dados daquele sentido no recorte. **Só leituras interditado** significa que os dados disponíveis foram todos marcados como interdição e, por isso, não entram nas estatísticas de tempo.

### Atraso médio por hora do dia

O mapa de calor apresenta o atraso médio sobre o fluxo livre por sentido e hora do dia. Célula vazia significa que não houve leitura naquele horário. As leituras interditadas não entram na média. Passe o mouse sobre uma célula para ver o horário e o valor.

### Perfil do dia por sentido

O gráfico agrupa os dias selecionados em intervalos de 15 minutos:

- A linha mostra a mediana do tempo de travessia.
- A faixa mostra do percentil 10 ao percentil 90, ou seja, a região que contém os 80% centrais das leituras.
- A linha tracejada mostra o fluxo livre estimado para comparação.
- Ao passar o mouse, são exibidos horário, mediana, faixa P10–P90, fluxo livre e quantidade de dias com leitura naquele horário.

O perfil resume os dias disponíveis no período; não é a previsão de um dia específico.

### Rotas do Waze

Esta tabela detalha os campos recebidos do Traffic View. A linha principal pode ser expandida para consultar atributos e trechos (`subRoutes`).

- **time:** tempo atual estimado pelo Waze.
- **historicTime:** tempo típico informado pelo Waze para a rota e o horário.
- **diferença:** `time - historicTime`; positiva indica tempo atual maior.
- **jamLevel:** indicador de lentidão do Waze, de 0 (livre) a 4 (parado). É um dado de contexto e não é, por si só, o status estatístico do painel.
- **length:** extensão da rota informada pelo Waze.
- **vel. média:** extensão dividida pelo tempo atual; é uma estimativa derivada desses dois campos.
- **fromName / toName / subRoutes:** nomes de origem e destino e divisão da rota em trechos fornecidos pelo Waze.

### Cadastro das rotas no Waze

Mostra rotas do feed que aparentam ter cadastro incompleto, percurso duplicado ou extensão longa demais para um túnel. Uma rota vazia pode ficar fora do painel; rotas com o mesmo percurso podem repetir os números; uma rota longa pode incorporar trânsito fora do túnel. Use as informações para revisar o cadastro no Partner Hub. A checagem depende do último arquivo recebido de cada feed.

## Como o status e os alertas são calculados

### Tempo atual e referência

No feed Traffic View usado pelo sistema, o tempo atual (`time`) e o histórico informado pelo Waze (`historicTime`) são recebidos por rota. O fluxo livre usado em algumas análises é estimado por `extensão ÷ velocidade livre`; para rotas descobertas no Traffic View, a configuração atual usa 60 km/h.

A referência chamada **típico** segue esta ordem:

1. **Histórico próprio:** mediana das leituras da mesma rota, tipo de dia e faixa de 15 minutos, usando também as faixas vizinhas (janela total de 45 minutos) das últimas 8 semanas.
2. **Histórico do Waze:** `historicTime`, quando ainda não há amostras próprias suficientes.
3. **Fluxo livre:** estimativa pela extensão e velocidade configurada, quando não há histórico próprio nem `historicTime` disponível.

Para usar o histórico próprio, a configuração exige pelo menos 20 amostras e 3 dias distintos naquele agrupamento. Dias úteis, sábados e domingos/feriados são comparados separadamente. Feriados do Rio de Janeiro, São Sebastião, Carnaval e Corpus Christi entram na categoria domingo/feriado.

### Atenção e Crítico

Quando há uma referência histórica, o sistema calcula:

- **Razão:** `tempo atual ÷ referência`.
- **Desvio robusto (z):** `(tempo atual - referência) ÷ dispersão robusta`.
- **Dispersão robusta:** o maior valor entre `1,4826 × MAD`, 10% da referência e 10 segundos. MAD é a mediana dos desvios absolutos em relação à mediana.

Os dois critérios do nível precisam ser atingidos ao mesmo tempo:

| Nível | Razão mínima | Desvio robusto mínimo |
|---|---:|---:|
| Atenção | 1,4× | 3 |
| Crítico | 2,0× | 4 |

Assim, um aumento percentual sozinho não basta. Por exemplo, passar de 4 para 6 minutos é 1,5× o típico; isso só é **Atenção** se também alcançar pelo menos 3 desvios robustos.

Enquanto a única referência disponível for o fluxo livre, o sistema mostra **Calibrando** e não classifica o pico normal como anomalia. Com a configuração atual, nessa fase somente uma interdição explícita pode gerar nível crítico. Isso evita alertas excessivos antes de haver histórico comparável.

### Abertura e encerramento de alertas

O alerta abre após 2 leituras consecutivas em Atenção ou Crítico (aproximadamente 4 minutos, com coleta de 2 em 2 minutos). Se o nível piorar durante o alerta, ele pode ser escalado. O encerramento ocorre após 3 leituras consecutivas normais (aproximadamente 6 minutos). Essa histerese reduz alertas causados por oscilações isoladas.

**Sem dados** aparece quando não existe leitura ou quando a última leitura passou de 10 minutos, conforme a configuração atual. Isso pode significar indisponibilidade do feed ou ausência de dados; não confirma, sozinho, que o túnel esteja fechado.

## Observações importantes

- A lista de rotas é controlada pelo filtro de nomes e pelo cadastro no Waze. O sistema usa `time`, `length` e `line` da rota inteira e não recorta automaticamente o trecho entre as bocas do túnel.
- No formato alternativo de feed de trânsito, o tempo é calculado como fluxo livre mais atrasos de congestionamentos identificados no túnel ou na fila de acesso, até 3 km e no mesmo sentido. Portanto, nesse formato as vias de acesso podem contribuir explicitamente para o atraso.
- **jamLevel**, status estatístico, alertas do Waze e interdição são informações relacionadas, mas não equivalentes.
- Um período sem leituras ou com poucos dias de histórico reduz o que é possível concluir. Confira o horário da última leitura e a quantidade de dias indicados na visão Análise.