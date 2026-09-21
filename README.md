# Mizuki Airflows

**Um data warehouse de voos comerciais brasileiros, com um agente que responde perguntas em
português escrevendo o SQL na hora.**

### → **[Abrir a demonstração do agente](https://leonardo369852.github.io/mizuki-airflows-datawarehouse/agente/)**

Não precisa instalar, logar nem criar conta. Pergunte `qual empresa tem a maior taxa de
cancelamento?` e veja o SQL que produziu a resposta.

> É uma **demonstração pública** sobre um recorte agregado dos dados. O agente principal do
> projeto é o Genie space do Databricks, que consulta o milhão de linhas inteiro — mas ele não
> pode ser aberto por link. [A diferença entre os dois, em detalhe.](#os-dois-agentes)

---

Por trás dele há um data warehouse completo no Databricks: arquitetura medalhão
(Bronze → Silver → Gold), modelo dimensional em estrela, dois dashboards AI/BI e um pipeline
declarativo com quarentena de dados inválidos. Tudo sobre os dados abertos da ANAC.

Projeto desenvolvido na Imersão de Engenharia de Dados com IA da Alura.

| | |
|---|---|
| **Janela** | ago/2025 a jul/2026, 12 meses |
| **Volume** | 1.014.705 voos, 29.145 cancelamentos |
| **Cobertura** | 118 empresas operaram, 374 aeroportos de origem, 3.104 rotas |
| **Pontualidade** | 79,9% na partida — 82,5% entre os voos com horário previsto ([por quê?](#o-que-a-fonte-esconde)) |

---

## Os dois agentes

O projeto tem **dois** agentes, e eles não são equivalentes.

**O agente principal é o Genie space, dentro do Databricks.** Ele consulta a `obt_voos` inteira —
1.014.705 linhas, 56 colunas, uma linha por voo — com o NL2SQL nativo da plataforma, sobre o
warehouse governado. É o que este projeto entrega como produto de engenharia de dados.

**O agente deste link é uma demonstração.** Ele existe porque nenhum recurso hospedado no
Databricks pode ser público: Genie space, Databricks App e Free Edition todos exigem que o
visitante exista dentro do workspace, com `SELECT` nas tabelas do Unity Catalog. Não há link
anônimo. Para mostrar o trabalho a quem não tem conta, a saída foi exportar um recorte agregado
e levar o motor de consulta para o navegador.

### O que a demonstração não responde

O grão do fato exportado é `mês × empresa × origem × destino × situação × período × tipo de linha`.
Tudo abaixo desse grão foi perdido de propósito, para caber em 1,5 MB:

| Pergunta | Genie | Este link |
|---|:---:|:---:|
| Pontualidade, atraso e cancelamento por empresa, rota, aeroporto, mês | ✅ | ✅ |
| Um voo específico — número, data exata, horário de partida | ✅ | ❌ |
| Por dia, ou por dia da semana | ✅ | ❌ só mês; do dia da semana, só útil × fim de semana |
| Horário exato de partida ou chegada | ✅ | ❌ só o período (madrugada, manhã, tarde, noite) |
| Minutos de atraso recuperados em voo | ✅ | ❌ medida não exportada |
| Status operacional do aeródromo | ✅ | ❌ não exportado |

O agente é instruído a responder isso quando perguntado, em vez de tentar uma consulta que o
modelo dele não sustenta.

### Como a demonstração funciona

```
sua pergunta
    ↓
Cloudflare Worker  ──→  Gemini          devolve {tipo, sql, gráfico, aviso}
    ↓                   (chave e prompt ficam no servidor)
DuckDB-WASM        ──→  executa o SQL no SEU navegador
    ↓                   sobre 5 Parquet estáticos, 1,5 MB
gráfico + "ver o SQL" + a tabela de linhas
```

**O modelo nunca produz um número.** Ele escolhe a consulta; a conta é feita na máquina de quem
pergunta. Por isso cada resposta traz o SQL que a gerou, aberto ao lado. Num portfólio de
engenharia de dados, um número inventado que parece plausível é o pior defeito possível — este
desenho torna isso impossível por construção.

### Decisões que sustentam o resto

**Somas e contagens, nunca médias.** O fato exportado ([`Exportar Fato do Agente.py`](databricks/Agents/Exportar%20Fato%20do%20Agente.py))
guarda `soma_atraso` e `com_atraso`, não `atraso_medio`. Se guardasse a média, qualquer recorte que
o visitante pedisse viraria média de média — errada sempre que os grupos têm tamanhos diferentes,
que é o caso. Com soma e contagem, `SUM(soma)/SUM(contagem)` está correto em **qualquer** nível de
agregação.

**Fato estreito, dimensões à parte.** `uf`, `município`, `latitude` e `distancia_km` são função das
chaves e viriam repetidos um milhão de vezes se entrassem no fato. Ficam em quatro dimensões
pequenas e o DuckDB junta. Resultado: 1.014.705 linhas da Gold viram **86.518** no fato —
compressão de 11,7x, 1,5 MB no total.

**O grão é validado, não presumido.** O notebook termina com duas provas: uma compara os totais com
a `obt_voos`, outra compara o OTP por empresa nas duas fontes. A segunda existe porque, se uma chave
faltasse no `GROUP BY`, os totais ainda fechariam — mas os cortes não.

**Roteamento antes de SQL.** Nem toda pergunta é consulta. "o que isso significa?", "o que é você?",
"obrigado" recebem resposta em prosa, sem gráfico e sem SQL. O agente também recebe os últimos
turnos da conversa com o SQL e as primeiras linhas de cada um, então "e em fevereiro?" reaproveita a
consulta anterior trocando só o filtro.

**O prompt fica no servidor, não na página.** Se o cliente pudesse mandar o prompt, o endpoint seria
um relay de LLM aberto — alguém acharia a URL e usaria a cota para gerar qualquer coisa. Aceitando
só a pergunta e devolvendo só SQL contra um schema fixo, o pior uso possível continua sendo
perguntar sobre voos brasileiros.

**O SQL gerado não roda em servidor nenhum.** Ele é executado em memória, no navegador do visitante,
sobre arquivos estáticos e sem credencial. Não existe banco para atacar nem warehouse para derrubar.
A validação que recusa qualquer coisa que não seja `SELECT` é cinto sobre suspensório.

Implantação, travas de custo e como trocar de provedor de IA:
[`agente/worker/README.md`](agente/worker/README.md).

---

## O que a fonte esconde

Achados de qualidade que mudam a leitura dos números. Estão aqui, e não num comentário de código,
porque o projeto inteiro se apoia em não esconder o que descarta.

**1. 30.800 voos (3,0%) não têm data de partida prevista.** Sem horário previsto não há atraso a
calcular, então nenhum deles conta como pontual — mas todos entram no denominador. É por isso que a
pontualidade geral (**79,9%**) é *menor* que a de qualquer um dos doze meses individuais (81,4% a
85,9%). Sobre os 954.760 voos realizados com horário previsto, ela é **82,5%**. Esses voos também
desaparecem de todo recorte por tempo.

**2. A justificativa de cancelamento está vazia.** Todos os 29.145 cancelamentos trazem `N/A` no
código de justificativa: **um único valor distinto na coluna inteira**. Não é possível dizer por que
um voo foi cancelado, e o agente é instruído a responder isso em vez de atribuir uma causa.

**3. Dois encodings no mesmo pipeline.** O cadastro de empresas nacionais vem em ISO-8859-1 e o de
estrangeiras em UTF-8, mas a ingestão lê os dois igual. O resultado era `IBÃRIA`, `AVIACIÃN`,
`COMPAÃIA PANAMEÃA`. Corrigido na exportação; a correção definitiva é o encoding do CSV na Bronze.

**4. Timestamps invertidos.** Produzem atrasos impossíveis — há empresa com média de −4.313 minutos,
três dias "adiantada". Existem também rotas com origem igual ao destino e 0 km. Nada foi descartado:
o fato guarda a soma bruta **e** uma soma restrita à faixa plausível (−60 a 1.440 min), e o agente
usa a segunda em ranking de atraso, declarando o corte.

**5. O cadastro de aeródromos só cobre o Brasil.** Dos 224 aeródromos com movimento relevante, 85
não têm nome, município nem coordenada: 79 estrangeiros e 6 brasileiros que faltam no cadastro da
ANAC (`SBIZ`, `SNCL`, `SBUY`, `SSOU`, `SBCR`, `SDLO`). São **10,5% das partidas**, e elas ficam fora
do mapa.

### Um achado analítico

**Sair de São Paulo é sempre pior.** Comparando a mesma rota nos dois sentidos, em **38 de 38**
destinos domésticos com 800+ voos realizados em cada direção, o voo que *parte* de Guarulhos ou
Congonhas é menos pontual que o que *chega* lá. Sem uma única exceção. Petrolina lidera o contraste:
73,3% saindo contra 91,0% chegando. Não é modelo nem estatística — é o par origem-destino invertido.

---

## Arquitetura

```
ANAC (CSV)  →  Bronze  →  Silver  →  Gold  →  Dashboards + Agente
                 tudo      espelho    star
                 STRING    tipado     schema
```

O catálogo é `mizukiairflows`, no Unity Catalog, com um schema por camada.

### Bronze: dados brutos, sem interpretação

Ingestão dos CSV da ANAC com **todas as colunas como STRING**. Nada de conversão, nada de filtro: o
que chega do órgão é o que fica gravado. Cada tabela carrega duas colunas de auditoria,
`_source_file` e `_ingestion_timestamp`, que dizem de qual arquivo e de que momento veio cada linha.

Tabelas: `vra`, `aerodromos_publicos`, `empresas_aereas_nacionais`, `empresas_aereas_estrangeiras`.

### Silver: o mesmo dado, agora governado

A regra da camada é estrita: **Silver é espelho exato do Bronze**. Mesma granularidade, mesma
contagem de linhas, nenhum filtro de negócio e nenhuma agregação. O que muda é a qualidade da
informação sobre o dado:

- tipagem aplicada (data vira `TIMESTAMP`, altitude vira `DOUBLE`, coordenadas viram número);
- **comentário em 100% das colunas**, verificado por uma consulta de auditoria no próprio notebook;
- tags de governança nas tabelas;
- uma função de validação de código ICAO, usada para medir qualidade;
- `silver.empresas` unifica nacionais e estrangeiras num cadastro só, mantendo a origem rastreável.

Cada etapa termina com uma prova de contagem Bronze × Silver. Se divergir, o notebook acusa.

Há ainda um **pipeline declarativo** (`databricks/Silver/mizuki-airflows-silver_959fe697/`) que
separa o joio do trigo em três passos: `airflow_marcado` valida os códigos ICAO contra as tabelas de
referência e marca cada registro; `airflow_auditado` fica com o que passou; `airflow_quarentena` fica
com o que foi rejeitado, **junto com o motivo da rejeição**. Dado ruim não some: vai para a
quarentena, onde pode ser investigado.

### Gold: modelo dimensional

Star schema clássico, uma fato cercada de dimensões:

| Tabela | O que é | Linhas |
|---|---|---:|
| `fato_voos` | um voo por linha, particionada por data de partida prevista | 1.014.705 |
| `dim_tempo` | calendário do período | 366 |
| `dim_empresa` | empresas aéreas por ICAO, deduplicadas | 169 |
| `dim_aerodromo` | aeródromos públicos com coordenadas decimais | 496 |
| `dim_rota` | pares de origem e destino com distância em km (Haversine) | 3.104 |
| `dim_tipo_linha` | nacional, internacional, geral, cargueiro | 4 |
| `dim_situacao_voo` | realizado, cancelado | 2 |
| `auditoria_carga` | métricas de cada execução da carga | |
| `vw_otp_por_empresa` | visão de pontualidade por empresa | |
| `obt_voos` | *One Big Table*: a fato desnormalizada com as 7 dimensões aplicadas | 1.014.705 |

As dimensões são cadastros: `dim_empresa` tem 169 empresas e `dim_aerodromo` 496 aeródromos, mas no
período **118 empresas operaram** e **374 aeroportos** apareceram como origem. Cadastro e operação
são coisas diferentes, e a fato mostra a segunda.

A `obt_voos` existe porque ferramenta de BI costuma ser mais rápida e mais simples de usar contra
uma tabela larga do que contra sete junções. As colunas seguem prefixo por origem (`empresa_`,
`origem_`, `destino_`, `rota_`), para não haver ambiguidade sobre de qual dimensão veio cada campo.

A fato não guarda só chaves: traz as medidas já calculadas (atraso de partida, atraso de chegada,
minutos recuperados em voo e duração) e um conjunto de indicadores booleanos (realizado, cancelado,
partida pontual, chegada pontual, atraso severo) que deixam as agregações de pontualidade diretas,
sem repetir regra de negócio em cada consulta.

**Critério de pontualidade:** partida com até 15 minutos de atraso, que é o padrão ANAC/IATA. O
denominador é o voo **realizado** — quem não decolou não pode ser pontual nem atrasado. Dos voos do
período, 97,1% foram realizados e 2,9% cancelados.

---

## Dashboards

Dois, ambos em `databricks/Dashboards/` no formato `.lvdash.json` do Databricks AI/BI. Eles rodam
dentro do workspace; o link público acima não depende deles.

**Operações de Voos — OBT.** Lê a `obt_voos`. Quatro indicadores no topo, evolução mensal,
distribuição por tipo de linha, ranking de empresas, faixas de distância, mapa dos aeródromos e uma
tabela-resumo por empresa.

**Dashboard de Operações de Voos — ANAC.** Lê o star schema diretamente, com as seis dimensões
declaradas como datasets e os relacionamentos com a fato configurados como muitos-para-um. Vai mais
fundo: atraso médio de partida **e de chegada**, duração média de voo, taxa de cancelamento, uma
seção dedicada a rotas e cortes por período de partida, dia da semana, fim de semana e estação.

> **Nota de implementação.** No editor de dashboards, uma consulta de widget descarta silenciosamente
> expressões complexas (`SUM(CASE WHEN ...)`, `ROUND(...)`). A saída é declarar essas métricas como
> campos calculados no dataset e referenciá-las com `MEASURE()` no widget.

> **Divergência conhecida.** A medida `otp_partida` do dashboard ANAC divide por `COUNT(1)` em vez do
> total de realizados, e por isso mostra 77,6% onde o resto do projeto mostra 79,9%. O denominador
> correto é o voo realizado. Corrigir ainda está pendente.

---

## Reproduzir

Os CSV da ANAC **não estão versionados** aqui: são públicos, pesados e reproduzíveis.

```bash
python scripts/baixar_anac.py
```

O script busca os 12 meses de VRA mais os cadastros de aeródromos e de empresas, calcula o SHA-256 de
cada arquivo e gera `docs/fontes.md` com a procedência de tudo o que entrou.

Em seguida, suba os arquivos para o Volume do Unity Catalog em
`/Volumes/mizukiairflows/bronze/arquivos/` e execute os notebooks na ordem Bronze → Silver → Gold.

Para regenerar os dados do agente público, rode
[`Exportar Fato do Agente`](databricks/Agents/Exportar%20Fato%20do%20Agente.py) e commite os seis
arquivos em `agente/dados/`.

### Armadilhas da fonte, já resolvidas no script

- O mês no **nome do arquivo** não tem zero à esquerda (`VRA_20258.csv`), mas o mês na **pasta** tem
  (`08 - Agosto`). Misturar os dois dá 404.
- As URLs têm espaços e acentos e exigem *percent-encoding*.
- A primeira linha do CSV não é o cabeçalho: é `Atualizado em: <data>`.
- `pda_empresas_aereas_nacionais.csv` tem duas cópias no portal. A da raiz de `Operador Aéreo/` está
  corrompida na origem: 144 MB de exportação aninhada e repetida, com 646 empresas viradas em cerca
  de 461 mil linhas. A boa está na subpasta `Empresas Aereas Nacionais/`, com 212 KB.
- A ANAC mantém dois repositórios de VRA. O de `www.gov.br` está descontinuado, congelado em
  out/2024. Este projeto usa apenas `sistemas.anac.gov.br/dadosabertos`.

---

## Estrutura

```
agente/
  index.html       a página pública: chat, DuckDB-WASM e os gráficos
  dados/           5 Parquet + manifest.json, exportados da Gold (1,5 MB)
  worker/          Cloudflare Worker: guarda a chave e o prompt da IA
databricks/
  Bronze/          notebooks de ingestão (Python)
  Silver/          notebook de governança (SQL) + pipeline declarativo + qualidade
  Gold/            notebook do star schema e da OBT (Python)
  Dashboards/      os dois dashboards AI/BI
  Agents/          exportação do fato e contexto do assistente do workspace
scripts/
  baixar_anac.py   download reproduzível da fonte oficial
docs/
  fontes.md        gerado pelo script: procedência e hash de cada arquivo
```

**Compute:** Serverless. Views materializadas não são suportadas nesse modo, então o projeto usa
views comuns.

---

## Fonte

Dados abertos da ANAC: <https://sistemas.anac.gov.br/dadosabertos/>

- **VRA** (Voo Regular Ativo): um registro por voo, com horários previstos e reais.
- **Aeródromos Públicos**: cadastro com coordenadas.
- **Empresas Aéreas** nacionais e estrangeiras: cadastro dos operadores.
