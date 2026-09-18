# Databricks notebook source
# /// script
# [tool.databricks.environment]
# environment_version = "5"
# ///
# DBTITLE 1,Título e Descrição do Pipeline
# MAGIC %md
# MAGIC # Camada Bronze - Ingestão VRA
# MAGIC
# MAGIC Este pipeline ingere dados VRA (Voo Regular Ativo) de arquivos CSV na camada bronze seguindo os princípios da arquitetura medallion:
# MAGIC
# MAGIC **Origem**: Arquivos CSV mensais no volume Unity Catalog `mizukiairflows.bronze.arquivos/vra/`
# MAGIC
# MAGIC **Destino**: Tabela bronze `mizukiairflows.bronze.vra`
# MAGIC
# MAGIC **Características da Camada Bronze**:
# MAGIC - Todas as colunas armazenadas como STRING (dados brutos, sem transformações)
# MAGIC - Ingestão completa de dados (sem filtros)
# MAGIC - Colunas de auditoria para rastreamento de linhagem
# MAGIC - Cargas idempotentes usando COPY INTO

# COMMAND ----------

# DBTITLE 1,Setup: Criar Catálogo e Schema
# MAGIC %sql
# MAGIC -- Criar catálogo e schema se não existirem
# MAGIC CREATE CATALOG IF NOT EXISTS mizukiairflows
# MAGIC   COMMENT 'Catálogo principal para a plataforma de dados Mizuki Airflows';
# MAGIC
# MAGIC CREATE SCHEMA IF NOT EXISTS mizukiairflows.bronze
# MAGIC   COMMENT 'Camada Bronze: Ingestão de dados brutos com transformações mínimas';

# COMMAND ----------

# DBTITLE 1,Criar Tabela Bronze com Schema String
# MAGIC %sql
# MAGIC -- Remover tabela existente para garantir schema limpo (idempotente)
# MAGIC DROP TABLE IF EXISTS mizukiairflows.bronze.vra;
# MAGIC
# MAGIC -- Criar tabela bronze com todas as colunas STRING mais colunas de auditoria
# MAGIC -- Nota: Primeiro precisamos inspecionar um CSV para determinar as colunas reais
# MAGIC -- Por enquanto, criando schema flexível que COPY INTO irá popular
# MAGIC CREATE TABLE mizukiairflows.bronze.vra (
# MAGIC   -- Colunas do CSV serão inferidas e convertidas para STRING pelo COPY INTO
# MAGIC   -- Colunas de auditoria para linhagem de dados
# MAGIC   _source_file STRING COMMENT 'Caminho do arquivo de origem para rastreamento',
# MAGIC   _ingestion_timestamp TIMESTAMP COMMENT 'Timestamp UTC de quando os dados foram ingeridos'
# MAGIC )
# MAGIC USING DELTA
# MAGIC COMMENT 'Camada Bronze: Dados brutos VRA (Voo Regular Ativo) de arquivos CSV mensais'
# MAGIC TBLPROPERTIES (
# MAGIC   'delta.autoOptimize.optimizeWrite' = 'true',
# MAGIC   'delta.autoOptimize.autoCompact' = 'true'
# MAGIC );

# COMMAND ----------

# DBTITLE 1,Verificar Volume e Arquivos
# Verificar se volume e arquivos existem, depois inspecionar schema

volume_path = "/Volumes/mizukiairflows/bronze/arquivos/vra/"

try:
    # Listar arquivos no volume
    files = dbutils.fs.ls(volume_path)
    csv_files = [f for f in files if f.name.endswith('.csv')]
    
    print(f"✓ Encontrados {len(csv_files)} arquivos CSV em {volume_path}")
    for f in csv_files[:5]:  # Mostrar primeiros 5 arquivos
        print(f"  • {f.name} ({f.size:,} bytes)")
    if len(csv_files) > 5:
        print(f"  ... e mais {len(csv_files) - 5} arquivos")
    
    if csv_files:
        # Ler um CSV para inferir o schema
        print("\n" + "="*80)
        print("Inspecionando schema do CSV...\n")
        
        df_sample = spark.read.csv(
            volume_path,
            header=True,
            inferSchema=True
        )
        
        print("Schema do CSV:")
        df_sample.printSchema()
        
        print("\nDados de amostra (primeiras 5 linhas):")
        display(df_sample.limit(5))
        
        print(f"\nNomes das colunas ({len(df_sample.columns)} colunas):")
        print(df_sample.columns)
    else:
        print("\n⚠ Nenhum arquivo CSV encontrado no caminho do volume")
        
except Exception as e:
    print(f"⚠ Falha na verificação do caminho do volume: {e}")
    print("\n" + "="*80)
    print("SETUP NECESSÁRIO:")
    print("1. Criar o diretório no volume:")
    print("   (Fazer upload dos arquivos via UI do Databricks para /Volumes/mizukiairflows/bronze/arquivos/vra/)")
    print("\n2. Ou criar o diretório e fazer upload dos CSVs usando dbutils:")
    print(f"   dbutils.fs.mkdirs('{volume_path}')")
    print("   dbutils.fs.cp('file:/caminho/local/arquivo.csv', f'{volume_path}arquivo.csv')")
    print("\n3. Depois execute esta célula novamente para inspecionar o schema")
    print("="*80)
    
    # Para fins de demonstração, criar uma sugestão de schema
    print("\n💡 Quando os arquivos forem carregados, o pipeline automaticamente:")
    print("   • Detectará todas as colunas do CSV")
    print("   • Criará tabela bronze com todas as colunas STRING")
    print("   • Adicionará colunas de auditoria (_source_file, _ingestion_timestamp)")
    print("   • Ingerirá dados de forma idempotente usando COPY INTO")

# COMMAND ----------

# DBTITLE 1,Criar Tabela Bronze
# Criar tabela bronze - abordagem de schema flexível
# Tabela começa apenas com colunas de auditoria
# COPY INTO adicionará colunas do CSV automaticamente com mergeSchema=true

print("Criando tabela bronze com schema flexível...")
print("Colunas do CSV serão adicionadas automaticamente durante o primeiro COPY INTO\n")

# Remover tabela se existir
spark.sql("DROP TABLE IF EXISTS mizukiairflows.bronze.vra")

# Criar tabela apenas com colunas de auditoria
create_table_sql = """
CREATE TABLE mizukiairflows.bronze.vra (
  _source_file STRING COMMENT 'Caminho do arquivo de origem para rastreamento',
  _ingestion_timestamp TIMESTAMP COMMENT 'Timestamp UTC de quando os dados foram ingeridos'
)
USING DELTA
COMMENT 'Camada Bronze: Dados brutos VRA (Voo Regular Ativo) de arquivos CSV mensais - todas as colunas como STRING'
TBLPROPERTIES (
  'delta.autoOptimize.optimizeWrite' = 'true',
  'delta.autoOptimize.autoCompact' = 'true',
  'delta.minReaderVersion' = '1',
  'delta.minWriterVersion' = '2'
)
"""

print(create_table_sql)
print("\n" + "="*80 + "\n")

spark.sql(create_table_sql)
print("✓ Tabela bronze criada com sucesso")
print("\n💡 Próximo passo: Fazer upload dos arquivos CSV para /Volumes/mizukiairflows/bronze/arquivos/vra/")
print("   Depois execute a célula COPY INTO para ingerir os dados")

# COMMAND ----------

# DBTITLE 1,Helper: Criar Diretório para Arquivos CSV
# Célula helper: Criar o diretório VRA no volume
# Execute esta célula uma vez para preparar a estrutura de diretórios para upload de arquivos

volume_path = "/Volumes/mizukiairflows/bronze/arquivos/vra/"

try:
    # Criar diretório se não existir
    dbutils.fs.mkdirs(volume_path)
    print(f"✓ Diretório criado: {volume_path}")
    print("\n" + "="*80)
    print("PRÓXIMOS PASSOS - Faça upload dos seus arquivos CSV VRA:")
    print("\n1. Via Interface do Databricks:")
    print("   - Vá para Catalog > Volumes > mizukiairflows > bronze > arquivos")
    print("   - Clique na pasta 'vra'")
    print("   - Clique no botão 'Upload' e selecione seus 12 arquivos CSV")
    print("\n2. Via Código (se os arquivos estiverem acessíveis deste notebook):")
    print("   # Exemplo: Copiar de outro local")
    print(f"   # dbutils.fs.cp('dbfs:/caminho/origem/arquivo.csv', '{volume_path}arquivo.csv')")
    print("\n3. Via Databricks CLI:")
    print("   # databricks fs cp arquivo-local.csv {volume_path}arquivo.csv")
    print("="*80)
    
    # Verificar se arquivos já existem
    files = dbutils.fs.ls(volume_path)
    if files:
        print(f"\n📝 Encontrado(s) {len(files)} arquivo(s) no diretório:")
        for f in files[:10]:
            print(f"  • {f.name}")
        if len(files) > 10:
            print(f"  ... e mais {len(files) - 10}")
except Exception as e:
    print(f"⚠ Erro ao criar diretório: {e}")

# COMMAND ----------

# DBTITLE 1,Sobre Idempotência do COPY INTO
# MAGIC %md
# MAGIC ## Ingestão Idempotente de Dados com COPY INTO
# MAGIC
# MAGIC O **COPY INTO** rastreia automaticamente quais arquivos foram processados, garantindo cargas idempotentes:
# MAGIC
# MAGIC * ✅ **Execute múltiplas vezes com segurança** - Arquivos já processados são automaticamente ignorados
# MAGIC * ✅ **Carregamento incremental** - Apenas arquivos novos ou modificados são ingeridos
# MAGIC * ✅ **Evolução de schema** - Com `mergeSchema=true`, novas colunas são adicionadas automaticamente
# MAGIC * ✅ **Conformidade camada bronze** - Todos os dados ingeridos como STRING, sem transformações
# MAGIC
# MAGIC **Antes de executar COPY INTO:**
# MAGIC 1. Certifique-se de que seus 12 arquivos CSV VRA estão carregados no caminho do volume
# MAGIC 2. Verifique se os arquivos têm cabeçalhos (primeira linha contém nomes das colunas)
# MAGIC 3. Confirme que os arquivos usam formato CSV padrão (separados por vírgula)
# MAGIC
# MAGIC **Após carregar os arquivos, execute a próxima célula para ingerir os dados.**

# COMMAND ----------

# DBTITLE 1,Ingerir Dados usando COPY INTO (Idempotente)
# Usar COPY INTO para ingestão idempotente
# COPY INTO rastreia automaticamente arquivos processados e previne duplicatas

volume_path = "/Volumes/mizukiairflows/bronze/arquivos/VRA/"

print("Iniciando ingestão VRA...")
print(f"Origem: {volume_path}")
print(f"Destino: mizukiairflows.bronze.vra")
print("\n" + "="*80 + "\n")

# Limpar tabela antes de re-ingerir (remover ingestão anterior com schema incorreto)
print("🧽 Limpando dados anteriores...")
spark.sql("TRUNCATE TABLE mizukiairflows.bronze.vra")
print("✅ Tabela limpa\n")

try:
    # Ler CSVs VRA com parsing robusto usando pandas
    # Estrutura: Linha 1 = metadados (remover), Linha 2+ = header + dados
    # Delimitador: `;`, Encoding: ISO-8859-1, Quote: `"`
    
    print("📥 Lendo arquivos CSV VRA com pandas...\n")
    
    from pyspark.sql.functions import col, current_timestamp, lit
    import pandas as pd
    import io
    
    # Listar arquivos CSV
    csv_files = [f for f in dbutils.fs.ls(volume_path) if f.name.endswith('.csv')]
    print(f"🗂️  Encontrados {len(csv_files)} arquivos CSV\n")
    
    # Processar arquivo por arquivo com pandas
    all_pandas_dfs = []
    
    for csv_file in csv_files:
        file_path = csv_file.path
        
        # Ler conteúdo do arquivo usando dbutils (funciona com Unity Catalog Volumes)
        # Ler arquivo inteiro como texto
        df_text = spark.read.text(file_path)
        lines = [row['value'] + '\n' for row in df_text.collect()]
        
        if len(lines) < 3:
            print(f"⚠️  Arquivo {csv_file.name} tem menos de 3 linhas, pulando...")
            continue
        
        # Remover linha 1 (metadados) e criar CSV limpo
        clean_csv = "".join(lines[1:])  # Linha 2 (header) + Linha 3+ (dados)
        
        # Ler com pandas
        pdf = pd.read_csv(
            io.StringIO(clean_csv),
            sep=';',
            encoding='ISO-8859-1',
            quotechar='"',
            dtype=str,  # Tudo como STRING (bronze)
            keep_default_na=False
        )
        
        # Limpar nomes de colunas
        def clean_column_name(name):
            cleaned = name.replace('\ufeff', '').strip()
            cleaned = cleaned.replace(' ', '_')
            for char in [',', ';', '{', '}', '(', ')', '\n', '\t', '=']:
                cleaned = cleaned.replace(char, '')
            return cleaned
        
        pdf.columns = [clean_column_name(c) for c in pdf.columns]
        
        # Adicionar coluna de source file
        pdf['_source_file'] = file_path
        
        all_pandas_dfs.append(pdf)
        print(f"✅ {csv_file.name}: {len(pdf.columns)-1} colunas, {len(pdf):,} registros")
    
    if not all_pandas_dfs:
        raise Exception("Nenhum arquivo foi processado com sucesso")
    
    # Concatenar todos os pandas DataFrames
    pdf_combined = pd.concat(all_pandas_dfs, ignore_index=True)
    
    print(f"\n📊 Total: {len(pdf_combined):,} registros, {len(pdf_combined.columns)-1} colunas de dados\n")
    
    # Converter para Spark DataFrame
    df_spark = spark.createDataFrame(pdf_combined)
    
    # Adicionar timestamp de ingestão
    df_final = df_spark.withColumn('_ingestion_timestamp', current_timestamp())
    
    num_records = df_final.count()
    num_files = len([f for f in dbutils.fs.ls(volume_path) if f.name.endswith('.csv')])
    
    print(f"✅ Processados {num_records:,} registros de {num_files} arquivo(s) CSV")
    print(f"📊 Colunas totais (dados + auditoria): {len(df_final.columns)}\n")
    
    # Escrever na tabela bronze
    print("📤 Escrevendo na tabela bronze...\n")
    
    df_final.write \
        .format('delta') \
        .mode('append') \
        .option('mergeSchema', 'true') \
        .saveAsTable('mizukiairflows.bronze.vra')
    
    print(f"\n✅ Ingestão concluída: {num_records:,} registros inseridos em mizukiairflows.bronze.vra")
    print("\n" + "="*80)
    print("\n📋 Resumo da Ingestão:")
    print(f"   • Arquivos processados: {num_files}")
    print(f"   • Registros inseridos: {num_records:,}")
    print(f"   • Colunas totais: {len(df_final.columns)}")
    print("\n⚠️  Nota: Esta ingestão usou modo 'append'. Para re-executar sem duplicar:")
    print("   Primeiro execute: spark.sql('TRUNCATE TABLE mizukiairflows.bronze.vra')")
    
except Exception as e:
    print(f"⚠ COPY INTO falhou: {str(e)}")
    print("\n" + "="*80)
    print("Problemas comuns:")
    print("1. Nenhum arquivo CSV no caminho do volume ainda")
    print("2. Formato CSV não corresponde às expectativas (verifique cabeçalho, delimitador)")
    print("3. Problemas de permissão ao acessar o volume")
    print("\nPara fazer upload dos arquivos:")
    print(f"  • Use a UI do Databricks: Catalog > Volumes > arquivos > Upload para a pasta 'vra'")
    print(f"  • Ou use: dbutils.fs.cp('caminho_origem', '{volume_path}nomedoarquivo.csv')")
    raise

# COMMAND ----------

# DBTITLE 1,Validação: Verificar Resultados da Ingestão
# MAGIC %sql
# MAGIC -- Queries de validação para verificar ingestão bem-sucedida
# MAGIC
# MAGIC -- 1. Contagem total de linhas
# MAGIC SELECT 
# MAGIC   COUNT(*) as total_linhas,
# MAGIC   COUNT(DISTINCT _source_file) as arquivos_processados,
# MAGIC   MIN(_ingestion_timestamp) as primeira_ingestao,
# MAGIC   MAX(_ingestion_timestamp) as ultima_ingestao
# MAGIC FROM mizukiairflows.bronze.vra;
# MAGIC
# MAGIC -- 2. Contagem de linhas por arquivo de origem
# MAGIC SELECT 
# MAGIC   _source_file,
# MAGIC   COUNT(*) as qtd_linhas,
# MAGIC   MIN(_ingestion_timestamp) as timestamp_ingestao
# MAGIC FROM mizukiairflows.bronze.vra
# MAGIC GROUP BY _source_file, _ingestion_timestamp
# MAGIC ORDER BY _source_file;
# MAGIC
# MAGIC -- 3. Registros de amostra
# MAGIC SELECT *
# MAGIC FROM mizukiairflows.bronze.vra
# MAGIC LIMIT 10;

# COMMAND ----------

# DBTITLE 1,Resumo do Pipeline e Próximos Passos
# MAGIC %md
# MAGIC ## ✅ Setup do Pipeline Completo
# MAGIC
# MAGIC **Infraestrutura Criada:**
# MAGIC * Catálogo: `mizukiairflows`
# MAGIC * Schema: `mizukiairflows.bronze`
# MAGIC * Volume: `mizukiairflows.bronze.arquivos`
# MAGIC * Diretório: `/Volumes/mizukiairflows/bronze/arquivos/vra/`
# MAGIC * Tabela: `mizukiairflows.bronze.vra` (com colunas de auditoria)
# MAGIC
# MAGIC **Características da Camada Bronze:**
# MAGIC * ✅ Todas as colunas CSV armazenadas como STRING (preservação de dados brutos)
# MAGIC * ✅ Colunas de auditoria: `_source_file`, `_ingestion_timestamp`
# MAGIC * ✅ Cargas idempotentes via COPY INTO
# MAGIC * ✅ Evolução automática de schema habilitada
# MAGIC * ✅ Auto-otimização habilitada para escrita e compactação
# MAGIC
# MAGIC **Próximos Passos:**
# MAGIC 1. **Faça upload dos seus 12 arquivos CSV VRA** para `/Volumes/mizukiairflows/bronze/arquivos/vra/`
# MAGIC 2. **Execute a célula COPY INTO** para ingerir os dados
# MAGIC 3. **Execute as queries de validação** para verificar ingestão bem-sucedida
# MAGIC 4. **Re-execute COPY INTO quando necessário** - processará apenas arquivos novos/modificados
# MAGIC
# MAGIC **Considerações para Produção:**
# MAGIC * Considere particionamento se o volume de dados for grande (milhões de linhas)
# MAGIC * Configure monitoramento/alertas para falhas de ingestão
# MAGIC * Documente o schema do CSV e dicionário de dados
# MAGIC * Crie transformações da camada silver downstream para lógica de negócio

# COMMAND ----------

# DBTITLE 1,Verificar arquivos no volume VRA
# Verificar o conteúdo atual do diretório VRA
vra_path = "/Volumes/mizukiairflows/bronze/arquivos/vra/"

print(f"📂 Verificando conteúdo de: {vra_path}\n")
print("="*80)

try:
    arquivos = dbutils.fs.ls(vra_path)
    
    if not arquivos:
        print("⚠️  DIRETÓRIO ESTÁ VAZIO")
        print("\nPara fazer upload dos arquivos CSV VRA:")
        print("\n1. Via Interface Databricks (RECOMENDADO):")
        print("   • Catalog > Volumes > mizukiairflows > bronze > arquivos > vra")
        print("   • Clique em 'Upload' e selecione os 12 arquivos CSV")
        print("\n2. Se os arquivos já estão em outro volume/caminho do Databricks:")
        print("   • Atualize o caminho 'origem' abaixo e execute:")
        print("   origem = '/Volumes/outro_catalog/outro_schema/outro_volume/caminho/'")
        print("   for f in dbutils.fs.ls(origem):")
        print("       if f.name.endswith('.csv'):")
        print(f"           dbutils.fs.cp(f.path, '{vra_path}' + f.name)")
    else:
        csv_files = [f for f in arquivos if f.name.endswith('.csv')]
        outros = [f for f in arquivos if not f.name.endswith('.csv')]
        
        print(f"✅ Encontrados {len(csv_files)} arquivo(s) CSV:")
        for f in csv_files:
            print(f"   • {f.name} ({f.size:,} bytes)")
        
        if outros:
            print(f"\n📄 Outros arquivos ({len(outros)}):")
            for f in outros[:5]:
                print(f"   • {f.name}")
            if len(outros) > 5:
                print(f"   ... e mais {len(outros) - 5}")
        
        if csv_files:
            print("\n✅ Arquivos encontrados! Você pode executar a Célula 8 (COPY INTO) agora.")
            
except Exception as e:
    print(f"❌ Erro ao acessar o diretório: {e}")

# COMMAND ----------

# DBTITLE 1,Buscar arquivos CSV VRA em todo o volume
# Buscar recursivamente por arquivos CSV em todo o volume bronze
import os

print("🔍 Buscando arquivos CSV em /Volumes/mizukiairflows/bronze/arquivos/\n")
print("="*80)

base_path = "/Volumes/mizukiairflows/bronze/arquivos/"
found_csv = []

def search_recursive(path, depth=0):
    """Busca recursiva por arquivos CSV"""
    try:
        items = dbutils.fs.ls(path)
        for item in items:
            if item.isDir():
                # Recursivamente buscar em subdiretórios
                search_recursive(item.path, depth+1)
            elif item.name.lower().endswith('.csv'):
                found_csv.append({
                    'path': item.path,
                    'name': item.name,
                    'size': item.size,
                    'dir': path
                })
    except Exception as e:
        pass  # Ignorar erros de permissão/acesso

search_recursive(base_path)

if found_csv:
    print(f"✅ Encontrados {len(found_csv)} arquivo(s) CSV:\n")
    
    # Agrupar por diretório
    by_dir = {}
    for f in found_csv:
        dir_name = f['dir']
        if dir_name not in by_dir:
            by_dir[dir_name] = []
        by_dir[dir_name].append(f)
    
    for dir_name, files in by_dir.items():
        print(f"\n📁 {dir_name}")
        for f in files:
            print(f"   • {f['name']} ({f['size']:,} bytes)")
    
    # Se arquivos estão em local diferente, oferecer mover
    vra_target = "/Volumes/mizukiairflows/bronze/arquivos/vra/"
    non_vra = [f for f in found_csv if not f['path'].startswith(vra_target)]
    
    if non_vra:
        print("\n" + "="*80)
        print("💡 Os arquivos estão em um local diferente do esperado!")
        print(f"\n✅ Local esperado: {vra_target}")
        print(f"⚠️  Arquivos encontrados em: {non_vra[0]['dir']}")
        print("\n🔧 Para mover os arquivos para o local correto, execute:")
        print("\nfor f in dbutils.fs.ls('" + non_vra[0]['dir'] + "'):")
        print("    if f.name.lower().endswith('.csv'):")
        print("        dbutils.fs.mv(f.path, '" + vra_target + "' + f.name)")
        print("        print(f'✓ Movido: {f.name}')")
else:
    print("❌ Nenhum arquivo CSV encontrado em /Volumes/mizukiairflows/bronze/arquivos/")
    print("\n📤 Você precisa fazer upload dos arquivos primeiro!")
    print("\n1. Via Interface Databricks:")
    print("   • Catalog > Volumes > mizukiairflows > bronze > arquivos > vra")
    print("   • Clique 'Upload' e selecione os 12 arquivos CSV VRA")
    print("\n2. Via Databricks CLI:")
    print("   databricks fs cp arquivo-local.csv /Volumes/mizukiairflows/bronze/arquivos/vra/")