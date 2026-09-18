# Databricks notebook source
# /// script
# [tool.databricks.environment]
# environment_version = "5"
# ///
# DBTITLE 1,Título e Descrição
# MAGIC %md
# MAGIC # Camada Bronze - Aeródromos Públicos
# MAGIC
# MAGIC Este pipeline ingere dados de referência de aeródromos públicos na camada bronze.
# MAGIC
# MAGIC **Origem**: `/Volumes/mizukiairflows/bronze/arquivos/Referencias/AerodromosPublicos.csv`
# MAGIC
# MAGIC **Destino**: `mizukiairflows.bronze.aerodromos_publicos`
# MAGIC
# MAGIC **Características da Camada Bronze**:
# MAGIC - Todas as colunas armazenadas como STRING (dados brutos)
# MAGIC - Ingestão completa de dados (sem filtros)
# MAGIC - Colunas de auditoria para rastreamento
# MAGIC - Cargas idempotentes usando COPY INTO

# COMMAND ----------

# DBTITLE 1,Criar Tabela Bronze
# Criar tabela bronze para aeródromos públicos

print("Criando tabela bronze para aeródromos públicos...\n")

spark.sql("DROP TABLE IF EXISTS mizukiairflows.bronze.aerodromos_publicos")

create_table_sql = """
CREATE TABLE mizukiairflows.bronze.aerodromos_publicos (
  _source_file STRING COMMENT 'Caminho do arquivo de origem',
  _ingestion_timestamp TIMESTAMP COMMENT 'Timestamp de ingestão'
)
USING DELTA
COMMENT 'Camada Bronze: Aeródromos públicos - todas colunas como STRING'
TBLPROPERTIES (
  'delta.autoOptimize.optimizeWrite' = 'true',
  'delta.autoOptimize.autoCompact' = 'true',
  'delta.columnMapping.mode' = 'name',
  'delta.minReaderVersion' = '2',
  'delta.minWriterVersion' = '5'
)
"""

print(create_table_sql)
print("\n" + "="*80 + "\n")

spark.sql(create_table_sql)
print("✓ Tabela bronze criada com sucesso")

# COMMAND ----------

# DBTITLE 1,Ingerir Dados com COPY INTO
# Ingestão com tratamento de linha de metadados no topo
# Arquivo CSV tem formato: Linha 1 = metadados, Linha 2+ = header + dados

from pyspark.sql.functions import col, lit, current_timestamp, monotonically_increasing_id

volume_path = "/Volumes/mizukiairflows/bronze/arquivos/Referencias/AerodromosPublicos.csv"

print(f"Iniciando ingestão...")
print(f"Origem: {volume_path}")
print(f"Destino: mizukiairflows.bronze.aerodromos_publicos")
print("\n⚠ Arquivo contém linha de metadados no topo - será removida\n")

try:
    # Ler arquivo como texto
    df_text = spark.read.text(volume_path)
    
    # Adicionar número da linha
    df_numbered = df_text.withColumn("row_num", monotonically_increasing_id())
    
    # Remover primeira linha (metadados) e pegar o resto
    df_without_metadata = df_numbered.filter(col("row_num") > 0).select("value")
    
    # Salvar temporariamente sem a linha de metadados
    temp_path = "/Volumes/mizukiairflows/bronze/arquivos/_temp/aerodromos_clean.csv"
    df_without_metadata.coalesce(1).write.mode("overwrite").text(temp_path)
    
    # Agora ler o arquivo limpo com COPY INTO
    result = spark.sql(f"""
    COPY INTO mizukiairflows.bronze.aerodromos_publicos
    FROM (
      SELECT 
        *,
        _metadata.file_path AS _source_file,
        current_timestamp() AS _ingestion_timestamp
      FROM '{temp_path}'
    )
    FILEFORMAT = CSV
    FORMAT_OPTIONS (
      'header' = 'true',
      'inferSchema' = 'false',
      'mode' = 'PERMISSIVE',
      'delimiter' = ';',
      'encoding' = 'ISO-8859-1'
    )
    COPY_OPTIONS ('mergeSchema' = 'true')
    """)
    
    display(result)
    print("\n✓ Ingestão concluída com sucesso")
    
except Exception as e:
    print(f"⚠ Erro: {str(e)}")
    import traceback
    traceback.print_exc()
    raise

# COMMAND ----------

# DBTITLE 1,Validação
# MAGIC %sql
# MAGIC -- Validação da ingestão
# MAGIC
# MAGIC SELECT 
# MAGIC   COUNT(*) as total_linhas,
# MAGIC   MIN(_ingestion_timestamp) as primeira_ingestao,
# MAGIC   MAX(_ingestion_timestamp) as ultima_ingestao
# MAGIC FROM mizukiairflows.bronze.aerodromos_publicos;
# MAGIC
# MAGIC -- Amostra
# MAGIC SELECT * FROM mizukiairflows.bronze.aerodromos_publicos LIMIT 10;

# COMMAND ----------

