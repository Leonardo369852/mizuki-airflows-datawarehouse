# Mizuki Airflows

Data warehouse de operações aéreas brasileiras, construído no Databricks sobre os dados abertos da
ANAC. Arquitetura medalhão (Bronze → Silver → Gold), com modelo dimensional em estrela, um agente de
IA contextualizado no catálogo e dois dashboards.

Projeto desenvolvido na Imersão de Engenharia de Dados com IA da Alura.

**Volume:** 1.014.705 voos, 12 meses (ago/2025 a jul/2026), 496 aeródromos públicos e 169 empresas
aéreas.

---

## O que este projeto responde

**Pontualidade e atraso**

- Qual o OTP de cada empresa aérea, na **partida e na chegada**, pelo critério oficial de 15
  minutos da ANAC/IATA.
- De quantos minutos é o atraso médio de partida e o de chegada.
- Quantos voos têm atraso severo, e de quem são.
- **Quanto de atraso é recuperado em voo**: a diferença entre o atraso na partida e o atraso no
  pouso, medida voo a voo.
- Como a pontualidade varia por **período do dia** (madrugada, manhã, tarde, noite), por dia da
  semana, entre dia útil e fim de semana, e por estação do ano.

**Malha e rotas**

- Quais são as rotas mais movimentadas, entre 3.104 pares de origem e destino.
- Quanto se voa por faixa de distância: curta (menos de 500 km), média, longa e extra-longa (mais de
  3.000 km), com a distância calculada por Haversine a partir das coordenadas.
- Qual a duração média de voo, e as distâncias média, mínima e máxima da malha.
- Onde estão os aeródromos que concentram o movimento, em mapa, com **município e UF** de origem e de
  destino.

**Empresas aéreas**

- Quais concentram o volume, em ranking.
- Como se comportam **nacionais e estrangeiras** lado a lado, com o tipo de serviço e a situação
  cadastral de cada operador, inclusive se ainda está ativo.

**Cancelamento**

- Qual a taxa de cancelamento, por empresa e por rota.
- **Com qual justificativa**: cada voo cancelado carrega o código informado à ANAC.

**Evolução no tempo**

- Como o volume, a pontualidade e o cancelamento se movem mês a mês ao longo dos 12 meses da janela.

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

A carga usa `COPY INTO`, que é idempotente. Rodar o notebook duas vezes não duplica dado.

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

Há ainda um **pipeline declarativo** (`databricks/Silver/mizuki-airflows-silver_959fe697/`) que separa
o joio do trigo em três passos: `airflow_marcado` valida os códigos ICAO contra as tabelas de
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
| `dim_rota` | pares de origem e destino com distância em km (fórmula de Haversine) | 3.104 |
| `dim_tipo_linha` | nacional, internacional, geral, cargueiro | 4 |
| `dim_situacao_voo` | realizado, cancelado | 2 |
| `auditoria_carga` | métricas de cada execução da carga | |
| `vw_otp_por_empresa` | visão de pontualidade por empresa | |
| `obt_voos` | *One Big Table*: a fato desnormalizada com as 7 dimensões já aplicadas | 1.014.705 |

A `obt_voos` existe porque ferramenta de BI costuma ser mais rápida e mais simples de usar contra uma
tabela larga do que contra sete junções. As colunas seguem prefixo por origem (`empresa_`,
`origem_`, `destino_`, `rota_`), para não haver ambiguidade sobre de qual dimensão veio cada campo.

A fato não guarda só chaves: traz as medidas já calculadas (atraso de partida, atraso de chegada,
minutos recuperados em voo e duração) e um conjunto de indicadores booleanos (realizado, cancelado,
partida pontual, chegada pontual, atraso severo) que deixam as agregações de pontualidade diretas,
sem repetir regra de negócio em cada consulta.

**Critério de pontualidade:** partida com até 15 minutos de atraso, que é o padrão ANAC/IATA. Dos
voos do período, 97,1% foram realizados e 2,9% cancelados.

---

## Dashboards

Dois, ambos em `databricks/Dashboards/` no formato `.lvdash.json` do Databricks AI/BI.

**Operações de Voos — OBT.** Lê a `obt_voos`. Quatro indicadores no topo (total de voos, realizados,
cancelados, pontualidade), evolução mensal, distribuição por tipo de linha, ranking de empresas,
faixas de distância, mapa dos aeródromos e uma tabela-resumo por empresa.

**Dashboard de Operações de Voos — ANAC.** Lê o star schema diretamente, com as seis dimensões
declaradas como datasets e os relacionamentos com a fato configurados como muitos-para-um. Vai mais
fundo na análise: atraso médio de partida **e de chegada** em minutos, duração média de voo, taxa de
cancelamento, uma seção dedicada a rotas (total de rotas, distância média, mínima e máxima) e cortes
por período de partida, dia da semana, fim de semana e estação do ano. Serve para navegar o modelo
dimensional como ele foi desenhado.

> **Nota de implementação.** No editor de dashboards, uma consulta de widget descarta silenciosamente
> expressões complexas (`SUM(CASE WHEN ...)`, `ROUND(...)`). A saída é declarar essas métricas como
> campos calculados no dataset e referenciá-las com `MEASURE()` no widget.

---

## Agente

`databricks/Agents/.assistant_instructions.md` é a memória de contexto do assistente do workspace.
Ele documenta para a IA o catálogo, a regra inegociável da Silver, o star schema completo com as
contagens, o critério de pontualidade e a estrutura dos dois dashboards, de modo que perguntas em
linguagem natural sejam respondidas contra o modelo certo, e não contra uma suposição.

---

## Reproduzir

Os CSV da ANAC **não estão versionados** aqui: são públicos, pesados e reproduzíveis. Para baixá-los:

```bash
python scripts/baixar_anac.py
```

O script busca os 12 meses de VRA mais os cadastros de aeródromos e de empresas, calcula o SHA-256 de
cada arquivo e gera `docs/fontes.md` com a procedência de tudo o que entrou.

Em seguida, suba os arquivos para o Volume do Unity Catalog em
`/Volumes/mizukiairflows/bronze/arquivos/` e execute os notebooks na ordem Bronze → Silver → Gold.

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
databricks/
  Bronze/          notebooks de ingestão (Python)
  Silver/          notebook de governança (SQL) + pipeline declarativo + avaliação de qualidade
  Gold/            notebook do star schema e da OBT (Python)
  Dashboards/      os dois dashboards AI/BI
  Agents/          contexto do agente do workspace
scripts/
  baixar_anac.py   download reproduzível da fonte oficial
docs/
  fontes.md        gerado pelo script: procedência e hash de cada arquivo
```

**Compute:** Serverless. Views materializadas não são suportadas nesse modo, então o projeto usa views
comuns.

---

## Fonte

Dados abertos da ANAC: <https://sistemas.anac.gov.br/dadosabertos/>

- **VRA** (Voo Regular Ativo): um registro por voo, com horários previstos e reais.
- **Aeródromos Públicos**: cadastro com coordenadas.
- **Empresas Aéreas** nacionais e estrangeiras: cadastro dos operadores.
