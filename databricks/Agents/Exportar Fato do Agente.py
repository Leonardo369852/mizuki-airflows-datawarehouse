# Databricks notebook source
# /// script
# [tool.databricks.environment]
# environment_version = "5"
# ///
# DBTITLE 1,Introdução
# MAGIC %md
# MAGIC # Exportar Fato do Agente Público
# MAGIC
# MAGIC Gera cinco Parquet pequenos que viram um **banco consultável no navegador** do visitante
# MAGIC (DuckDB compilado em WebAssembly). O agente público escreve SQL de verdade contra eles.
# MAGIC
# MAGIC ## Diferença em relação a `Exportar Cubos do Agente`
# MAGIC
# MAGIC | | Cubos (`dados.json`) | Fato (este notebook) |
# MAGIC |---|---|---|
# MAGIC | Forma | respostas já calculadas | tabelas consultáveis |
# MAGIC | Perguntas | as que eu previ | qualquer agregação |
# MAGIC | Consumo | texto no prompt do LLM | `SELECT` executado no navegador |
# MAGIC
# MAGIC Os dois convivem: o JSON alimenta os KPIs e gráficos fixos da página, o Parquet alimenta
# MAGIC o chat.
# MAGIC
# MAGIC ## Duas decisões que sustentam o resto
# MAGIC
# MAGIC **1. Somas e contagens, nunca médias.** Se o fato guardasse `atraso_medio`, qualquer
# MAGIC reagregação do visitante viraria média de média — errada sempre que os grupos têm tamanhos
# MAGIC diferentes, que é o caso. Guardando `soma_atraso` e `com_atraso`, a média correta é
# MAGIC `SUM(soma_atraso) / SUM(com_atraso)` em **qualquer** nível de corte.
# MAGIC
# MAGIC **2. Fato estreito, dimensões à parte.** `origem_uf`, `origem_municipio`, `latitude`,
# MAGIC `rota_distancia_km` e `estacao` não entram no fato: eles são função das chaves e viriam
# MAGIC repetidos milhões de vezes. Ficam em quatro dimensões minúsculas, e o DuckDB junta.
# MAGIC
# MAGIC ## Saída
# MAGIC
# MAGIC Cinco Parquet + um `manifest.json` em `DIR_SAIDA`. Baixar pela UI
# MAGIC (Catalog > Volumes) e commitar em `agente/dados/`.

# COMMAND ----------

# DBTITLE 1,Configuração
DIR_SAIDA = "/Volumes/mizukiairflows/bronze/arquivos/export"

# Limites de plausibilidade do atraso de partida, em minutos.
#
# A fonte tem timestamps invertidos: existem empresas com atraso médio de -4.313 min (três dias
# "adiantada") e rotas com duração média de 175.454 min. Isso não é atraso, é erro de captura.
#
# Não removo essas linhas — elas continuam no fato e nas somas brutas, porque descartar em
# silêncio é pior que reportar. Mas exporto TAMBÉM uma soma restrita à faixa plausível, para a
# página poder mostrar o número honesto e declarar o corte ao lado.
ATRASO_MIN_PLAUSIVEL = -60      # sair 1h adiantado já é raro, mas acontece
ATRASO_MAX_PLAUSIVEL = 1440     # 24h de atraso é o teto do que faz sentido chamar de atraso

# Aeródromos com menos partidas que isso não entram na dimensão (não aparecem no mapa).
MIN_PARTIDAS_AERODROMO = 100

# COMMAND ----------

# DBTITLE 1,Helpers
import json
import os
import unicodedata

os.makedirs(DIR_SAIDA, exist_ok=True)


def corrigir_encoding(texto):
    """Repara mojibake de UTF-8 lido como ISO-8859-1.

    A ingestão Bronze lê o VRA com encoding='ISO-8859-1'. O arquivo de empresas nacionais
    está em ISO-8859-1 mesmo e sai correto; o de estrangeiras está em UTF-8 e sai corrompido
    ('TRANSPORTES AÃREOS', 'COMPAÃIA PANAMEÃA', 'IBÃRIA').

    A ida-e-volta latin-1 -> utf-8 desfaz exatamente essa troca. Em texto que já está correto
    ela falha (byte inválido em UTF-8) e o original é preservado.

    A correção definitiva é no notebook Bronze, não aqui. Isto é remendo de exibição.
    """
    if texto is None:
        return None
    try:
        reparado = texto.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return texto
    # Só aceita o reparo se ele produziu texto imprimível.
    if any(unicodedata.category(c) in ("Cc", "Cn") for c in reparado):
        return texto
    return reparado


def salvar(df_spark, nome, ordem=None):
    """Spark -> pandas -> um único Parquet. Devolve (linhas, bytes)."""
    pdf = df_spark.toPandas()
    if ordem:
        pdf = pdf.sort_values(ordem).reset_index(drop=True)
    caminho = f"{DIR_SAIDA}/{nome}.parquet"
    pdf.to_parquet(caminho, index=False, compression="snappy")
    tamanho = os.path.getsize(caminho)
    print(f"  {nome:<20} {len(pdf):>9,} linhas   {tamanho / 1024:>8,.0f} KB")
    return len(pdf), tamanho, pdf


print(f"Saída: {DIR_SAIDA}")
print(f"Faixa plausível de atraso: [{ATRASO_MIN_PLAUSIVEL}, {ATRASO_MAX_PLAUSIVEL}] min")

# COMMAND ----------

# DBTITLE 1,Tabela 1 — fato_voos (o grão)
# MAGIC %md
# MAGIC ### Grão
# MAGIC
# MAGIC `ano_mes × empresa × origem × destino × situação × período × fim de semana × tipo de linha`
# MAGIC
# MAGIC Oito chaves. As quatro primeiras são as que o visitante vai cortar; as quatro últimas são
# MAGIC quase gratuitas em cardinalidade porque já são altamente correlacionadas com as primeiras
# MAGIC (uma rota de uma empresa num mês costuma ter um tipo de linha só e voar em poucos períodos).
# MAGIC
# MAGIC `ano_mes` é `NULL` nos **30.800 voos sem data de partida prevista** (3,0% do total). Eles
# MAGIC continuam aqui — é justamente o que explica o OTP global ser menor que o de todos os doze
# MAGIC meses individuais. Sumir com eles esconderia o achado.
# MAGIC
# MAGIC Se a contagem de linhas sair acima de ~400 mil, o caminho de corte é nesta ordem:
# MAGIC `periodo_partida` → `fim_de_semana` → `codigo_tipo_linha` → `icao_destino`.

# COMMAND ----------

fato_sql = f"""
SELECT
  ano_mes,
  icao_empresa,
  icao_origem,
  icao_destino,
  situacao_voo,
  periodo_partida,
  fim_de_semana,
  codigo_tipo_linha,

  -- Contagens: todo denominador possível sai daqui.
  COUNT(*)                                                             AS voos,
  SUM(CASE WHEN flag_realizado        THEN 1 ELSE 0 END)                AS realizados,
  SUM(CASE WHEN flag_cancelado        THEN 1 ELSE 0 END)                AS cancelados,
  SUM(CASE WHEN partida_pontual       THEN 1 ELSE 0 END)                AS partidas_pontuais,
  SUM(CASE WHEN chegada_pontual       THEN 1 ELSE 0 END)                AS chegadas_pontuais,
  SUM(CASE WHEN partida_atrasada      THEN 1 ELSE 0 END)                AS partidas_atrasadas,
  SUM(CASE WHEN partida_atraso_severo THEN 1 ELSE 0 END)                AS partidas_severas,

  -- Somas + contagem do que não é nulo: a média correta é soma/contagem em qualquer nível.
  SUM(CASE WHEN atraso_partida_min IS NOT NULL THEN 1 ELSE 0 END)       AS com_atraso_partida,
  SUM(atraso_partida_min)                                               AS soma_atraso_partida,
  SUM(CASE WHEN atraso_chegada_min IS NOT NULL THEN 1 ELSE 0 END)       AS com_atraso_chegada,
  SUM(atraso_chegada_min)                                               AS soma_atraso_chegada,
  SUM(CASE WHEN duracao_voo_min IS NOT NULL THEN 1 ELSE 0 END)          AS com_duracao,
  SUM(duracao_voo_min)                                                  AS soma_duracao,

  -- Mesma medida, restrita à faixa plausível. Ver nota de configuração.
  SUM(CASE WHEN atraso_partida_min BETWEEN {ATRASO_MIN_PLAUSIVEL} AND {ATRASO_MAX_PLAUSIVEL}
           THEN 1 ELSE 0 END)                                           AS com_atraso_plausivel,
  SUM(CASE WHEN atraso_partida_min BETWEEN {ATRASO_MIN_PLAUSIVEL} AND {ATRASO_MAX_PLAUSIVEL}
           THEN atraso_partida_min ELSE 0 END)                          AS soma_atraso_plausivel

FROM mizukiairflows.gold.obt_voos
GROUP BY ALL
"""

print("fato_voos")
n_fato, b_fato, pdf_fato = salvar(
    spark.sql(fato_sql),
    "fato_voos",
    ordem=["ano_mes", "icao_empresa", "icao_origem", "icao_destino"],
)

total_voos = int(pdf_fato["voos"].sum())
print(f"\n  Compressão: 1.014.705 linhas da OBT -> {n_fato:,} no fato "
      f"({1014705 / max(n_fato, 1):.1f}x)")
print(f"  Soma de voos: {total_voos:,}  (tem de fechar com a OBT)")

# COMMAND ----------

# DBTITLE 1,Tabela 2 — dim_empresa
# MAGIC %md
# MAGIC `razao_social` vem da Bronze com mojibake nas estrangeiras — corrigido aqui pelo
# MAGIC `corrigir_encoding`. `nacional` separa os dois cadastros de origem, que é o corte que
# MAGIC explica a maior diferença de pontualidade do dataset (81,8% contra 67,2%).

# COMMAND ----------

emp = spark.sql("""
SELECT
  icao_empresa,
  MAX(empresa_nome)     AS nome,
  MAX(empresa_iata)     AS iata,
  MAX(empresa_servico)  AS servico,
  MAX(empresa_origem)   AS origem_cadastro,
  MAX(empresa_situacao) AS situacao,
  COUNT(*)              AS voos_no_periodo
FROM mizukiairflows.gold.obt_voos
WHERE icao_empresa IS NOT NULL
GROUP BY icao_empresa
""").toPandas()

emp["nome"] = emp["nome"].map(corrigir_encoding)
emp["nacional"] = emp["origem_cadastro"].str.contains("nacion", case=False, na=False)

reparados = spark.sql("""
SELECT COUNT(DISTINCT icao_empresa) AS n FROM mizukiairflows.gold.obt_voos
WHERE empresa_nome RLIKE 'Ã'
""").collect()[0]["n"]

print("dim_empresa")
import pandas as pd
n_emp, b_emp, _ = salvar(spark.createDataFrame(emp), "dim_empresa", ordem=["icao_empresa"])
print(f"\n  Nomes com mojibake na origem: {reparados}")
print(f"  Nacionais: {int(emp['nacional'].sum())}   Estrangeiras: {int((~emp['nacional']).sum())}")

# COMMAND ----------

# DBTITLE 1,Tabela 3 — dim_aerodromo
# MAGIC %md
# MAGIC Um aeródromo aparece como origem e como destino. A dimensão é uma só — o DuckDB junta
# MAGIC duas vezes com apelidos diferentes, exatamente como a `fato_voos` faz no Databricks.
# MAGIC
# MAGIC `latitude`/`longitude` vêm daqui e são o que permite ao agente desenhar o mapa.

# COMMAND ----------

aero_sql = f"""
WITH partidas AS (
  SELECT icao_origem AS icao, COUNT(*) AS partidas
  FROM mizukiairflows.gold.obt_voos GROUP BY icao_origem
),
chegadas AS (
  SELECT icao_destino AS icao, COUNT(*) AS chegadas
  FROM mizukiairflows.gold.obt_voos GROUP BY icao_destino
),
cadastro AS (
  SELECT icao_origem AS icao, MAX(origem_nome) AS nome, MAX(origem_municipio) AS municipio,
         MAX(origem_uf) AS uf, MAX(origem_latitude) AS latitude, MAX(origem_longitude) AS longitude
  FROM mizukiairflows.gold.obt_voos WHERE icao_origem IS NOT NULL GROUP BY icao_origem
  UNION ALL
  SELECT icao_destino AS icao, MAX(destino_nome), MAX(destino_municipio),
         MAX(destino_uf), MAX(destino_latitude), MAX(destino_longitude)
  FROM mizukiairflows.gold.obt_voos WHERE icao_destino IS NOT NULL GROUP BY icao_destino
)
SELECT
  c.icao,
  MAX(c.nome)      AS nome,
  MAX(c.municipio) AS municipio,
  MAX(c.uf)        AS uf,
  MAX(c.latitude)  AS latitude,
  MAX(c.longitude) AS longitude,
  COALESCE(MAX(p.partidas), 0) AS partidas,
  COALESCE(MAX(ch.chegadas), 0) AS chegadas
FROM cadastro c
LEFT JOIN partidas p  ON c.icao = p.icao
LEFT JOIN chegadas ch ON c.icao = ch.icao
GROUP BY c.icao
HAVING COALESCE(MAX(p.partidas), 0) + COALESCE(MAX(ch.chegadas), 0) >= {MIN_PARTIDAS_AERODROMO}
"""

print("dim_aerodromo")
n_aero, b_aero, pdf_aero = salvar(spark.sql(aero_sql), "dim_aerodromo", ordem=["icao"])
sem_coord = int(pdf_aero["latitude"].isna().sum())
sem_munic = int(pdf_aero["municipio"].isna().sum())
print(f"\n  Sem coordenadas: {sem_coord}   Sem município: {sem_munic}")

# COMMAND ----------

# DBTITLE 1,Tabela 4 — dim_rota
# MAGIC %md
# MAGIC `distancia_km` é Haversine sobre as coordenadas, calculada na Gold.
# MAGIC
# MAGIC `origem_igual_destino` marca as rotas do tipo SBGR→SBGR (568 voos, 0 km). São elas que
# MAGIC puxam a distância mínima da `dim_rota` para zero e envenenam qualquer média de distância.
# MAGIC Ficam no export, sinalizadas, para o agente poder excluí-las quando a pergunta for sobre
# MAGIC distância — e para poder falar delas quando a pergunta for sobre qualidade.

# COMMAND ----------

rota_sql = """
SELECT
  icao_origem,
  icao_destino,
  MAX(rota_distancia_km)     AS distancia_km,
  MAX(rota_faixa_distancia)  AS faixa_distancia,
  (icao_origem = icao_destino) AS origem_igual_destino,
  COUNT(*) AS voos
FROM mizukiairflows.gold.obt_voos
WHERE icao_origem IS NOT NULL AND icao_destino IS NOT NULL
GROUP BY icao_origem, icao_destino
"""

print("dim_rota")
n_rota, b_rota, pdf_rota = salvar(spark.sql(rota_sql), "dim_rota",
                                  ordem=["icao_origem", "icao_destino"])
circulares = int(pdf_rota["origem_igual_destino"].sum())
voos_circulares = int(pdf_rota.loc[pdf_rota["origem_igual_destino"], "voos"].sum())
print(f"\n  Rotas com origem = destino: {circulares} ({voos_circulares:,} voos)")

# COMMAND ----------

# DBTITLE 1,Tabela 5 — dim_tempo
# MAGIC %md
# MAGIC Uma linha por `ano_mes`, mais a linha de `NULL` — que é o marcador dos 30.800 voos sem
# MAGIC data prevista. `ordem` existe porque o agente precisa ordenar cronologicamente sem
# MAGIC depender de ordenação alfabética de texto.

# COMMAND ----------

tempo_sql = """
SELECT
  ano_mes,
  CAST(MAX(ano) AS INT)       AS ano,
  CAST(MAX(mes) AS INT)       AS mes,
  /* O nome_mes da OBT vem do date_format do Spark com locale padrão, ou seja em
     inglês ("August"), e repete entre anos: agosto de 2025 e agosto de 2026 teriam
     o mesmo rótulo, e um GROUP BY nome_mes somaria os dois numa linha só. Aqui ele
     é reconstruído em português e qualificado pelo ano, o que conserta o idioma e
     torna a coluna única por linha. Quem quiser agrupar por mês do ano ainda tem
     a coluna `mes`. */
  CASE MAX(mes)
    WHEN 1 THEN 'jan' WHEN 2 THEN 'fev' WHEN 3  THEN 'mar' WHEN 4  THEN 'abr'
    WHEN 5 THEN 'mai' WHEN 6 THEN 'jun' WHEN 7  THEN 'jul' WHEN 8  THEN 'ago'
    WHEN 9 THEN 'set' WHEN 10 THEN 'out' WHEN 11 THEN 'nov' WHEN 12 THEN 'dez'
  END || '/' || CAST(MAX(ano) AS INT)                       AS nome_mes,
  CAST(MAX(trimestre) AS INT) AS trimestre,
  MAX(estacao)   AS estacao,
  MIN(data_partida_prevista) AS primeiro_dia,
  MAX(data_partida_prevista) AS ultimo_dia,
  COUNT(DISTINCT data_partida_prevista) AS dias_com_voo,
  COUNT(*) AS voos,
  COALESCE(CAST(MAX(ano) * 100 + MAX(mes) AS INT), 999999) AS ordem
FROM mizukiairflows.gold.obt_voos
GROUP BY ano_mes
"""

print("dim_tempo")
n_tempo, b_tempo, pdf_tempo = salvar(spark.sql(tempo_sql), "dim_tempo", ordem=["ordem"])
print()
print(pdf_tempo[["ano_mes", "dias_com_voo", "voos"]].to_string(index=False))

# COMMAND ----------

# DBTITLE 1,Manifest — o que a página precisa saber sobre o export
# MAGIC %md
# MAGIC O manifest carrega contagens, tamanhos e as **definições das métricas**. A página mostra
# MAGIC "dados gerados em X" a partir dele, e ele é a prova de que os números da página vêm de
# MAGIC uma execução datada e não de digitação manual.

# COMMAND ----------

qualidade = spark.sql(f"""
SELECT
  COUNT(*)                                                              AS total_voos,
  SUM(CASE WHEN ano_mes IS NULL THEN 1 ELSE 0 END)                      AS sem_data_prevista,
  SUM(CASE WHEN flag_cancelado THEN 1 ELSE 0 END)                       AS cancelados,
  COUNT(DISTINCT CASE WHEN flag_cancelado THEN codigo_justificativa END) AS justificativas_distintas,
  COUNT(DISTINCT icao_empresa)                                          AS empresas,
  COUNT(DISTINCT icao_origem)                                           AS origens,
  ROUND(100.0 * SUM(CASE WHEN partida_pontual THEN 1 ELSE 0 END)
        / NULLIF(SUM(CASE WHEN flag_realizado THEN 1 ELSE 0 END), 0), 1) AS otp_global,
  ROUND(100.0 * SUM(CASE WHEN partida_pontual AND ano_mes IS NOT NULL THEN 1 ELSE 0 END)
        / NULLIF(SUM(CASE WHEN flag_realizado AND ano_mes IS NOT NULL THEN 1 ELSE 0 END), 0), 1)
                                                                        AS otp_com_data,
  SUM(CASE WHEN atraso_partida_min < {ATRASO_MIN_PLAUSIVEL}
             OR atraso_partida_min > {ATRASO_MAX_PLAUSIVEL} THEN 1 ELSE 0 END) AS atrasos_implausiveis
FROM mizukiairflows.gold.obt_voos
""").collect()[0].asDict()

from datetime import datetime, timezone

manifest = {
    "gerado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    "origem": "mizukiairflows.gold.obt_voos",
    "tabelas": {
        "fato_voos":     {"linhas": n_fato,  "bytes": b_fato},
        "dim_empresa":   {"linhas": n_emp,   "bytes": b_emp},
        "dim_aerodromo": {"linhas": n_aero,  "bytes": b_aero},
        "dim_rota":      {"linhas": n_rota,  "bytes": b_rota},
        "dim_tempo":     {"linhas": n_tempo, "bytes": b_tempo},
    },
    "definicoes": {
        "otp": "SUM(partidas_pontuais) / SUM(realizados) — cancelado não entra no denominador, "
               "porque voo que não saiu não pode ser pontual nem atrasado",
        "pontual": "atraso de partida <= 15 min (padrão ANAC/IATA)",
        "atraso_severo": "atraso de partida > 60 min",
        "media_de_atraso": "SUM(soma_atraso_partida) / SUM(com_atraso_partida) — nunca a média "
                           "de uma média",
        "faixa_plausivel": [ATRASO_MIN_PLAUSIVEL, ATRASO_MAX_PLAUSIVEL],
    },
    "qualidade": {k: (int(v) if isinstance(v, (int, bool)) else v) for k, v in qualidade.items()},
}

caminho_manifest = f"{DIR_SAIDA}/manifest.json"
with open(caminho_manifest, "w", encoding="utf-8") as f:
    json.dump(manifest, f, ensure_ascii=False, indent=2)

print(json.dumps(manifest, ensure_ascii=False, indent=2))

# COMMAND ----------

# DBTITLE 1,Validação — o fato tem de reproduzir a OBT
# MAGIC %md
# MAGIC Um fato agregado que não fecha com a origem é pior que nenhum fato. Estas quatro
# MAGIC igualdades têm de dar `diferenca = 0`. Se alguma falhar, o `GROUP BY ALL` perdeu linha —
# MAGIC tipicamente por chave com `NULL` tratada de forma diferente nos dois lados.

# COMMAND ----------

spark.createDataFrame(pdf_fato).createOrReplaceTempView("fato_exportado")

display(spark.sql("""
SELECT 'total de voos' AS medida,
       (SELECT SUM(voos) FROM fato_exportado)  AS no_fato,
       (SELECT COUNT(*)  FROM mizukiairflows.gold.obt_voos) AS na_obt,
       (SELECT SUM(voos) FROM fato_exportado)
       - (SELECT COUNT(*) FROM mizukiairflows.gold.obt_voos) AS diferenca
UNION ALL
SELECT 'realizados',
       (SELECT SUM(realizados) FROM fato_exportado),
       (SELECT SUM(CASE WHEN flag_realizado THEN 1 ELSE 0 END) FROM mizukiairflows.gold.obt_voos),
       (SELECT SUM(realizados) FROM fato_exportado)
       - (SELECT SUM(CASE WHEN flag_realizado THEN 1 ELSE 0 END) FROM mizukiairflows.gold.obt_voos)
UNION ALL
SELECT 'partidas pontuais',
       (SELECT SUM(partidas_pontuais) FROM fato_exportado),
       (SELECT SUM(CASE WHEN partida_pontual THEN 1 ELSE 0 END) FROM mizukiairflows.gold.obt_voos),
       (SELECT SUM(partidas_pontuais) FROM fato_exportado)
       - (SELECT SUM(CASE WHEN partida_pontual THEN 1 ELSE 0 END) FROM mizukiairflows.gold.obt_voos)
UNION ALL
SELECT 'soma do atraso de partida',
       (SELECT SUM(soma_atraso_partida) FROM fato_exportado),
       (SELECT SUM(atraso_partida_min) FROM mizukiairflows.gold.obt_voos),
       (SELECT SUM(soma_atraso_partida) FROM fato_exportado)
       - (SELECT SUM(atraso_partida_min) FROM mizukiairflows.gold.obt_voos)
"""))

# COMMAND ----------

# DBTITLE 1,Validação — o OTP por empresa tem de bater com a OBT
# MAGIC %md
# MAGIC A validação acima prova que os totais fecham. Esta prova que o **grão** está certo: se
# MAGIC alguma chave estivesse faltando no `GROUP BY`, os totais ainda fechariam mas os cortes
# MAGIC não. Compara o OTP das dez maiores empresas nas duas fontes.

# COMMAND ----------

display(spark.sql("""
WITH do_fato AS (
  SELECT icao_empresa,
         SUM(realizados) AS realizados,
         ROUND(100.0 * SUM(partidas_pontuais) / NULLIF(SUM(realizados), 0), 2) AS otp
  FROM fato_exportado GROUP BY icao_empresa
),
da_obt AS (
  SELECT icao_empresa,
         SUM(CASE WHEN flag_realizado THEN 1 ELSE 0 END) AS realizados,
         ROUND(100.0 * SUM(CASE WHEN partida_pontual THEN 1 ELSE 0 END)
               / NULLIF(SUM(CASE WHEN flag_realizado THEN 1 ELSE 0 END), 0), 2) AS otp
  FROM mizukiairflows.gold.obt_voos GROUP BY icao_empresa
)
SELECT f.icao_empresa, f.realizados, f.otp AS otp_fato, o.otp AS otp_obt,
       ROUND(f.otp - o.otp, 4) AS diferenca
FROM do_fato f JOIN da_obt o ON f.icao_empresa = o.icao_empresa
ORDER BY f.realizados DESC LIMIT 10
"""))

# COMMAND ----------

# DBTITLE 1,Resumo
total_bytes = sum(t["bytes"] for t in manifest["tabelas"].values())

print("=" * 66)
print("EXPORT CONCLUÍDO")
print("=" * 66)
for nome, t in manifest["tabelas"].items():
    print(f"  {nome:<16} {t['linhas']:>9,} linhas   {t['bytes'] / 1024:>8,.0f} KB")
print("-" * 66)
print(f"  {'TOTAL':<16} {'':>9}          {total_bytes / 1024 / 1024:>8,.2f} MB")
print()
print(f"  Compressão do fato: {1014705 / max(n_fato, 1):.1f}x")
print()

if total_bytes > 12 * 1024 * 1024:
    print("  ⚠️  Acima de 12 MB — primeiro carregamento da página fica lento.")
    print("     Cortar chaves do fato nesta ordem: periodo_partida, fim_de_semana,")
    print("     codigo_tipo_linha, icao_destino.")
else:
    print("  ✅ Tamanho confortável para carregar no navegador.")

print()
print("  Próximo passo: Catalog > Volumes > mizukiairflows > bronze > arquivos > export")
print("  Baixar os 5 .parquet + manifest.json e commitar em agente/dados/")
print("=" * 66)
