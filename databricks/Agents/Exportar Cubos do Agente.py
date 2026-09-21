# Databricks notebook source
# /// script
# [tool.databricks.environment]
# environment_version = "5"
# ///
# DBTITLE 1,Introdução
# MAGIC %md
# MAGIC # Exportar Cubos do Agente Público
# MAGIC
# MAGIC Gera um único arquivo `dados.json` com a Gold **pré-agregada**, para alimentar o demo
# MAGIC público do agente fora do Databricks.
# MAGIC
# MAGIC ## Por que agregar
# MAGIC
# MAGIC A `obt_voos` tem 1.014.705 linhas — não cabe numa página web e não precisa caber. Todas as
# MAGIC perguntas que o README promete responder são respondidas por cubos de algumas milhares de
# MAGIC linhas. O modelo completo continua no Databricks; o demo carrega o resumo.
# MAGIC
# MAGIC ## Convenção de OTP (uma só, para o projeto inteiro)
# MAGIC
# MAGIC ```
# MAGIC OTP = voos pontuais / voos REALIZADOS
# MAGIC ```
# MAGIC
# MAGIC Cancelado não entra no denominador: voo que não saiu não pode ser pontual nem atrasado.
# MAGIC Esta é a mesma conta do notebook Gold e da `vw_otp_por_empresa`. A medida `otp_partida` do
# MAGIC dashboard ANAC divide por `COUNT(1)` — por isso ela sai menor. Vale corrigir lá.
# MAGIC
# MAGIC **Saída:** um JSON em `CAMINHO_SAIDA`, para baixar pela UI (Catalog > Volumes) e commitar
# MAGIC em `agente/dados.json`.

# COMMAND ----------

# DBTITLE 1,Configuração
CAMINHO_SAIDA = "/Volumes/mizukiairflows/bronze/arquivos/export/dados.json"

# Empresas com menos voos que isso não entram no cubo empresa x mês (ruído de cauda longa).
MIN_VOOS_EMPRESA_MES = 500

# COMMAND ----------

# DBTITLE 1,Helper: rodar SQL e devolver registros limpos
import json
import math
import os
from datetime import date, datetime


def limpar(valor):
    """NaN/NaT/Timestamp -> algo que o json.dump aceita."""
    if valor is None:
        return None
    if isinstance(valor, float) and math.isnan(valor):
        return None
    if isinstance(valor, (datetime, date)):
        return valor.isoformat()[:10]
    if hasattr(valor, "item"):  # numpy int64 / bool_ / float64
        return limpar(valor.item())
    return valor


def linhas(sql):
    pdf = spark.sql(sql).toPandas()
    return [{c: limpar(v) for c, v in reg.items()} for reg in pdf.to_dict(orient="records")]


# Fragmentos reusados: OTP sempre sobre realizados.
OTP_PARTIDA = ("ROUND(100.0 * SUM(CASE WHEN partida_pontual THEN 1 ELSE 0 END) "
               "/ NULLIF(SUM(CASE WHEN flag_realizado THEN 1 ELSE 0 END), 0), 1)")
OTP_CHEGADA = ("ROUND(100.0 * SUM(CASE WHEN chegada_pontual THEN 1 ELSE 0 END) "
               "/ NULLIF(SUM(CASE WHEN flag_realizado THEN 1 ELSE 0 END), 0), 1)")

print("Helpers prontos.")

# COMMAND ----------

# DBTITLE 1,Cubo 1 — Visão geral (KPIs)
geral = linhas(f"""
SELECT
  COUNT(*)                                                    AS total_voos,
  SUM(CASE WHEN flag_realizado THEN 1 ELSE 0 END)             AS realizados,
  SUM(CASE WHEN flag_cancelado THEN 1 ELSE 0 END)             AS cancelados,
  ROUND(100.0 * SUM(CASE WHEN flag_cancelado THEN 1 ELSE 0 END) / COUNT(*), 2) AS pct_cancelado,
  {OTP_PARTIDA}                                               AS otp_partida,
  {OTP_CHEGADA}                                               AS otp_chegada,
  SUM(CASE WHEN partida_atraso_severo THEN 1 ELSE 0 END)      AS atraso_severo,
  ROUND(AVG(CASE WHEN flag_realizado THEN atraso_partida_min END), 1) AS atraso_medio_partida,
  ROUND(AVG(CASE WHEN flag_realizado THEN atraso_chegada_min END), 1) AS atraso_medio_chegada,
  ROUND(AVG(minutos_recuperados), 1)                          AS minutos_recuperados_medio,
  ROUND(AVG(duracao_voo_min), 1)                              AS duracao_media_min,
  COUNT(DISTINCT icao_empresa)                                AS empresas,
  COUNT(DISTINCT icao_origem)                                 AS aerodromos_origem,
  COUNT(DISTINCT CONCAT(icao_origem, '>', icao_destino))      AS rotas,
  MIN(data_partida_prevista)                                  AS periodo_inicio,
  MAX(data_partida_prevista)                                  AS periodo_fim
FROM mizukiairflows.gold.obt_voos
""")[0]

print(json.dumps(geral, indent=2, ensure_ascii=False))

# COMMAND ----------

# DBTITLE 1,Cubo 2 — Empresas
empresas = linhas(f"""
SELECT
  icao_empresa                                     AS icao,
  COALESCE(empresa_nome, '(sem cadastro)')         AS nome,
  empresa_iata                                     AS iata,
  empresa_origem                                   AS origem_cadastro,
  empresa_servico                                  AS servico,
  empresa_ativa                                    AS ativa,
  COUNT(*)                                         AS voos,
  SUM(CASE WHEN flag_realizado THEN 1 ELSE 0 END)  AS realizados,
  SUM(CASE WHEN flag_cancelado THEN 1 ELSE 0 END)  AS cancelados,
  ROUND(100.0 * SUM(CASE WHEN flag_cancelado THEN 1 ELSE 0 END) / COUNT(*), 2) AS pct_cancelado,
  {OTP_PARTIDA}                                    AS otp_partida,
  {OTP_CHEGADA}                                    AS otp_chegada,
  ROUND(AVG(CASE WHEN flag_realizado THEN atraso_partida_min END), 1) AS atraso_medio_partida,
  ROUND(AVG(CASE WHEN flag_realizado THEN atraso_chegada_min END), 1) AS atraso_medio_chegada,
  ROUND(AVG(minutos_recuperados), 1)               AS minutos_recuperados_medio,
  SUM(CASE WHEN partida_atraso_severo THEN 1 ELSE 0 END) AS atraso_severo,
  COUNT(DISTINCT CONCAT(icao_origem, '>', icao_destino)) AS rotas
FROM mizukiairflows.gold.obt_voos
GROUP BY icao_empresa, empresa_nome, empresa_iata, empresa_origem, empresa_servico, empresa_ativa
ORDER BY voos DESC
""")

print(f"{len(empresas)} empresas")

# COMMAND ----------

# DBTITLE 1,Cubo 3 — Evolução mensal
mensal = linhas(f"""
SELECT
  ano_mes,
  MIN(nome_mes)                                    AS nome_mes,
  MIN(ano)                                         AS ano,
  COUNT(*)                                         AS voos,
  SUM(CASE WHEN flag_realizado THEN 1 ELSE 0 END)  AS realizados,
  SUM(CASE WHEN flag_cancelado THEN 1 ELSE 0 END)  AS cancelados,
  ROUND(100.0 * SUM(CASE WHEN flag_cancelado THEN 1 ELSE 0 END) / COUNT(*), 2) AS pct_cancelado,
  {OTP_PARTIDA}                                    AS otp_partida,
  ROUND(AVG(CASE WHEN flag_realizado THEN atraso_partida_min END), 1) AS atraso_medio_partida
FROM mizukiairflows.gold.obt_voos
GROUP BY ano_mes
ORDER BY ano_mes
""")

print(f"{len(mensal)} meses")

# COMMAND ----------

# DBTITLE 1,Cubo 4 — Empresa x mês
empresa_mes = linhas(f"""
SELECT
  icao_empresa                                     AS icao,
  ano_mes,
  COUNT(*)                                         AS voos,
  SUM(CASE WHEN flag_cancelado THEN 1 ELSE 0 END)  AS cancelados,
  {OTP_PARTIDA}                                    AS otp_partida,
  ROUND(AVG(CASE WHEN flag_realizado THEN atraso_partida_min END), 1) AS atraso_medio_partida
FROM mizukiairflows.gold.obt_voos
WHERE icao_empresa IN (
  SELECT icao_empresa FROM mizukiairflows.gold.obt_voos
  GROUP BY icao_empresa HAVING COUNT(*) >= {MIN_VOOS_EMPRESA_MES}
)
GROUP BY icao_empresa, ano_mes
ORDER BY icao, ano_mes
""")

print(f"{len(empresa_mes)} pares empresa x mes")

# COMMAND ----------

# DBTITLE 1,Cubo 5 — Rotas
rotas = linhas(f"""
SELECT
  icao_origem,
  icao_destino,
  MIN(origem_municipio)                            AS origem_municipio,
  MIN(origem_uf)                                   AS origem_uf,
  MIN(destino_municipio)                           AS destino_municipio,
  MIN(destino_uf)                                  AS destino_uf,
  MAX(rota_distancia_km)                           AS distancia_km,
  MIN(rota_faixa_distancia)                        AS faixa,
  COUNT(*)                                         AS voos,
  SUM(CASE WHEN flag_cancelado THEN 1 ELSE 0 END)  AS cancelados,
  {OTP_PARTIDA}                                    AS otp_partida,
  ROUND(AVG(duracao_voo_min), 1)                   AS duracao_media_min
FROM mizukiairflows.gold.obt_voos
GROUP BY icao_origem, icao_destino
ORDER BY voos DESC
""")

print(f"{len(rotas)} rotas")

# COMMAND ----------

# DBTITLE 1,Cubo 6 — Aeródromos de origem (para o mapa)
aerodromos = linhas(f"""
SELECT
  icao_origem                                      AS icao,
  MIN(origem_nome)                                 AS nome,
  MIN(origem_municipio)                            AS municipio,
  MIN(origem_uf)                                   AS uf,
  MAX(origem_latitude)                             AS latitude,
  MAX(origem_longitude)                            AS longitude,
  COUNT(*)                                         AS voos,
  SUM(CASE WHEN flag_cancelado THEN 1 ELSE 0 END)  AS cancelados,
  {OTP_PARTIDA}                                    AS otp_partida
FROM mizukiairflows.gold.obt_voos
WHERE origem_latitude IS NOT NULL
GROUP BY icao_origem
ORDER BY voos DESC
""")

print(f"{len(aerodromos)} aerodromos com coordenada")

# COMMAND ----------

# DBTITLE 1,Cubo 7 — Cortes categóricos
def corte(coluna, rotulo):
    return linhas(f"""
      SELECT
        '{rotulo}'                                       AS dimensao,
        CAST(COALESCE(CAST({coluna} AS STRING), '(sem valor)') AS STRING) AS categoria,
        COUNT(*)                                         AS voos,
        SUM(CASE WHEN flag_cancelado THEN 1 ELSE 0 END)  AS cancelados,
        {OTP_PARTIDA}                                    AS otp_partida,
        ROUND(AVG(CASE WHEN flag_realizado THEN atraso_partida_min END), 1) AS atraso_medio_partida
      FROM mizukiairflows.gold.obt_voos
      GROUP BY {coluna}
      ORDER BY voos DESC
    """)


cortes = (
    corte("tipo_linha", "tipo_linha")
    + corte("rota_faixa_distancia", "faixa_distancia")
    + corte("periodo_partida", "periodo_partida")
    + corte("nome_dia_semana", "dia_semana")
    + corte("fim_de_semana", "fim_de_semana")
    + corte("estacao", "estacao")
    + corte("situacao_descricao", "situacao")
    + corte("empresa_origem", "origem_empresa")
)

print(f"{len(cortes)} linhas de corte")

# COMMAND ----------

# DBTITLE 1,Cubo 8 — Justificativas de cancelamento
justificativas = linhas("""
SELECT
  COALESCE(NULLIF(codigo_justificativa, ''), '(sem codigo)') AS codigo,
  COUNT(*) AS cancelados
FROM mizukiairflows.gold.obt_voos
WHERE flag_cancelado
GROUP BY codigo_justificativa
ORDER BY cancelados DESC
""")

print(f"{len(justificativas)} justificativas")

# COMMAND ----------

# DBTITLE 1,Montar e gravar o JSON
from datetime import timezone

pacote = {
    "meta": {
        "projeto": "Mizuki Airflows",
        "fonte": "ANAC - dados abertos (sistemas.anac.gov.br/dadosabertos)",
        "origem": "mizukiairflows.gold.obt_voos",
        "gerado_em": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "definicao_otp": "voos pontuais / voos realizados; pontual = atraso de partida <= 15 min (ANAC/IATA)",
        "definicao_atraso_severo": "atraso de partida > 60 min",
        "nota": "Agregados da camada Gold. O modelo dimensional completo (1.014.705 voos) roda no Databricks.",
    },
    "geral": geral,
    "empresas": empresas,
    "mensal": mensal,
    "empresa_mes": empresa_mes,
    "rotas": rotas,
    "aerodromos": aerodromos,
    "cortes": cortes,
    "justificativas": justificativas,
}

os.makedirs(os.path.dirname(CAMINHO_SAIDA), exist_ok=True)
with open(CAMINHO_SAIDA, "w", encoding="utf-8") as fp:
    json.dump(pacote, fp, ensure_ascii=False, separators=(",", ":"))

tamanho_kb = os.path.getsize(CAMINHO_SAIDA) / 1024
print(f"Gravado em {CAMINHO_SAIDA}")
print(f"Tamanho: {tamanho_kb:,.0f} KB\n")
for chave, valor in pacote.items():
    if chave in ("meta", "geral"):
        continue
    print(f"  {chave:<16} {len(valor):>6} linhas")

# COMMAND ----------

# DBTITLE 1,Como baixar
# MAGIC %md
# MAGIC ## Baixar o arquivo
# MAGIC
# MAGIC **Pela UI:** Catalog > Volumes > `mizukiairflows` > `bronze` > `arquivos` > `export` >
# MAGIC `dados.json` > botão de download.
# MAGIC
# MAGIC **Pela CLI:**
# MAGIC
# MAGIC ```bash
# MAGIC databricks fs cp \
# MAGIC   dbfs:/Volumes/mizukiairflows/bronze/arquivos/export/dados.json \
# MAGIC   agente/dados.json
# MAGIC ```
# MAGIC
# MAGIC Depois commite em `agente/dados.json` na raiz do repositório.
