# Databricks notebook source
# /// script
# [tool.databricks.environment]
# environment_version = "5"
# ///
# DBTITLE 1,Título e Descrição
# MAGIC %md
# MAGIC # Camada Bronze - Empresas Aéreas Nacionais
# MAGIC
# MAGIC Este pipeline ingere dados de referência de empresas aéreas nacionais na camada bronze.
# MAGIC
# MAGIC **Origem**: `/Volumes/mizukiairflows/bronze/arquivos/Referencias/pda_empresas_aereas_nacionais.csv` (142 MB)
# MAGIC
# MAGIC **Destino**: `mizukiairflows.bronze.empresas_aereas_nacionais`
# MAGIC
# MAGIC **Características da Camada Bronze**:
# MAGIC - Todas as colunas armazenadas como STRING (dados brutos)
# MAGIC - Ingestão completa de dados (sem filtros)
# MAGIC - Colunas de auditoria para rastreamento
# MAGIC - Cargas idempotentes usando COPY INTO

# COMMAND ----------

# DBTITLE 1,Criar Tabela Bronze
# Criar tabela bronze para empresas aéreas nacionais

print("Criando tabela bronze para empresas aéreas nacionais...\n")

spark.sql("DROP TABLE IF EXISTS mizukiairflows.bronze.empresas_aereas_nacionais")

create_table_sql = """
CREATE TABLE mizukiairflows.bronze.empresas_aereas_nacionais (
  _source_file STRING COMMENT 'Caminho do arquivo de origem',
  _ingestion_timestamp TIMESTAMP COMMENT 'Timestamp de ingestão'
)
USING DELTA
COMMENT 'Camada Bronze: Empresas aéreas nacionais - todas colunas como STRING'
TBLPROPERTIES (
  'delta.autoOptimize.optimizeWrite' = 'true',
  'delta.autoOptimize.autoCompact' = 'true'
)
"""

print(create_table_sql)
print("\n" + "="*80 + "\n")

spark.sql(create_table_sql)
print("✓ Tabela bronze criada com sucesso")

# COMMAND ----------

# DBTITLE 1,Ingerir Dados como Texto Bruto
# Ingestão como texto bruto devido a CSV extremamente malformado
# Arquivo será ingerido como linhas de texto - parsing será feito na camada silver

from pyspark.sql.functions import lit, current_timestamp, input_file_name, col, monotonically_increasing_id

volume_path = "/Volumes/mizukiairflows/bronze/arquivos/Referencias/pda_empresas_aereas_nacionais.csv"

print(f"Iniciando ingestão...")
print(f"Origem: {volume_path}")
print(f"Destino: mizukiairflows.bronze.empresas_aereas_nacionais")
print("\n⚠ Arquivo com formato CSV inválido")
print("⚠ Ingerindo como TEXTO BRUTO - parsing será feito na camada Silver\n")

try:
    # Verificar se já existem dados (para idempotência manual)
    try:
        existing_count = spark.table("mizukiairflows.bronze.empresas_aereas_nacionais").count()
    except:
        existing_count = 0
    
    if existing_count > 0:
        print(f"⚠ Tabela já contém {existing_count:,} registros")
        print("Pulando ingestão (para re-ingerir, recrie a tabela)\n")
    else:
        # Ler arquivo como texto bruto (cada linha = um registro)
        df_text = spark.read.text(volume_path)
        
        # Adicionar ID de linha e colunas de auditoria
        df_with_audit = df_text \
            .withColumn("linha_id", monotonically_increasing_id()) \
            .withColumn("_source_file", lit(volume_path)) \
            .withColumn("_ingestion_timestamp", current_timestamp()) \
            .select(
                col("value").alias("raw_line"),
                "linha_id",
                "_source_file",
                "_ingestion_timestamp"
            )
        
        print(f"Linhas lidas: {df_text.count():,}")
        print("Inserindo na tabela bronze...\n")
        
        # Inserir na tabela bronze
        df_with_audit.write \
            .mode("append") \
            .option("mergeSchema", "true") \
            .saveAsTable("mizukiairflows.bronze.empresas_aereas_nacionais")
        
        final_count = spark.table("mizukiairflows.bronze.empresas_aereas_nacionais").count()
        print(f"✓ Ingestão concluída com sucesso")
        print(f"Total de linhas ingeridas: {final_count:,}")
        print("\n💡 Nota: Dados ingeridos como texto bruto")
        print("   O parsing e estruturação serão feitos na camada Silver")
    
except Exception as e:
    print(f"⚠ Erro: {str(e)}")
    import traceback
    traceback.print_exc()
    raise

# COMMAND ----------

# DBTITLE 1,Validação
# MAGIC %sql
# MAGIC -- Validação da ingestão (dados como texto bruto)
# MAGIC
# MAGIC SELECT 
# MAGIC   COUNT(*) as total_linhas,
# MAGIC   COUNT(DISTINCT linha_id) as linhas_unicas,
# MAGIC   MIN(_ingestion_timestamp) as primeira_ingestao,
# MAGIC   MAX(_ingestion_timestamp) as ultima_ingestao
# MAGIC FROM mizukiairflows.bronze.empresas_aereas_nacionais;
# MAGIC
# MAGIC -- Amostra das primeiras linhas
# MAGIC SELECT 
# MAGIC   linha_id,
# MAGIC   LEFT(raw_line, 100) as preview_linha,
# MAGIC   _ingestion_timestamp
# MAGIC FROM mizukiairflows.bronze.empresas_aereas_nacionais
# MAGIC ORDER BY linha_id
# MAGIC LIMIT 10;

# COMMAND ----------

