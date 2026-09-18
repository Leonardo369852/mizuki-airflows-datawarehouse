# Databricks notebook source
# /// script
# [tool.databricks.environment]
# environment_version = "5"
# ///
# DBTITLE 1,Introdução
# MAGIC %md
# MAGIC # Gold — Camada Analítica: Star Schema de Aviação
# MAGIC
# MAGIC A Gold é onde a **modelagem dimensional** acontece. A Silver é espelho do Bronze; a Gold é **visão de negócio**.
# MAGIC
# MAGIC ## Star Schema
# MAGIC
# MAGIC ```
# MAGIC                       dim_tempo
# MAGIC                           |
# MAGIC                           |
# MAGIC   dim_empresa ---- fato_voos ---- dim_aerodromo (origem)
# MAGIC                           |
# MAGIC                           |
# MAGIC   dim_tipo_linha          |       dim_aerodromo (destino)
# MAGIC                           |
# MAGIC                           |
# MAGIC                   dim_situacao_voo
# MAGIC                           |
# MAGIC                           |
# MAGIC                       dim_rota
# MAGIC ```
# MAGIC
# MAGIC ## Filosofia da Gold
# MAGIC
# MAGIC | Silver (espelho) | Gold (negócio) |
# MAGIC | --- | --- |
# MAGIC | Mesma contagem do Bronze | Filtra headers, deduplica |
# MAGIC | Sem join, sem agregação | Joins, enriquecimento, agregação |
# MAGIC | Tipagem e metadados | Regras de negócio (15 min = atraso) |
# MAGIC
# MAGIC ## Decisões de modelagem
# MAGIC
# MAGIC * **Grão da fato**: um registro por voo (VRA)
# MAGIC * **Surrogate keys**: ROW_NUMBER() em cada dimensão, COALESCE para unmatched (sk = 0)
# MAGIC * **Particionamento**: fato_voos por `data_partida_prevista`
# MAGIC * **Flags de pontualidade**: 15 min (padrão ANAC/IATA)
# MAGIC * **dim_rota**: pares origem-destino com distância haversine
# MAGIC * **Headers da Silver**: filtrados aqui, não na Silver

# COMMAND ----------

# DBTITLE 1,Criar schema Gold
# MAGIC %sql
# MAGIC CREATE SCHEMA IF NOT EXISTS mizukiairflows.gold
# MAGIC COMMENT 'Camada Gold: modelo dimensional Star Schema para analytics de aviação ANAC'

# COMMAND ----------

# DBTITLE 1,dim_tempo
# MAGIC %md
# MAGIC ## 1. dim_tempo — Calendário
# MAGIC
# MAGIC Dimensão de tempo cobrindo todo o período de voos (2025-08 a 2026-08). Uma linha por dia, com ano, mês, trimestre, dia da semana, fim de semana e estação.
# MAGIC
# MAGIC A chave primária `sk_tempo` é o inteiro YYYYMMDD, facilitando joins diretos com datas convertidas.

# COMMAND ----------

# DBTITLE 1,Criar dim_tempo
# MAGIC %sql
# MAGIC CREATE OR REPLACE TABLE mizukiairflows.gold.dim_tempo
# MAGIC COMMENT 'Dimensão calendário: uma linha por dia no período de operação de voos'
# MAGIC AS
# MAGIC WITH date_bounds AS (
# MAGIC   SELECT 
# MAGIC     MIN(partida_prevista_data) AS min_date,
# MAGIC     MAX(partida_prevista_data) AS max_date
# MAGIC   FROM mizukiairflows.silver.vra
# MAGIC   WHERE partida_prevista_data IS NOT NULL
# MAGIC ),
# MAGIC date_series AS (
# MAGIC   SELECT explode(sequence(min_date, max_date, INTERVAL 1 DAY)) AS data
# MAGIC   FROM date_bounds
# MAGIC )
# MAGIC SELECT
# MAGIC   INT(YEAR(data) * 10000 + MONTH(data) * 100 + DAY(data)) AS sk_tempo,
# MAGIC   data,
# MAGIC   YEAR(data) AS ano,
# MAGIC   MONTH(data) AS mes,
# MAGIC   DATE_FORMAT(data, 'MMMM') AS nome_mes,
# MAGIC   DAY(data) AS dia,
# MAGIC   DAYOFWEEK(data) AS dia_semana_num,
# MAGIC   DATE_FORMAT(data, 'EEEE') AS nome_dia_semana,
# MAGIC   QUARTER(data) AS trimestre,
# MAGIC   DATE_FORMAT(data, 'yyyy-MM') AS ano_mes,
# MAGIC   CASE WHEN DAYOFWEEK(data) IN (1, 7) THEN TRUE ELSE FALSE END AS fim_de_semana,
# MAGIC   CASE 
# MAGIC     WHEN MONTH(data) IN (12, 1, 2) THEN 'verao'
# MAGIC     WHEN MONTH(data) IN (3, 4, 5) THEN 'outono'
# MAGIC     WHEN MONTH(data) IN (6, 7, 8) THEN 'inverno'
# MAGIC     ELSE 'primavera'
# MAGIC   END AS estacao
# MAGIC FROM date_series

# COMMAND ----------

# DBTITLE 1,dim_empresa
# MAGIC %md
# MAGIC ## 2. dim_empresa — Empresas Aéreas Deduplicadas
# MAGIC
# MAGIC A silver.empresas tem **479.421 registros**, mas apenas **170 ICAOs únicos**. O resto é ruído: 641 headers (`icao = 'icao'`) e 465.258 registros sem ICAO (aviação geral).
# MAGIC
# MAGIC **Estratégia de deduplicação:**
# MAGIC * Filtrar headers e ICAO nulo
# MAGIC * `ROW_NUMBER() PARTITION BY icao` ranqueado por completude (razao_social > situacao > timestamp)
# MAGIC * Manter `rn = 1` — o registro mais completo por empresa

# COMMAND ----------

# DBTITLE 1,Criar dim_empresa
# MAGIC %sql
# MAGIC CREATE OR REPLACE TABLE mizukiairflows.gold.dim_empresa
# MAGIC COMMENT 'Dimensão de empresas aéreas: uma linha por ICAO único, deduplicada e enriquecida'
# MAGIC AS
# MAGIC WITH ranked AS (
# MAGIC   SELECT
# MAGIC     icao,
# MAGIC     iata,
# MAGIC     razao_social,
# MAGIC     cnpj,
# MAGIC     servico,
# MAGIC     cidade,
# MAGIC     uf,
# MAGIC     situacao,
# MAGIC     decisao_operacional,
# MAGIC     validade_operacional,
# MAGIC     origem_cadastro,
# MAGIC     transformado_em,
# MAGIC     ROW_NUMBER() OVER (
# MAGIC       PARTITION BY icao
# MAGIC       ORDER BY
# MAGIC         CASE WHEN razao_social IS NOT NULL AND razao_social != '' THEN 0 ELSE 1 END,
# MAGIC         CASE WHEN situacao IS NOT NULL AND situacao != '' THEN 0 ELSE 1 END,
# MAGIC         transformado_em DESC
# MAGIC     ) AS rn
# MAGIC   FROM mizukiairflows.silver.empresas
# MAGIC   WHERE icao IS NOT NULL
# MAGIC     AND icao != 'icao'
# MAGIC     AND icao != 'ICAO'
# MAGIC     AND icao != ''
# MAGIC )
# MAGIC SELECT
# MAGIC   ROW_NUMBER() OVER (ORDER BY icao) AS sk_empresa,
# MAGIC   icao,
# MAGIC   iata,
# MAGIC   razao_social,
# MAGIC   cnpj,
# MAGIC   servico,
# MAGIC   cidade,
# MAGIC   uf,
# MAGIC   situacao,
# MAGIC   decisao_operacional,
# MAGIC   validade_operacional,
# MAGIC   origem_cadastro,
# MAGIC   CASE 
# MAGIC     WHEN UPPER(COALESCE(situacao, '')) LIKE '%ATIVA%' THEN TRUE
# MAGIC     ELSE FALSE
# MAGIC   END AS flag_ativa
# MAGIC FROM ranked
# MAGIC WHERE rn = 1

# COMMAND ----------

# DBTITLE 1,dim_aerodromo
# MAGIC %md
# MAGIC ## 3. dim_aerodromo — Aeródromos
# MAGIC
# MAGIC A silver.aerodromos já está limpa (496 registros, sem duplicatas). Aqui adicionamos:
# MAGIC * Surrogate key
# MAGIC * `status_operacional` derivado da situação
# MAGIC * `tem_coordenadas` para identificar aeródromos geolocalizáveis
# MAGIC * Coordenadas em formato decimal (latgeopoint/longeopoint) prontas para cálculos

# COMMAND ----------

# DBTITLE 1,Criar dim_aerodromo
# MAGIC %sql
# MAGIC CREATE OR REPLACE TABLE mizukiairflows.gold.dim_aerodromo
# MAGIC COMMENT 'Dimensão de aeródromos: uma linha por ICAO com coordenadas e situação operacional'
# MAGIC AS
# MAGIC SELECT
# MAGIC   ROW_NUMBER() OVER (ORDER BY icao) AS sk_aerodromo,
# MAGIC   icao,
# MAGIC   ciad,
# MAGIC   nome,
# MAGIC   municipio,
# MAGIC   uf_nome,
# MAGIC   municipio_servido,
# MAGIC   uf_servido_nome,
# MAGIC   altitude_m,
# MAGIC   TRY_CAST(latgeopoint AS DOUBLE) AS latitude,
# MAGIC   TRY_CAST(longeopoint AS DOUBLE) AS longitude,
# MAGIC   situacao,
# MAGIC   operacao_diurna,
# MAGIC   operacao_noturna,
# MAGIC   CASE 
# MAGIC     WHEN UPPER(COALESCE(situacao, '')) LIKE '%CADASTRADO%' THEN 'cadastrado'
# MAGIC     WHEN UPPER(COALESCE(situacao, '')) LIKE '%INTERDITADO%' THEN 'interditado'
# MAGIC     ELSE 'outro'
# MAGIC   END AS status_operacional,
# MAGIC   CASE 
# MAGIC     WHEN latgeopoint IS NOT NULL AND longeopoint IS NOT NULL THEN TRUE
# MAGIC     ELSE FALSE
# MAGIC   END AS tem_coordenadas
# MAGIC FROM mizukiairflows.silver.aerodromos
# MAGIC WHERE icao IS NOT NULL AND icao != ''

# COMMAND ----------

# DBTITLE 1,Dims de domínio
# MAGIC %md
# MAGIC ## 4. Dimensões de Domínio
# MAGIC
# MAGIC Duas dimensões pequenas mas fundamentais para o Star Schema:
# MAGIC
# MAGIC * **dim_tipo_linha**: N (Nacional), I (Internacional), G (Geral), C (Cargueiro/Charter)
# MAGIC * **dim_situacao_voo**: REALIZADO, CANCELADO — com flags booleanas para filtros rápidos

# COMMAND ----------

# DBTITLE 1,Criar dim_tipo_linha
# MAGIC %sql
# MAGIC CREATE OR REPLACE TABLE mizukiairflows.gold.dim_tipo_linha
# MAGIC COMMENT 'Dimensão de tipos de linha aérea: Nacional, Internacional, Geral, Cargueiro'
# MAGIC AS
# MAGIC SELECT
# MAGIC   ROW_NUMBER() OVER (ORDER BY codigo) AS sk_tipo_linha,
# MAGIC   codigo,
# MAGIC   CASE codigo
# MAGIC     WHEN 'N' THEN 'Nacional'
# MAGIC     WHEN 'I' THEN 'Internacional'
# MAGIC     WHEN 'G' THEN 'Geral/Privado'
# MAGIC     WHEN 'C' THEN 'Cargueiro/Charter'
# MAGIC     ELSE 'Outro'
# MAGIC   END AS descricao
# MAGIC FROM (
# MAGIC   SELECT DISTINCT codigo_tipo_linha AS codigo
# MAGIC   FROM mizukiairflows.silver.vra
# MAGIC   WHERE codigo_tipo_linha IS NOT NULL
# MAGIC )

# COMMAND ----------

# DBTITLE 1,Criar dim_situacao_voo
# MAGIC %sql
# MAGIC CREATE OR REPLACE TABLE mizukiairflows.gold.dim_situacao_voo
# MAGIC COMMENT 'Dimensão de situação do voo: realizado, cancelado, com flags booleanas'
# MAGIC AS
# MAGIC SELECT
# MAGIC   ROW_NUMBER() OVER (ORDER BY codigo) AS sk_situacao,
# MAGIC   codigo,
# MAGIC   CASE codigo
# MAGIC     WHEN 'REALIZADO' THEN 'Voo realizado normalmente'
# MAGIC     WHEN 'CANCELADO' THEN 'Voo cancelado'
# MAGIC     ELSE 'Outro'
# MAGIC   END AS descricao,
# MAGIC   CASE WHEN codigo = 'REALIZADO' THEN TRUE ELSE FALSE END AS flag_realizado,
# MAGIC   CASE WHEN codigo = 'CANCELADO' THEN TRUE ELSE FALSE END AS flag_cancelado
# MAGIC FROM (
# MAGIC   SELECT DISTINCT situacao_voo AS codigo
# MAGIC   FROM mizukiairflows.silver.vra
# MAGIC   WHERE situacao_voo IS NOT NULL
# MAGIC )

# COMMAND ----------

# DBTITLE 1,dim_rota
# MAGIC %md
# MAGIC ## 5. dim_rota — Rotas com Distância Haversine
# MAGIC
# MAGIC Dimensão única da aviação: cada par origem-destino é uma rota. Aqui calculamos a **distância em km** entre os aeródromos usando a fórmula de Haversine.
# MAGIC
# MAGIC Rotas sem coordenadas (aeródromos não cadastrados) recebem `distancia_km = NULL`.

# COMMAND ----------

# DBTITLE 1,Criar dim_rota
# MAGIC %sql
# MAGIC CREATE OR REPLACE TABLE mizukiairflows.gold.dim_rota
# MAGIC COMMENT 'Dimensão de rotas: pares origem-destino únicos com distância haversine em km'
# MAGIC AS
# MAGIC WITH rotas AS (
# MAGIC   SELECT DISTINCT
# MAGIC     icao_origem,
# MAGIC     icao_destino
# MAGIC   FROM mizukiairflows.silver.vra
# MAGIC   WHERE icao_origem IS NOT NULL AND icao_destino IS NOT NULL
# MAGIC ),
# MAGIC coords AS (
# MAGIC   SELECT
# MAGIC     r.icao_origem,
# MAGIC     r.icao_destino,
# MAGIC     TRY_CAST(ao.latgeopoint AS DOUBLE) AS lat_origem,
# MAGIC     TRY_CAST(ao.longeopoint AS DOUBLE) AS lon_origem,
# MAGIC     TRY_CAST(ad.latgeopoint AS DOUBLE) AS lat_destino,
# MAGIC     TRY_CAST(ad.longeopoint AS DOUBLE) AS lon_destino
# MAGIC   FROM rotas r
# MAGIC   LEFT JOIN mizukiairflows.silver.aerodromos ao ON r.icao_origem = ao.icao
# MAGIC   LEFT JOIN mizukiairflows.silver.aerodromos ad ON r.icao_destino = ad.icao
# MAGIC )
# MAGIC SELECT
# MAGIC   ROW_NUMBER() OVER (ORDER BY icao_origem, icao_destino) AS sk_rota,
# MAGIC   icao_origem,
# MAGIC   icao_destino,
# MAGIC   lat_origem,
# MAGIC   lon_origem,
# MAGIC   lat_destino,
# MAGIC   lon_destino,
# MAGIC   CASE 
# MAGIC     WHEN lat_origem IS NOT NULL AND lon_origem IS NOT NULL 
# MAGIC      AND lat_destino IS NOT NULL AND lon_destino IS NOT NULL
# MAGIC     THEN ROUND(
# MAGIC       2 * 6371 * ASIN(SQRT(
# MAGIC         POWER(SIN(RADIANS(lat_destino - lat_origem) / 2), 2) +
# MAGIC         COS(RADIANS(lat_origem)) * COS(RADIANS(lat_destino)) *
# MAGIC         POWER(SIN(RADIANS(lon_destino - lon_origem) / 2), 2)
# MAGIC       )),
# MAGIC       1
# MAGIC     )
# MAGIC     ELSE NULL
# MAGIC   END AS distancia_km,
# MAGIC   CASE
# MAGIC     WHEN lat_origem IS NOT NULL AND lat_destino IS NOT NULL THEN 'com_coordenadas'
# MAGIC     ELSE 'sem_coordenadas'
# MAGIC   END AS status_distancia
# MAGIC FROM coords

# COMMAND ----------

# Adicionar comentários e tags em todas as tabelas Gold

COMENTARIOS = {
    "mizukiairflows.gold.dim_tempo": {
        "sk_tempo": "Chave surrogate da dimensão tempo (YYYYMMDD como inteiro).",
        "data": "Data completa do dia.",
        "ano": "Ano da data (ex: 2025).",
        "mes": "Mês da data (1-12).",
        "nome_mes": "Nome do mês por extenso em português.",
        "dia": "Dia do mês (1-31).",
        "dia_semana_num": "Número do dia da semana (1=domingo, 7=sabado).",
        "nome_dia_semana": "Nome do dia da semana por extenso.",
        "trimestre": "Trimestre da data (1-4).",
        "ano_mes": "Ano e mês concatenados (ex: 2025-08).",
        "fim_de_semana": "TRUE se a data cai em sabado ou domingo.",
        "estacao": "Estação do ano: verao, outono, inverno, primavera."
    },
    "mizukiairflows.gold.dim_empresa": {
        "sk_empresa": "Chave surrogate da dimensão empresa.",
        "icao": "Código ICAO de tres letras da empresa aérea. Chave de negócio.",
        "iata": "Código IATA de duas letras, comum em sistemas comerciais.",
        "razao_social": "Razão social da empresa aérea.",
        "cnpj": "CNPJ da empresa (apenas nacionais).",
        "servico": "Tipo de serviço aéreo prestado.",
        "cidade": "Cidade da sede da empresa.",
        "uf": "Unidade federativa da sede.",
        "situacao": "Situação operacional: ATIVA, SUSPENSA, etc.",
        "decisao_operacional": "Instrumento operacional da empresa.",
        "validade_operacional": "Validade da autorização operacional.",
        "origem_cadastro": "Origem: nacional ou estrangeira.",
        "flag_ativa": "TRUE se situacao contem 'ATIVA'."
    },
    "mizukiairflows.gold.dim_aerodromo": {
        "sk_aerodromo": "Chave surrogate da dimensão aeródromo.",
        "icao": "Código ICAO de quatro letras do aeródromo.",
        "ciad": "Código CIAD (identificador nacional).",
        "nome": "Nome oficial do aeródromo.",
        "municipio": "Município de localização.",
        "uf_nome": "Nome da UF por extenso.",
        "municipio_servido": "Município principal servido.",
        "uf_servido_nome": "UF do município servido.",
        "altitude_m": "Altitude em metros acima do nível do mar.",
        "latitude": "Latitude em graus decimais (formato geopoint).",
        "longitude": "Longitude em graus decimais (formato geopoint).",
        "situacao": "Situação original: Cadastrado, Interditado, etc.",
        "operacao_diurna": "Indicador de operação diurna.",
        "operacao_noturna": "Indicador de operação noturna.",
        "status_operacional": "Status derivado: cadastrado, interditado, outro.",
        "tem_coordenadas": "TRUE se latitude e longitude estao presentes."
    },
    "mizukiairflows.gold.dim_tipo_linha": {
        "sk_tipo_linha": "Chave surrogate da dimensão tipo de linha.",
        "codigo": "Código original: N, I, G, C.",
        "descricao": "Descrição por extenso do tipo de linha."
    },
    "mizukiairflows.gold.dim_situacao_voo": {
        "sk_situacao": "Chave surrogate da dimensão situação.",
        "codigo": "Código original: REALIZADO, CANCELADO.",
        "descricao": "Descrição por extenso da situação.",
        "flag_realizado": "TRUE se o voo foi realizado.",
        "flag_cancelado": "TRUE se o voo foi cancelado."
    },
    "mizukiairflows.gold.dim_rota": {
        "sk_rota": "Chave surrogate da dimensão rota.",
        "icao_origem": "Código ICAO do aeródromo de origem.",
        "icao_destino": "Código ICAO do aeródromo de destino.",
        "lat_origem": "Latitude de origem em graus decimais.",
        "lon_origem": "Longitude de origem em graus decimais.",
        "lat_destino": "Latitude de destino em graus decimais.",
        "lon_destino": "Longitude de destino em graus decimais.",
        "distancia_km": "Distância em km entre origem e destino (fórmula haversine).",
        "status_distancia": "com_coordenadas ou sem_coordenadas."
    },
    "mizukiairflows.gold.fato_voos": {
        "id_voo": "Chave surrogate da tabela fato. Única por voo.",
        "sk_empresa": "FK para dim_empresa. 0 = não encontrado.",
        "sk_aerodromo_origem": "FK para dim_aerodromo (origem). 0 = não encontrado.",
        "sk_aerodromo_destino": "FK para dim_aerodromo (destino). 0 = não encontrado.",
        "sk_tempo_partida_prevista": "FK para dim_tempo (data prevista).",
        "sk_tempo_partida_real": "FK para dim_tempo ( data real). 0 = cancelado/sem partida.",
        "sk_tipo_linha": "FK para dim_tipo_linha.",
        "sk_situacao": "FK para dim_situacao_voo.",
        "sk_rota": "FK para dim_rota. 0 = rota sem par único.",
        "icao_empresa": "Código ICAO da empresa (chave de negócio).",
        "numero_voo": "Número do voo divulgado pela companhia.",
        "codigo_di": "Código DI de escala e regime.",
        "icao_origem": "Código ICAO do aeródromo de origem (chave de negócio).",
        "icao_destino": "Código ICAO do aeródromo de destino (chave de negócio).",
        "partida_prevista_hora": "Horário previsto de partida (TIMESTAMP).",
        "partida_real_hora": "Horário real de decolagem (TIMESTAMP).",
        "chegada_prevista_hora": "Horário previsto de chegada (TIMESTAMP).",
        "chegada_real_hora": "Horário real de pouso (TIMESTAMP).",
        "atraso_partida_min": "Atraso de partida em minutos. Positivo = atrasou.",
        "atraso_chegada_min": "Atraso de chegada em minutos. Positivo = atrasou.",
        "minutos_recuperados": "Minutos recuperados no ar (atraso_partida - atraso_chegada).",
        "flag_realizado": "TRUE se o voo foi realizado.",
        "flag_cancelado": "TRUE se o voo foi cancelado.",
        "partida_pontual": "TRUE se atraso_partida <= 15 min (padrão ANAC/IATA).",
        "chegada_pontual": "TRUE se atraso_chegada <= 15 min.",
        "partida_atrasada": "TRUE se atraso_partida > 15 min.",
        "partida_atraso_severo": "TRUE se atraso_partida > 60 min.",
        "duracao_voo_min": "Duração real do voo em minutos (partida_real a chegada_real).",
        "periodo_partida": "Periodo do dia: madrugada, manha, tarde, noite.",
        "situacao_voo": "Situação original do voo.",
        "codigo_justificativa": "Código de justificativa para atrasos/cancelamentos.",
        "origem_arquivo": "Arquivo CSV de origem no bronze.",
        "transformado_em": "Timestamp de transformação na silver.",
        "data_partida_prevista": "Data da partida prevista (coluna de particionamento)."
    }
}

for tabela, colunas in COMENTARIOS.items():
    for coluna, comentario in colunas.items():
        spark.sql(f"ALTER TABLE {tabela} ALTER COLUMN {coluna} COMMENT '{comentario}'")
    print(f"✅ {len(colunas)} colunas comentadas em {tabela}")

# Adicionar tags
for tabela in ["dim_tempo", "dim_empresa", "dim_aerodromo", "dim_tipo_linha", 
               "dim_situacao_voo", "dim_rota", "fato_voos", "auditoria_carga", "obt_voos"]:
    spark.sql(f"ALTER TABLE mizukiairflows.gold.{tabela} SET TAGS ('camada' = 'gold', 'dominio' = 'aviacao')")
    print(f"✅ Tags adicionadas: gold.{tabela}")

print("\n✅ Camada Gold documentada e governada")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 6. fato_voos — Tabela Fato Central
# MAGIC
# MAGIC A tabela fato é o coração do Star Schema. Cada linha é um voo do VRA, enriquecido com:
# MAGIC
# MAGIC * **Surrogate keys** para todas as dimensoes (COALESCE para 0 quando não há match)
# MAGIC * **Medidas**: atraso_partida_min, atraso_chegada_min, minutos_recuperados, duracao_voo_min
# MAGIC * **Flags de pontualidade**: partida_pontual, chegada_pontual (limiar ANAC/IATA = 15 min)
# MAGIC * **Flags de gravidade**: partida_atrasada, partida_atraso_severo (> 60 min)
# MAGIC * **Periodo do dia**: madrugada, manha, tarde, noite (baseado na hora prevista)
# MAGIC * **Particionamento**: por `data_partida_prevista` (DATE)
# MAGIC
# MAGIC **Filtro de Gold**: `WHERE icao_empresa IS NOT NULL` — remove headers e registros inválidos

# COMMAND ----------

# MAGIC %md
# MAGIC ## 8. Validação Final
# MAGIC
# MAGIC Consultas para verificar a consistência do Star Schema:
# MAGIC * Contagem de registros por tabela
# MAGIC * Integridade referencial (FK sem match = 0)
# MAGIC * Cobertura de joins
# MAGIC * Distribuição de pontualidade

# COMMAND ----------

# MAGIC %sql
# MAGIC CREATE OR REPLACE TABLE mizukiairflows.gold.fato_voos
# MAGIC COMMENT 'Tabela fato: um registro por voo do VRA, com SKs para dimensoes, medidas e flags de pontualidade'
# MAGIC PARTITIONED BY (data_partida_prevista)
# MAGIC AS
# MAGIC SELECT
# MAGIC   ROW_NUMBER() OVER (ORDER BY v.partida_prevista_data, v.icao_empresa, v.numero_voo) AS id_voo,
# MAGIC   COALESCE(e.sk_empresa, 0) AS sk_empresa,
# MAGIC   COALESCE(ao.sk_aerodromo, 0) AS sk_aerodromo_origem,
# MAGIC   COALESCE(ad.sk_aerodromo, 0) AS sk_aerodromo_destino,
# MAGIC   COALESCE(t.sk_tempo, 0) AS sk_tempo_partida_prevista,
# MAGIC   COALESCE(tr.sk_tempo, 0) AS sk_tempo_partida_real,
# MAGIC   COALESCE(tl.sk_tipo_linha, 0) AS sk_tipo_linha,
# MAGIC   COALESCE(s.sk_situacao, 0) AS sk_situacao,
# MAGIC   COALESCE(r.sk_rota, 0) AS sk_rota,
# MAGIC   v.icao_empresa,
# MAGIC   v.numero_voo,
# MAGIC   v.codigo_di,
# MAGIC   v.icao_origem,
# MAGIC   v.icao_destino,
# MAGIC   v.partida_prevista_hora,
# MAGIC   v.partida_real_hora,
# MAGIC   v.chegada_prevista_hora,
# MAGIC   v.chegada_real_hora,
# MAGIC   v.atraso_partida_min,
# MAGIC   v.atraso_chegada_min,
# MAGIC   v.minutos_recuperados,
# MAGIC   CASE WHEN v.situacao_voo = 'REALIZADO' THEN TRUE ELSE FALSE END AS flag_realizado,
# MAGIC   CASE WHEN v.situacao_voo = 'CANCELADO' THEN TRUE ELSE FALSE END AS flag_cancelado,
# MAGIC   CASE WHEN v.atraso_partida_min IS NOT NULL AND v.atraso_partida_min <= 15 THEN TRUE ELSE FALSE END AS partida_pontual,
# MAGIC   CASE WHEN v.atraso_chegada_min IS NOT NULL AND v.atraso_chegada_min <= 15 THEN TRUE ELSE FALSE END AS chegada_pontual,
# MAGIC   CASE WHEN v.atraso_partida_min IS NOT NULL AND v.atraso_partida_min > 15 THEN TRUE ELSE FALSE END AS partida_atrasada,
# MAGIC   CASE WHEN v.atraso_partida_min IS NOT NULL AND v.atraso_partida_min > 60 THEN TRUE ELSE FALSE END AS partida_atraso_severo,
# MAGIC   CASE WHEN v.partida_real_hora IS NOT NULL AND v.chegada_real_hora IS NOT NULL THEN TIMESTAMPDIFF(MINUTE, v.partida_real_hora, v.chegada_real_hora) ELSE NULL END AS duracao_voo_min,
# MAGIC   CASE WHEN v.partida_prevista_hora IS NOT NULL THEN CASE WHEN HOUR(v.partida_prevista_hora) < 6 THEN 'madrugada' WHEN HOUR(v.partida_prevista_hora) < 12 THEN 'manha' WHEN HOUR(v.partida_prevista_hora) < 18 THEN 'tarde' ELSE 'noite' END ELSE NULL END AS periodo_partida,
# MAGIC   v.situacao_voo,
# MAGIC   v.codigo_justificativa,
# MAGIC   v.origem_arquivo,
# MAGIC   v.transformado_em,
# MAGIC   v.partida_prevista_data AS data_partida_prevista
# MAGIC FROM mizukiairflows.silver.vra v
# MAGIC LEFT JOIN mizukiairflows.gold.dim_empresa e ON v.icao_empresa = e.icao
# MAGIC LEFT JOIN mizukiairflows.gold.dim_aerodromo ao ON v.icao_origem = ao.icao
# MAGIC LEFT JOIN mizukiairflows.gold.dim_aerodromo ad ON v.icao_destino = ad.icao
# MAGIC LEFT JOIN mizukiairflows.gold.dim_tempo t ON v.partida_prevista_data = t.data
# MAGIC LEFT JOIN mizukiairflows.gold.dim_tempo tr ON v.partida_real_data = tr.data
# MAGIC LEFT JOIN mizukiairflows.gold.dim_tipo_linha tl ON v.codigo_tipo_linha = tl.codigo
# MAGIC LEFT JOIN mizukiairflows.gold.dim_situacao_voo s ON v.situacao_voo = s.codigo
# MAGIC LEFT JOIN mizukiairflows.gold.dim_rota r ON v.icao_origem = r.icao_origem AND v.icao_destino = r.icao_destino
# MAGIC WHERE v.icao_empresa IS NOT NULL

# COMMAND ----------

# MAGIC %md
# MAGIC ## 7. Auditoria e View Materializada
# MAGIC
# MAGIC **auditoria_carga**: Registra métricas de cada carga da Gold — total, realizados, cancelados, unmatched.
# MAGIC
# MAGIC **vw_otp_por_empresa**: View com On-Time Performance (OTP) por empresa e mês. OTP é a métrica #1 da aviação: pct de voos com atraso <= 15 min.
# MAGIC
# MAGIC Nota: View regular em vez de materializada pois MV não é suportada em compute serverless.

# COMMAND ----------

# MAGIC %sql
# MAGIC CREATE OR REPLACE TABLE mizukiairflows.gold.auditoria_carga
# MAGIC COMMENT 'Auditoria de carga da Gold: métricas por tabela e execução'
# MAGIC AS
# MAGIC SELECT
# MAGIC   current_timestamp() AS data_carga,
# MAGIC   'fato_voos' AS tabela,
# MAGIC   (SELECT COUNT(*) FROM mizukiairflows.gold.fato_voos) AS registros_total,
# MAGIC   (SELECT COUNT(*) FROM mizukiairflows.gold.fato_voos WHERE flag_realizado = TRUE) AS registros_realizados,
# MAGIC   (SELECT COUNT(*) FROM mizukiairflows.gold.fato_voos WHERE flag_cancelado = TRUE) AS registros_cancelados,
# MAGIC   (SELECT COUNT(*) FROM mizukiairflows.gold.fato_voos WHERE sk_empresa = 0) AS registros_sem_empresa,
# MAGIC   (SELECT COUNT(*) FROM mizukiairflows.gold.fato_voos WHERE sk_aerodromo_origem = 0) AS registros_sem_origem,
# MAGIC   (SELECT COUNT(*) FROM mizukiairflows.gold.fato_voos WHERE sk_aerodromo_destino = 0) AS registros_sem_destino,
# MAGIC   (SELECT COUNT(*) FROM mizukiairflows.gold.dim_empresa) AS dim_empresa_registros,
# MAGIC   (SELECT COUNT(*) FROM mizukiairflows.gold.dim_aerodromo) AS dim_aerodromo_registros,
# MAGIC   (SELECT COUNT(*) FROM mizukiairflows.gold.dim_rota) AS dim_rota_registros,
# MAGIC   'SUCCESS' AS status

# COMMAND ----------

# MAGIC %sql
# MAGIC -- Validação 1: Contagem de registros por tabela Gold
# MAGIC SELECT 'dim_tempo' AS tabela, COUNT(*) AS registros FROM mizukiairflows.gold.dim_tempo
# MAGIC UNION ALL SELECT 'dim_empresa', COUNT(*) FROM mizukiairflows.gold.dim_empresa
# MAGIC UNION ALL SELECT 'dim_aerodromo', COUNT(*) FROM mizukiairflows.gold.dim_aerodromo
# MAGIC UNION ALL SELECT 'dim_tipo_linha', COUNT(*) FROM mizukiairflows.gold.dim_tipo_linha
# MAGIC UNION ALL SELECT 'dim_situacao_voo', COUNT(*) FROM mizukiairflows.gold.dim_situacao_voo
# MAGIC UNION ALL SELECT 'dim_rota', COUNT(*) FROM mizukiairflows.gold.dim_rota
# MAGIC UNION ALL SELECT 'fato_voos', COUNT(*) FROM mizukiairflows.gold.fato_voos

# COMMAND ----------

# MAGIC %sql
# MAGIC -- Validação 2: Integridade referencial e cobertura de joins
# MAGIC SELECT
# MAGIC   'fato_voos' AS tabela,
# MAGIC   COUNT(*) AS total_voos,
# MAGIC   SUM(CASE WHEN sk_empresa = 0 THEN 1 ELSE 0 END) AS sem_empresa,
# MAGIC   SUM(CASE WHEN sk_aerodromo_origem = 0 THEN 1 ELSE 0 END) AS sem_origem,
# MAGIC   SUM(CASE WHEN sk_aerodromo_destino = 0 THEN 1 ELSE 0 END) AS sem_destino,
# MAGIC   SUM(CASE WHEN sk_rota = 0 THEN 1 ELSE 0 END) AS sem_rota,
# MAGIC   ROUND(100.0 * SUM(CASE WHEN flag_realizado THEN 1 ELSE 0 END) / COUNT(*), 1) AS pct_realizado,
# MAGIC   ROUND(100.0 * SUM(CASE WHEN flag_cancelado THEN 1 ELSE 0 END) / COUNT(*), 1) AS pct_cancelado,
# MAGIC   ROUND(100.0 * SUM(CASE WHEN partida_pontual THEN 1 ELSE 0 END) / NULLIF(SUM(CASE WHEN flag_realizado THEN 1 ELSE 0 END), 0), 1) AS pct_partida_pontual
# MAGIC FROM mizukiairflows.gold.fato_voos

# COMMAND ----------

# MAGIC %sql
# MAGIC -- Validação 3: Top 10 empresas por volume de voos
# MAGIC SELECT
# MAGIC   e.razao_social,
# MAGIC   e.icao,
# MAGIC   COUNT(*) AS total_voos,
# MAGIC   SUM(CASE WHEN f.flag_realizado THEN 1 ELSE 0 END) AS realizados,
# MAGIC   SUM(CASE WHEN f.flag_cancelado THEN 1 ELSE 0 END) AS cancelados,
# MAGIC   ROUND(100.0 * SUM(CASE WHEN f.partida_pontual THEN 1 ELSE 0 END) / NULLIF(SUM(CASE WHEN f.flag_realizado THEN 1 ELSE 0 END), 0), 1) AS pct_pontual
# MAGIC FROM mizukiairflows.gold.fato_voos f
# MAGIC JOIN mizukiairflows.gold.dim_empresa e ON f.sk_empresa = e.sk_empresa
# MAGIC GROUP BY e.razao_social, e.icao
# MAGIC ORDER BY total_voos DESC
# MAGIC LIMIT 10

# COMMAND ----------

# MAGIC %sql
# MAGIC -- Validação 4: Auditoria da carga
# MAGIC SELECT * FROM mizukiairflows.gold.auditoria_carga

# COMMAND ----------

# MAGIC %sql
# MAGIC CREATE OR REPLACE VIEW mizukiairflows.gold.vw_otp_por_empresa
# MAGIC COMMENT 'On-Time Performance por empresa e mes: pct de voos com atraso <= 15 min (padrão IATA/ANAC)'
# MAGIC AS
# MAGIC SELECT
# MAGIC   e.razao_social,
# MAGIC   e.icao,
# MAGIC   t.ano,
# MAGIC   t.mes,
# MAGIC   t.nome_mes,
# MAGIC   COUNT(*) AS total_voos,
# MAGIC   SUM(CASE WHEN f.flag_realizado THEN 1 ELSE 0 END) AS voos_realizados,
# MAGIC   SUM(CASE WHEN f.flag_cancelado THEN 1 ELSE 0 END) AS voos_cancelados,
# MAGIC   ROUND(100.0 * SUM(CASE WHEN f.partida_pontual THEN 1 ELSE 0 END) / NULLIF(SUM(CASE WHEN f.flag_realizado THEN 1 ELSE 0 END), 0), 2) AS pct_partida_pontual,
# MAGIC   ROUND(100.0 * SUM(CASE WHEN f.chegada_pontual THEN 1 ELSE 0 END) / NULLIF(SUM(CASE WHEN f.flag_realizado THEN 1 ELSE 0 END), 0), 2) AS pct_chegada_pontual,
# MAGIC   ROUND(AVG(CASE WHEN f.flag_realizado THEN f.atraso_partida_min ELSE NULL END), 1) AS atraso_medio_partida_min,
# MAGIC   ROUND(AVG(CASE WHEN f.flag_realizado THEN f.atraso_chegada_min ELSE NULL END), 1) AS atraso_medio_chegada_min
# MAGIC FROM mizukiairflows.gold.fato_voos f
# MAGIC JOIN mizukiairflows.gold.dim_empresa e ON f.sk_empresa = e.sk_empresa
# MAGIC JOIN mizukiairflows.gold.dim_tempo t ON f.sk_tempo_partida_prevista = t.sk_tempo
# MAGIC GROUP BY e.razao_social, e.icao, t.ano, t.mes, t.nome_mes

# COMMAND ----------

# DBTITLE 1,OBT — One Big Table
# MAGIC %md
# MAGIC ## 8. OBT — One Big Table
# MAGIC
# MAGIC A OBT (One Big Table) é a **fato_voos denormalizada**: um JOIN de todas as dimensões numa única tabela larga. Cada linha continua sendo um voo, mas agora com **nomes descritivos** em vez de surrogate keys.
# MAGIC
# MAGIC ### Vantagens
# MAGIC * **Zero JOINs** para queries de BI — todas as colunas numa só tabela
# MAGIC * **Simplicidade** para dashboards e analistas (sem conhecimento do star schema)
# MAGIC * **Performance** — Spark otimiza uma tabela larga melhor que múltiplos joins em runtime
# MAGIC
# MAGIC ### Decisões de modelagem
# MAGIC * **Grão**: um registro por voo (mesmo do fato_voos)
# MAGIC * **LEFT JOINs**: preserva todos os 1.014.705 voos (unmatched = NULL)
# MAGIC * **dim_aerodromo** joined 2x (origem com prefixo `origem_`, destino com `destino_`)
# MAGIC * **dim_tempo** joined 1x (partida prevista — a principal dimensão temporal)
# MAGIC * **Surrogate keys** (sk_*): não incluídas — substituídas por colunas descritivas
# MAGIC * **Metadata** (transformado_em, origem_arquivo): removidas
# MAGIC * **rota_faixa_distancia**: derivada na OBT para categorização direta
# MAGIC * **Particionamento**: mesmo do fato (`data_partida_prevista`)
# MAGIC
# MAGIC ### Convenção de nomes
# MAGIC
# MAGIC | Prefixo | Origem | Exemplo |
# MAGIC | --- | --- | --- |
# MAGIC | `empresa_` | dim_empresa | empresa_nome, empresa_iata |
# MAGIC | `origem_` | dim_aerodromo (origem) | origem_nome, origem_uf |
# MAGIC | `destino_` | dim_aerodromo (destino) | destino_nome, destino_uf |
# MAGIC | `rota_` | dim_rota | rota_distancia_km |
# MAGIC | (sem prefixo) | dim_tempo / fato | ano, mes, atraso_partida_min |

# COMMAND ----------

# DBTITLE 1,Criar obt_voos
# MAGIC %sql
# MAGIC CREATE OR REPLACE TABLE mizukiairflows.gold.obt_voos
# MAGIC COMMENT 'One Big Table: fato_voos denormalizada com todas as dimensoes — uma linha por voo, pronta para analytics e BI'
# MAGIC PARTITIONED BY (data_partida_prevista)
# MAGIC AS
# MAGIC SELECT
# MAGIC   -- === CHAVE PRIMARIA ===
# MAGIC   f.id_voo,
# MAGIC   
# MAGIC   -- === EMPRESA AEREA ===
# MAGIC   f.icao_empresa,
# MAGIC   e.razao_social    AS empresa_nome,
# MAGIC   e.iata            AS empresa_iata,
# MAGIC   e.servico         AS empresa_servico,
# MAGIC   e.origem_cadastro AS empresa_origem,
# MAGIC   e.situacao        AS empresa_situacao,
# MAGIC   e.flag_ativa      AS empresa_ativa,
# MAGIC   
# MAGIC   -- === AERODROMO ORIGEM ===
# MAGIC   f.icao_origem,
# MAGIC   ao.nome                AS origem_nome,
# MAGIC   ao.municipio           AS origem_municipio,
# MAGIC   ao.uf_nome             AS origem_uf,
# MAGIC   ao.latitude            AS origem_latitude,
# MAGIC   ao.longitude           AS origem_longitude,
# MAGIC   ao.status_operacional  AS origem_status,
# MAGIC   
# MAGIC   -- === AERODROMO DESTINO ===
# MAGIC   f.icao_destino,
# MAGIC   ad.nome                AS destino_nome,
# MAGIC   ad.municipio           AS destino_municipio,
# MAGIC   ad.uf_nome             AS destino_uf,
# MAGIC   ad.latitude            AS destino_latitude,
# MAGIC   ad.longitude           AS destino_longitude,
# MAGIC   ad.status_operacional  AS destino_status,
# MAGIC   
# MAGIC   -- === TEMPO (PARTIDA PREVISTA) ===
# MAGIC   f.data_partida_prevista,
# MAGIC   t.ano,
# MAGIC   t.mes,
# MAGIC   t.nome_mes,
# MAGIC   t.dia,
# MAGIC   t.nome_dia_semana,
# MAGIC   t.trimestre,
# MAGIC   t.ano_mes,
# MAGIC   t.fim_de_semana,
# MAGIC   t.estacao,
# MAGIC   
# MAGIC   -- === TIPO DE LINHA ===
# MAGIC   tl.codigo     AS codigo_tipo_linha,
# MAGIC   tl.descricao  AS tipo_linha,
# MAGIC   
# MAGIC   -- === SITUACAO DO VOO ===
# MAGIC   s.codigo      AS codigo_situacao,
# MAGIC   s.descricao   AS situacao_descricao,
# MAGIC   
# MAGIC   -- === ROTA ===
# MAGIC   r.distancia_km AS rota_distancia_km,
# MAGIC   CASE 
# MAGIC     WHEN r.distancia_km IS NULL THEN 'Sem coordenadas'
# MAGIC     WHEN r.distancia_km < 500    THEN 'Curta (<500km)'
# MAGIC     WHEN r.distancia_km < 1500   THEN 'Media (500-1500km)'
# MAGIC     WHEN r.distancia_km < 3000   THEN 'Longa (1500-3000km)'
# MAGIC     ELSE 'Extra-longa (>3000km)'
# MAGIC   END AS rota_faixa_distancia,
# MAGIC   
# MAGIC   -- === IDENTIFICACAO DO VOO ===
# MAGIC   f.numero_voo,
# MAGIC   f.codigo_di,
# MAGIC   
# MAGIC   -- === HORARIOS ===
# MAGIC   f.partida_prevista_hora,
# MAGIC   f.partida_real_hora,
# MAGIC   f.chegada_prevista_hora,
# MAGIC   f.chegada_real_hora,
# MAGIC   
# MAGIC   -- === MEDIDAS ===
# MAGIC   f.atraso_partida_min,
# MAGIC   f.atraso_chegada_min,
# MAGIC   f.minutos_recuperados,
# MAGIC   f.duracao_voo_min,
# MAGIC   
# MAGIC   -- === FLAGS DE PONTUALIDADE ===
# MAGIC   f.flag_realizado,
# MAGIC   f.flag_cancelado,
# MAGIC   f.partida_pontual,
# MAGIC   f.chegada_pontual,
# MAGIC   f.partida_atrasada,
# MAGIC   f.partida_atraso_severo,
# MAGIC   
# MAGIC   -- === CONTEXTO ===
# MAGIC   f.periodo_partida,
# MAGIC   f.situacao_voo,
# MAGIC   f.codigo_justificativa
# MAGIC FROM mizukiairflows.gold.fato_voos f
# MAGIC LEFT JOIN mizukiairflows.gold.dim_empresa e      ON f.sk_empresa = e.sk_empresa
# MAGIC LEFT JOIN mizukiairflows.gold.dim_aerodromo ao     ON f.sk_aerodromo_origem = ao.sk_aerodromo
# MAGIC LEFT JOIN mizukiairflows.gold.dim_aerodromo ad     ON f.sk_aerodromo_destino = ad.sk_aerodromo
# MAGIC LEFT JOIN mizukiairflows.gold.dim_tempo t          ON f.sk_tempo_partida_prevista = t.sk_tempo
# MAGIC LEFT JOIN mizukiairflows.gold.dim_tipo_linha tl    ON f.sk_tipo_linha = tl.sk_tipo_linha
# MAGIC LEFT JOIN mizukiairflows.gold.dim_situacao_voo s   ON f.sk_situacao = s.sk_situacao
# MAGIC LEFT JOIN mizukiairflows.gold.dim_rota r           ON f.sk_rota = r.sk_rota

# COMMAND ----------

# DBTITLE 1,Validar OBT
# MAGIC %sql
# MAGIC -- Validação OBT: contagem, integridade e cobertura de joins
# MAGIC SELECT
# MAGIC   COUNT(*) AS total_obt,
# MAGIC   (SELECT COUNT(*) FROM mizukiairflows.gold.fato_voos) AS total_fato,
# MAGIC   SUM(CASE WHEN empresa_nome IS NULL THEN 1 ELSE 0 END) AS sem_empresa,
# MAGIC   SUM(CASE WHEN origem_nome IS NULL THEN 1 ELSE 0 END) AS sem_origem,
# MAGIC   SUM(CASE WHEN destino_nome IS NULL THEN 1 ELSE 0 END) AS sem_destino,
# MAGIC   SUM(CASE WHEN rota_distancia_km IS NOT NULL THEN 1 ELSE 0 END) AS com_distancia,
# MAGIC   ROUND(100.0 * SUM(CASE WHEN partida_pontual THEN 1 ELSE 0 END) / NULLIF(SUM(CASE WHEN flag_realizado THEN 1 ELSE 0 END), 0), 1) AS pct_otp,
# MAGIC   COUNT(DISTINCT empresa_nome) AS empresas_unicas,
# MAGIC   COUNT(DISTINCT rota_faixa_distancia) AS faixas_distancia
# MAGIC FROM mizukiairflows.gold.obt_voos

# COMMAND ----------

# MAGIC %md
# MAGIC ## 9. Resumo Final
# MAGIC
# MAGIC ### Star Schema Gold
# MAGIC
# MAGIC | Tabela | Tipo | Registros | Descrição |
# MAGIC | --- | --- | --- | --- |
# MAGIC | dim_tempo | Dimensão | 366 | Calendário 2025-08 a 2026-08 |
# MAGIC | dim_empresa | Dimensão | 169 | Empresas aéreas únicas por ICAO |
# MAGIC | dim_aerodromo | Dimensão | 496 | Aeródromos públicos brasileiros |
# MAGIC | dim_tipo_linha | Dimensão | 4 | N, I, G, C |
# MAGIC | dim_situacao_voo | Dimensão | 2 | REALIZADO, CANCELADO |
# MAGIC | dim_rota | Dimensão | 3.104 | Rotas com distância haversine |
# MAGIC | fato_voos | Fato | 1.014.705 | Voos do VRA com SKs e medidas |
# MAGIC | auditoria_carga | Controle | 1 | Métricas da carga atual |
# MAGIC | vw_otp_por_empresa | View | ~230 | OTP por empresa e mês |
# MAGIC | obt_voos | OBT | 1.014.705 | Fato denormalizada com todas as dimensões |
# MAGIC
# MAGIC ### Regras de Negócio Implementadas
# MAGIC
# MAGIC * **Pontualidade**: atraso <= 15 min = pontual (padrão ANAC/IATA)
# MAGIC * **Atraso severo**: > 60 min
# MAGIC * **Deduplicação**: dim_empresa com 1 registro por ICAO (mais completo)
# MAGIC * **Unmatched**: sk = 0 (LEFT JOIN com COALESCE)
# MAGIC * **Particionamento**: fato por data_partida_prevista
# MAGIC * **OTP médio**: 79.9% partida pontual (realizados)
# MAGIC * **Cancelamentos**: 2,9% (29.145 voos)
# MAGIC * **Unmatched origem/destino**: 10,4% (aeródromos não cadastrados - internacionais/militares)
# MAGIC * **Unmatched empresa**: 0,02% (169 voos)
# MAGIC * **OBT**: obt_voos — fato denormalizada com 7 joins, 0 sk_*, particionada por data_partida_prevista
# MAGIC * **View**: vw_otp_por_empresa (MV não suportada em serverless)

# COMMAND ----------

