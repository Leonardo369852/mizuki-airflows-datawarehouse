-- Databricks notebook source
-- DBTITLE 1,Introdução
-- MAGIC %md
-- MAGIC # Silver — Espelho Governado do Bronze
-- MAGIC
-- MAGIC **A regra da casa, e ela não é negociável:**
-- MAGIC
-- MAGIC A silver é o espelho do bronze com governança aplicada. **Mesmo nome de tabelas, mesmo grão, mesma contagem de linhas.**
-- MAGIC
-- MAGIC ## Regras Permitidas na Silver
-- MAGIC
-- MAGIC | Permitido na Silver | ✅ | Proibido na Silver | ❌ |
-- MAGIC | --- | --- | --- | --- |
-- MAGIC | **tipagem** | ✅ string vira TIMESTAMP, INT, DATE | **filtro / wheel de negócio** | ❌ |
-- MAGIC | **legalidade** | ✅ qualificar timestamps em data e hora | **caixa de / agregação** | ❌ |
-- MAGIC | **metadados** | ✅ COMMENT em toda coluna, tags na tabela | **tempo flag / sublineage** | ❌ |
-- MAGIC | **unificação** | ✅ dois cadastros do mesmo assunto, com a origem por registro | | |
-- MAGIC | **aritmética pura** | ✅ atraso = real - previsto | | |
-- MAGIC
-- MAGIC ---
-- MAGIC
-- MAGIC **Por quê?** Porque a silver precisa servir várias análises, e toda linha que ela descarta é uma pergunta que ninguém mais vai conseguir fazer. Filtro fecha porta.
-- MAGIC
-- MAGIC O teste para qualquer coluna nova: use **atributo, uma divisão de negócio** através da partida_min = partida_real - partida_prevista → o número 15 que diferencia atraso e não atraso vive na **gold**, não aqui. E se o limiar de atraso é subjetivo e muda por cliente — **gold**.

-- COMMAND ----------

-- DBTITLE 1,1. O que precisa ser convertido na tipagem
-- MAGIC %md
-- MAGIC ## 1. O que precisa ser convertido na tipagem
-- MAGIC
-- MAGIC **Antes de escrever o CAST, medir.** Duas armadilhas escondidas no bronze:
-- MAGIC
-- MAGIC ### Armadilha 1 — a ausência vem como a string `"null"`
-- MAGIC
-- MAGIC Quatro caracteres de texto: WHERE partida_real IS NULL THEN 0 ELSE 0 END.
-- MAGIC
-- MAGIC A partida_real não vicia null: ela vicia a string null.
-- MAGIC
-- MAGIC Reparar no que **não** existe nesta query: nenhum WHERE, nenhum GROUP BY, nenhum DISTINCT, nenhum JOIN. É um SELECT sobre a tabela bronze inteiro.

-- COMMAND ----------

-- DBTITLE 1,Analisar ausências e valores nulos
-- Medir ausências antes do CAST
-- Objetivo: descobrir se valores vem como NULL, 'null', '', ou outro padrão

SELECT
  COUNT(*) AS linhas,
  SUM(CASE WHEN partida_real IS NULL THEN 1 ELSE 0 END) AS partida_real_null_se_verdade,
  SUM(CASE WHEN partida_real = 'null' THEN 1 ELSE 0 END) AS partida_real_string_null,
  SUM(CASE WHEN partida_real LIKE '' THEN 1 ELSE 0 END) AS partida_real_string_vazia,
  SUM(CASE WHEN partida_prevista = 'NULL' THEN 1 ELSE 0 END) AS partida_prevista_string_null,
  SUM(CASE WHEN partida_prevista LIKE '' THEN 1 ELSE 0 END) AS partida_prevista_string_vazia
FROM mizukiairflows.bronze.vra;

-- COMMAND ----------

-- DBTITLE 1,2. Criar silver.vra com tipagem e metadados
-- MAGIC %md
-- MAGIC ## 2. Criar silver.vra — Espelho tipado do bronze
-- MAGIC
-- MAGIC **Estratégia:**
-- MAGIC * Tipar todas as colunas de timestamp (partida_prevista, partida_real, chegada_prevista, chegada_real)
-- MAGIC * Calcular aritmética pura: atraso_partida_min, atraso_chegada_min, minutos_recuperados
-- MAGIC * COMMENT em toda coluna
-- MAGIC * Documentar origem dos dados

-- COMMAND ----------

-- DBTITLE 1,Criar tabela silver.vra
CREATE OR REPLACE TABLE mizukiairflows.silver.vra
COMMENT 'Espelho governado do bronze.vra: voos regulares ativos com tipagem aplicada, cálculos de atraso, e metadados completos'
AS
SELECT
  -- Identificação (renomear para nomes limpos)
  `ICAO_Empresa_Aérea` AS icao_empresa,
  `Número_Voo` AS numero_voo,
  `Código_Autorização_DI` AS codigo_di,
  `Código_Tipo_Linha` AS codigo_tipo_linha,
  
  -- Origem e destino
  `ICAO_Aeródromo_Origem` AS icao_origem,
  `ICAO_Aeródromo_Destino` AS icao_destino,
  
  -- Partida (tipagem de timestamps - tratar 'null' como NULL)
  CASE WHEN `Partida_Prevista` = 'null' THEN NULL ELSE CAST(`Partida_Prevista` AS DATE) END AS partida_prevista_data,
  CASE WHEN `Partida_Prevista` = 'null' THEN NULL ELSE CAST(`Partida_Prevista` AS TIMESTAMP) END AS partida_prevista_hora,
  CASE WHEN `Partida_Real` = 'null' THEN NULL ELSE CAST(`Partida_Real` AS DATE) END AS partida_real_data,
  CASE WHEN `Partida_Real` = 'null' THEN NULL ELSE CAST(`Partida_Real` AS TIMESTAMP) END AS partida_real_hora,
  
  -- Chegada (tipagem de timestamps - tratar 'null' como NULL)
  CASE WHEN `Chegada_Prevista` = 'null' THEN NULL ELSE CAST(`Chegada_Prevista` AS DATE) END AS chegada_prevista_data,
  CASE WHEN `Chegada_Prevista` = 'null' THEN NULL ELSE CAST(`Chegada_Prevista` AS TIMESTAMP) END AS chegada_prevista_hora,
  CASE WHEN `Chegada_Real` = 'null' THEN NULL ELSE CAST(`Chegada_Real` AS DATE) END AS chegada_real_data,
  CASE WHEN `Chegada_Real` = 'null' THEN NULL ELSE CAST(`Chegada_Real` AS TIMESTAMP) END AS chegada_real_hora,
  
  -- Situação e justificativa
  `Situação_Voo` AS situacao_voo,
  `Código_Justificativa` AS codigo_justificativa,
  
  -- Aritmética pura: cálculo de atrasos (em minutos)
  CASE 
    WHEN `Partida_Real` != 'null' AND `Partida_Prevista` != 'null'
    THEN TIMESTAMPDIFF(MINUTE, CAST(`Partida_Prevista` AS TIMESTAMP), CAST(`Partida_Real` AS TIMESTAMP))
    ELSE NULL 
  END AS atraso_partida_min,
  
  CASE 
    WHEN `Chegada_Real` != 'null' AND `Chegada_Prevista` != 'null'
    THEN TIMESTAMPDIFF(MINUTE, CAST(`Chegada_Prevista` AS TIMESTAMP), CAST(`Chegada_Real` AS TIMESTAMP))
    ELSE NULL 
  END AS atraso_chegada_min,
  
  -- Minutos recuperados = atraso_partida - atraso_chegada
  CASE
    WHEN `Partida_Real` != 'null' AND `Partida_Prevista` != 'null' 
      AND `Chegada_Real` != 'null' AND `Chegada_Prevista` != 'null'
    THEN TIMESTAMPDIFF(MINUTE, CAST(`Partida_Prevista` AS TIMESTAMP), CAST(`Partida_Real` AS TIMESTAMP))
       - TIMESTAMPDIFF(MINUTE, CAST(`Chegada_Prevista` AS TIMESTAMP), CAST(`Chegada_Real` AS TIMESTAMP))
    ELSE NULL
  END AS minutos_recuperados,
  
  -- Auditoria (manter colunas bronze)
  _source_file AS origem_arquivo,
  _ingestion_timestamp AS transformado_em
FROM mizukiairflows.bronze.vra;

-- COMMAND ----------

-- DBTITLE 1,3. A prova que importa: mesma contagem
-- MAGIC %md
-- MAGIC ## 3. A prova que importa: mesma contagem
-- MAGIC
-- MAGIC Este é o critério objetivo do marco. **Se a diferença não for zero**, a silver não é espelho — é recorte, e alguém em algum momento vai fazer uma pergunta que ela não consegue mais responder.
-- MAGIC
-- MAGIC **A tipagem funcionou? Contagens de conversões bem-sucedidas por coluna.**

-- COMMAND ----------

-- DBTITLE 1,Validar contagem: bronze vs silver
-- Validar contagens: bronze vs silver
-- O número de linhas DEVE ser idêntico

SELECT
  (SELECT COUNT(*) FROM mizukiairflows.bronze.vra) AS bronze_vra,
  (SELECT COUNT(*) FROM mizukiairflows.silver.vra) AS silver_vra,
  (SELECT COUNT(*) FROM mizukiairflows.bronze.vra) - (SELECT COUNT(*) FROM mizukiairflows.silver.vra) AS diferenca;

-- COMMAND ----------

-- DBTITLE 1,Validar conversões de tipagem
-- Validar sucesso das conversões de timestamp
-- Contar quantas conversões foram bem-sucedidas

SELECT
  COUNT(*) AS total_linhas,
  COUNT(partida_real_data) AS partida_real_ok,
  COUNT(chegada_prevista_hora) AS chegada_prevista_ok,
  COUNT(chegada_real_hora) AS chegada_real_ok,
  COUNT(atraso_partida_min) AS atraso_partida_ok,
  COUNT(atraso_chegada_min) AS atraso_chegada_min,
  COUNT(minutos_recuperados) AS minutos_recuperados_ok
FROM mizukiairflows.silver.vra;

-- COMMAND ----------

-- DBTITLE 1,4. silver.empresas — O caso clássico dos dois sistemas
-- MAGIC %md
-- MAGIC ## 4. silver.empresas — O caso clássico dos dois sistemas
-- MAGIC
-- MAGIC Aqui a silver faz a **única coisa que muda a forma da tabela: unifica dois cadastros do mesmo assunto**.
-- MAGIC
-- MAGIC Nacionais_aereas_nacionais, estrangeiras_aereas_estrangeiras. Mesmo grão, contagens iguais, mas silver é a soma exata das duas, e o usuário cadastra guarda por registro de onde ele veio. Quem quiser voltar e olhar só as estrangeiras, converge. Nada fecha.
-- MAGIC
-- MAGIC O que está proibido: um WHERE situacao = 'ATIVA' aqui. Empresas que encerrou operação continua tendo voo no período histórico — filtra aqui e o histórico dela desaparece.
-- MAGIC
-- MAGIC **Estratégia:**
-- MAGIC * UNION ALL das duas tabelas
-- MAGIC * Adicionar coluna `origem_cadastro` para rastreabilidade ('nacional' ou 'estrangeira')

-- COMMAND ----------

-- DBTITLE 1,Criar tabela silver.empresas
CREATE OR REPLACE TABLE mizukiairflows.silver.empresas
COMMENT 'Cadastro unificado de empresas aéreas: nacionais + estrangeiras com origem rastreada'
AS
-- Empresas Nacionais
SELECT
  icao,
  iata,
  razao_social,
  cnpj,
  atividades_aereas AS servico,
  cidade,
  uf,
  cep,
  telefone,
  email,
  situacao,
  decisao_operacional,
  data_decisao_operacional,
  validade_operacional,
  id_empresa_aerea,
  endereco_sede,
  'nacional' AS origem_cadastro,
  _source_file AS origem_arquivo,
  _ingestion_timestamp AS transformado_em
FROM mizukiairflows.bronze.empresas_aereas_nacionais
-- NÃO FILTRAR HEADERS: Silver é espelho do Bronze, mesma contagem de linhas

UNION ALL

-- Empresas Estrangeiras
SELECT
  ICAO AS icao,
  NULL AS iata,  -- Não disponível para estrangeiras
  Razao AS razao_social,
  NULL AS cnpj,  -- Não aplicável para estrangeiras
  Servico AS servico,
  Cidade AS cidade,
  UF AS uf,
  CEP AS cep,
  Telefone AS telefone,
  Email AS email,
  Ativa AS situacao,
  Instrumento AS decisao_operacional,
  Data AS data_decisao_operacional,
  NULL AS validade_operacional,
  NULL AS id_empresa_aerea,
  Endereco AS endereco_sede,
  'estrangeira' AS origem_cadastro,
  _source_file AS origem_arquivo,
  _ingestion_timestamp AS transformado_em
FROM mizukiairflows.bronze.empresas_aereas_estrangeiras;
-- NÃO FILTRAR HEADERS: Silver é espelho do Bronze, mesma contagem de linhas

-- COMMAND ----------

-- DBTITLE 1,Validar unificação: nacionais + estrangeiras = empresas
-- Validar unificação: a contagem total deve ser a soma exata

SELECT
  (SELECT COUNT(*) FROM mizukiairflows.bronze.empresas_aereas_nacionais) AS bronze_nacionais,
  (SELECT COUNT(*) FROM mizukiairflows.bronze.empresas_aereas_estrangeiras) AS bronze_estrangeiras,
  (SELECT COUNT(*) FROM mizukiairflows.silver.empresas) AS silver_empresas,
  (SELECT COUNT(*) FROM mizukiairflows.silver.empresas WHERE origem_cadastro = 'nacional') AS silver_nacionais,
  (SELECT COUNT(*) FROM mizukiairflows.silver.empresas WHERE origem_cadastro = 'estrangeira') AS silver_estrangeiras;

-- COMMAND ----------

-- DBTITLE 1,5. silver.aerodromos e silver.codigos_operacao — Espelhos
-- MAGIC %md
-- MAGIC ## 5. silver.aerodromos e silver.codigos_operacao — Espelhos
-- MAGIC
-- MAGIC **Uma tabela de referência para cada uma do bronze, tipada e documentada.**
-- MAGIC
-- MAGIC Duas coisas valem comentário:
-- MAGIC
-- MAGIC 1. **altitude** vem como "393,4" — vírgula decimal. Vira DOUBLE com um `replace`
-- MAGIC 2. **A coluna df_i**: o cabecinho chamava isso de "df". "São Paulo" é o **nome da unidade federativa por extenso**, não só sigla. Quem escrever `WHERE uf = "SP"` recebe zero linhas e vai achar que o dado sumiu. O nome da coluna passa a dizer a verdade (`uf_nome`) e o COMMENT avisa. Renomear e documentar a governança. Investir a sigla pressa a fazer na verdade.

-- COMMAND ----------

-- DBTITLE 1,Criar tabela silver.aerodromos
CREATE OR REPLACE TABLE mizukiairflows.silver.aerodromos
COMMENT 'Cadastro de aeródromos públicos tipado: altitude em DOUBLE, coordenadas estruturadas'
AS
SELECT
  `Código OACI` AS icao,
  CIAD AS ciad,
  Nome AS nome,
  `Município` AS municipio,
  
  -- Importante: UF é o nome por extenso, não sigla!
  UF AS uf_nome,
  `Município Servido` AS municipio_servido,
  `UF Servido` AS uf_servido_nome,
  
  -- Altitude: converter vírgula para ponto e tipar como DOUBLE
  TRY_CAST(REPLACE(Altitude, ',', '.') AS DOUBLE) AS altitude_m,
  
  -- Coordenadas: manter como string (formato graus/minutos/segundos)
  Latitude AS latitude,
  Longitude AS longitude,
  LATGEOPOINT AS latgeopoint,
  LONGEOPOINT AS longeopoint,
  
  -- Operação
  `Operação Diurna` AS operacao_diurna,
  `Operação Noturna` AS operacao_noturna,
  `Situação` AS situacao,
  
  -- Registro e validade
  `Validade do Registro` AS validade_registro,
  `Portaria de Registro` AS portaria_registro,
  `Link Portaria` AS link_portaria,
  
  -- Status das coordenadas
  CASE 
    WHEN Latitude IS NOT NULL AND Longitude IS NOT NULL 
    THEN 'coordenadas_presentes'
    ELSE 'coordenadas_ausentes'
  END AS status_coordenadas,
  
  -- Auditoria
  _source_file AS origem_arquivo,
  _ingestion_timestamp AS transformado_em
FROM mizukiairflows.bronze.aerodromos_publicos
WHERE `Código OACI` != 'Código OACI';  -- Excluir headers duplicados

-- COMMAND ----------

-- DBTITLE 1,6. Metadados gerenciados
-- MAGIC %md
-- MAGIC ## 6. Metadados gerenciados
-- MAGIC
-- MAGIC **Documentação não é enfeite:** o consumidor final deste pipeline é um **LLM** e o **COMMENT** é literalmente o que ele lê para decidir qual coluna usar.
-- MAGIC
-- MAGIC Colunas sem comentários é colunas que a IA vai usar errado.
-- MAGIC
-- MAGIC O comentado devem **significado de negócio, não tipo de dado**. "TIMESTAMP de partida" não ajuda ninguém — "horário em que a aeronave efetivamente saiu do solo" ajuda.
-- MAGIC
-- MAGIC **Importante:** Não usaremos comandos ALTER TABLE individuais. Vamos usar um loop Python para adicionar comments em todas as colunas de forma programática.

-- COMMAND ----------

-- DBTITLE 1,Adicionar comentários em colunas silver.vra
-- MAGIC %python
-- MAGIC # Dicionário de comentários para silver.vra
-- MAGIC COMENTARIOS_VRA = {
-- MAGIC     "icao_empresa": "Código ICAO de tres letras da empresa aérea que operou o voo. Chave para silver.empresas.",
-- MAGIC     "numero_voo": "Número do voo divulgado pela companhia. Identificador comercial, não numérico.",
-- MAGIC     "codigo_di": "Código DI de escala e regime entre dados.",
-- MAGIC     "codigo_tipo_linha": "Código de tipo de voo: N (nacional), I (internacional), R (regional).",
-- MAGIC     "icao_origem": "Código ICAO de aeródromo de onde o voo partiu. Chave para silver.aerodromos.",
-- MAGIC     "icao_destino": "Código ICAO de aeródromo onde o voo pousou. Chave para silver.aerodromos.",
-- MAGIC     "partida_prevista_data": "Data da partida programada, separada para facilitar análise por dia.",
-- MAGIC     "partida_prevista_hora": "Horário da partida programada pela companhia, na hora local do aeroporto de origem.",
-- MAGIC     "partida_real_data": "Data da partida efetiva.",
-- MAGIC     "partida_real_hora": "Horário em que a aeronave efetivamente saiu do solo (decolação real).",
-- MAGIC     "chegada_prevista_data": "Data da chegada programada.",
-- MAGIC     "chegada_prevista_hora": "Horário da chegada programada pela companhia, na hora local de destino.",
-- MAGIC     "chegada_real_data": "Data da chegada efetiva.",
-- MAGIC     "chegada_real_hora": "Horário em que o avião pousou efetivamente (aterrisagem real).",
-- MAGIC     "situacao_voo": "Situação final do voo: realizado, cancelado, desviado, etc.",
-- MAGIC     "codigo_justificativa": "Código de justificativa para atrasos ou cancelamentos pela ANAC.",
-- MAGIC     "atraso_partida_min": "Diferença em minutos entre partida real e prevista. Positivo = atrasou, negativo = adiantou.",
-- MAGIC     "atraso_chegada_min": "Diferença em minutos entre chegada real e prevista. Positivo = atrasou, negativo = adiantou.",
-- MAGIC     "minutos_recuperados": "Diferença entre atraso_partida e atraso_chegada. Positivo = recuperou tempo no ar.",
-- MAGIC     "origem_arquivo": "Caminho completo do arquivo CSV de origem no volume bronze.",
-- MAGIC     "transformado_em": "Timestamp de quando esta linha foi transformada na silver."
-- MAGIC }
-- MAGIC
-- MAGIC # Aplicar comentários
-- MAGIC for coluna, comentario in COMENTARIOS_VRA.items():
-- MAGIC     spark.sql(f"ALTER TABLE mizukiairflows.silver.vra ALTER COLUMN {coluna} COMMENT '{comentario}'")
-- MAGIC
-- MAGIC print(f"✅ {len(COMENTARIOS_VRA)} colunas comentadas em silver.vra")

-- COMMAND ----------

-- DBTITLE 1,Adicionar comentários em outras tabelas Silver
-- MAGIC %python
-- MAGIC # Dicionários de comentários para outras tabelas
-- MAGIC
-- MAGIC COMENTARIOS_EMPRESAS = {
-- MAGIC     "icao": "Código ICAO de tres letras da empresa. Vazio para operadores sem código (aviacao geral).",
-- MAGIC     "iata": "Código IATA de duas letras, comum em sistemas comerciais.",
-- MAGIC     "razao_social": "Razão social da empresa aérea, o nome que aparece no contrato da ANAC.",
-- MAGIC     "cnpj": "CNPJ da empresa (apenas nacionais).",
-- MAGIC     "servico": "Tipo de serviço aéreo prestado pela empresa.",
-- MAGIC     "cidade": "Cidade da sede da empresa.",
-- MAGIC     "uf": "Unidade federativa da sede.",
-- MAGIC     "cep": "CEP da sede da empresa.",
-- MAGIC     "telefone": "Telefone de contato da empresa.",
-- MAGIC     "email": "Email de contato da empresa.",
-- MAGIC     "situacao": "Situação operacional da empresa: ativa, suspensa, etc.",
-- MAGIC     "decisao_operacional": "Decisão ou instrumento operacional da empresa.",
-- MAGIC     "data_decisao_operacional": "Data da decisão operacional.",
-- MAGIC     "validade_operacional": "Validade da autorização operacional.",
-- MAGIC     "id_empresa_aerea": "Identificador único da empresa aérea (apenas nacionais).",
-- MAGIC     "endereco_sede": "Endereço completo da sede da empresa.",
-- MAGIC     "origem_cadastro": "Origem dos dados: nacional ou estrangeira. Para filtrar por tipo de empresa.",
-- MAGIC     "origem_arquivo": "Caminho do arquivo bronze de origem.",
-- MAGIC     "transformado_em": "Timestamp de transformação na silver."
-- MAGIC }
-- MAGIC
-- MAGIC COMENTARIOS_AERODROMOS = {
-- MAGIC     "icao": "Código ICAO de quatro letras. Identificador internacional padrão de aeroportos.",
-- MAGIC     "ciad": "Código CIAD do aeródromo (identificador nacional).",
-- MAGIC     "nome": "Nome oficial do aeródromo.",
-- MAGIC     "municipio": "Município onde o aeródromo está localizado.",
-- MAGIC     "uf_nome": "Nome da unidade federativa por extenso. Nao e sigla.",
-- MAGIC     "municipio_servido": "Município principal servido pelo aeródromo.",
-- MAGIC     "uf_servido_nome": "UF do município servido (nome por extenso).",
-- MAGIC     "altitude_m": "Altitude do aeródromo em metros acima do nível do mar.",
-- MAGIC     "latitude": "Coordenada de latitude (formato original: graus/minutos/segundos).",
-- MAGIC     "longitude": "Coordenada de longitude (formato original: graus/minutos/segundos).",
-- MAGIC     "latgeopoint": "Latitude em formato geopoint decimal.",
-- MAGIC     "longeopoint": "Longitude em formato geopoint decimal.",
-- MAGIC     "operacao_diurna": "Indicador de operação diurna permitida.",
-- MAGIC     "operacao_noturna": "Indicador de operação noturna permitida.",
-- MAGIC     "situacao": "Situação operacional do aeródromo.",
-- MAGIC     "validade_registro": "Data de validade do registro do aeródromo.",
-- MAGIC     "portaria_registro": "Número da portaria de registro.",
-- MAGIC     "link_portaria": "Link para a portaria de registro.",
-- MAGIC     "status_coordenadas": "Indicador se coordenadas estao presentes ou ausentes.",
-- MAGIC     "origem_arquivo": "Caminho do arquivo bronze de origem.",
-- MAGIC     "transformado_em": "Timestamp de transformação na silver."
-- MAGIC }
-- MAGIC
-- MAGIC # Aplicar comentários em silver.empresas
-- MAGIC for coluna, comentario in COMENTARIOS_EMPRESAS.items():
-- MAGIC     spark.sql(f"ALTER TABLE mizukiairflows.silver.empresas ALTER COLUMN {coluna} COMMENT '{comentario}'")
-- MAGIC
-- MAGIC print(f"✅ {len(COMENTARIOS_EMPRESAS)} colunas comentadas em silver.empresas")
-- MAGIC
-- MAGIC # Aplicar comentários em silver.aerodromos
-- MAGIC for coluna, comentario in COMENTARIOS_AERODROMOS.items():
-- MAGIC     spark.sql(f"ALTER TABLE mizukiairflows.silver.aerodromos ALTER COLUMN {coluna} COMMENT '{comentario}'")
-- MAGIC
-- MAGIC print(f"✅ {len(COMENTARIOS_AERODROMOS)} colunas comentadas em silver.aerodromos")

-- COMMAND ----------

-- DBTITLE 1,7. Auditoria da governança: 100% das colunas comentadas?
-- MAGIC %md
-- MAGIC ## 7. Auditoria da governança: 100% das colunas comentadas?
-- MAGIC
-- MAGIC **"Documentar tudo" é afirmação, não fato.**
-- MAGIC
-- MAGIC O `information_schema` responde de verdade.
-- MAGIC
-- MAGIC Se tem uma coluna não comentada, o GROUP BY table_name mostra onde.

-- COMMAND ----------

-- DBTITLE 1,Verificar colunas sem comentários
-- Auditoria: encontrar colunas sem comentários na camada Silver

SELECT 
  table_name,
  COUNT(*) AS colunas,
  SUM(CASE WHEN comment IS NULL OR comment = '' THEN 1 ELSE 0 END) AS sem_comentario,
  ROUND(100.0 * SUM(CASE WHEN comment IS NOT NULL AND comment != '' THEN 1 ELSE 0 END) / COUNT(*), 1) AS pct_documentado
FROM system.information_schema.columns
WHERE table_schema = 'silver'
  AND table_catalog = 'mizukiairflows'
GROUP BY table_name
ORDER BY pct_documentado;

-- COMMAND ----------

-- DBTITLE 1,Listar colunas específicas sem comentários
-- Detalhar quais colunas ainda precisam de comentários

SELECT 
  table_name,
  column_name,
  data_type
FROM system.information_schema.columns
WHERE table_schema = 'silver'
  AND table_catalog = 'mizukiairflows'
  AND (comment IS NULL OR comment = '')
ORDER BY table_name, ordinal_position;

-- COMMAND ----------

-- DBTITLE 1,8. Fechamento do marco
-- MAGIC %md
-- MAGIC ## 8. Fechamento do marco
-- MAGIC
-- MAGIC A silver tem **quatro tabelas**, todas espelho do bronze, todas documentadas, e a vra com **exatamente a mesma contagem de linhas** da casa.
-- MAGIC
-- MAGIC O que **não** está aqui de propósito: `partida_pontual`, `except`, qualquer agregação.
-- MAGIC
-- MAGIC O limiar de 15 minutos é uma decisão do cliente — outra separação pode trabalhar com 30. Se ele estivesse cruzado na silver, atender esse outro cliente significaria reprocessar a camada inteira.
-- MAGIC
-- MAGIC **Na gold, é uma linha de SQL.**

-- COMMAND ----------

-- DBTITLE 1,Resumo final: todas as tabelas Silver
-- Resumo: verificar todas as tabelas silver criadas

SELECT 
  'vra' AS tabela,
  (SELECT COUNT(*) FROM mizukiairflows.silver.vra) AS registros,
  (SELECT COUNT(DISTINCT column_name) FROM system.information_schema.columns 
   WHERE table_catalog = 'mizukiairflows' AND table_schema = 'silver' AND table_name = 'vra') AS colunas
UNION ALL
SELECT 
  'empresas',
  (SELECT COUNT(*) FROM mizukiairflows.silver.empresas),
  (SELECT COUNT(DISTINCT column_name) FROM system.information_schema.columns 
   WHERE table_catalog = 'mizukiairflows' AND table_schema = 'silver' AND table_name = 'empresas')
UNION ALL
SELECT 
  'aerodromos',
  (SELECT COUNT(*) FROM mizukiairflows.silver.aerodromos),
  (SELECT COUNT(DISTINCT column_name) FROM system.information_schema.columns 
   WHERE table_catalog = 'mizukiairflows' AND table_schema = 'silver' AND table_name = 'aerodromos');

-- COMMAND ----------

-- DBTITLE 1,Adicionar tags e metadados nas tabelas
-- MAGIC %python
-- MAGIC # Adicionar tags nas tabelas Silver para governança
-- MAGIC # Tags são metadados de busca e política de acesso
-- MAGIC
-- MAGIC for tabela, comentario, tags in [
-- MAGIC     ("mizukiairflows.silver.vra", "camada silver", "vra, voos, anac, silver"),
-- MAGIC     ("mizukiairflows.silver.empresas", "camada silver", "empresas, companhias, silver"),
-- MAGIC     ("mizukiairflows.silver.aerodromos", "camada silver", "aerodromos, aeroportos, silver")
-- MAGIC ]:
-- MAGIC     # Comentar tabela
-- MAGIC     spark.sql(f"COMMENT ON TABLE {tabela} IS '{comentario}'")
-- MAGIC     
-- MAGIC     # Adicionar tags
-- MAGIC     spark.sql(f"ALTER TABLE {tabela} SET TAGS ('camada' = 'silver', 'dominio' = 'aviacao')")
-- MAGIC     
-- MAGIC     print(f"✅ Tags adicionadas: {tabela}")
-- MAGIC
-- MAGIC print("\n✅ Camada Silver concluída: 3 tabelas documentadas e governadas")

-- COMMAND ----------

-- DBTITLE 1,9. Data Quality: Função de Validação ICAO
-- MAGIC %md
-- MAGIC ## 9. Data Quality: Processo Integrado de Validação
-- MAGIC
-- MAGIC **Garantia de qualidade:** Nenhum registro com ICAO inválido entra na Silver.
-- MAGIC
-- MAGIC **Estratégia:**
-- MAGIC 1. Função `validar_icao()` já criada no processo de DQ
-- MAGIC 2. Aplicar validação nas tabelas empresas e vra
-- MAGIC 3. Registros inválidos vão para quarentena (já existe)
-- MAGIC 4. Auditoria automática de cada carga

-- COMMAND ----------

-- DBTITLE 1,Validar existência da função de DQ
-- Verificar se função de validação existe
USE CATALOG mizukiairflows;
SHOW USER FUNCTIONS IN silver LIKE 'validar*'

-- COMMAND ----------

-- DBTITLE 1,Validar ICAO nas tabelas Silver
-- Aplicar validação ICAO nas tabelas principais
-- Este é um checkpoint: quantos ICAOs inválidos temos?

SELECT 
  'empresas' as tabela,
  COUNT(*) as total_registros,
  SUM(CASE WHEN mizukiairflows.silver.validar_icao(icao).valido = FALSE THEN 1 ELSE 0 END) as icao_invalidos,
  ROUND(100.0 * SUM(CASE WHEN mizukiairflows.silver.validar_icao(icao).valido = TRUE THEN 1 ELSE 0 END) / COUNT(*), 2) as pct_validos
FROM mizukiairflows.silver.empresas

UNION ALL

SELECT 
  'vra',
  COUNT(*),
  SUM(CASE WHEN mizukiairflows.silver.validar_icao(icao_empresa).valido = FALSE THEN 1 ELSE 0 END),
  ROUND(100.0 * SUM(CASE WHEN mizukiairflows.silver.validar_icao(icao_empresa).valido = TRUE THEN 1 ELSE 0 END) / COUNT(*), 2)
FROM mizukiairflows.silver.vra

UNION ALL

SELECT 
  'aerodromos',
  COUNT(*),
  SUM(CASE WHEN mizukiairflows.silver.validar_icao(icao).valido = FALSE THEN 1 ELSE 0 END),
  ROUND(100.0 * SUM(CASE WHEN mizukiairflows.silver.validar_icao(icao).valido = TRUE THEN 1 ELSE 0 END) / COUNT(*), 2)
FROM mizukiairflows.silver.aerodromos;

-- COMMAND ----------

-- DBTITLE 1,Validar correção: contagens Bronze = Silver
-- VALIDAÇÃO FINAL: Todas as tabelas devem ter mesma contagem do Bronze

SELECT 
  'vra' as tabela,
  (SELECT COUNT(*) FROM mizukiairflows.bronze.vra) AS bronze,
  (SELECT COUNT(*) FROM mizukiairflows.silver.vra) AS silver,
  (SELECT COUNT(*) FROM mizukiairflows.bronze.vra) - (SELECT COUNT(*) FROM mizukiairflows.silver.vra) AS diferenca,
  CASE 
    WHEN (SELECT COUNT(*) FROM mizukiairflows.bronze.vra) = (SELECT COUNT(*) FROM mizukiairflows.silver.vra) 
    THEN '✅ OK' 
    ELSE '❌ ERRO' 
  END as status

UNION ALL

SELECT 
  'aerodromos',
  (SELECT COUNT(*) FROM mizukiairflows.bronze.aerodromos_publicos),
  (SELECT COUNT(*) FROM mizukiairflows.silver.aerodromos),
  (SELECT COUNT(*) FROM mizukiairflows.bronze.aerodromos_publicos) - (SELECT COUNT(*) FROM mizukiairflows.silver.aerodromos),
  CASE 
    WHEN (SELECT COUNT(*) FROM mizukiairflows.bronze.aerodromos_publicos) = (SELECT COUNT(*) FROM mizukiairflows.silver.aerodromos) 
    THEN '✅ OK' 
    ELSE '❌ ERRO' 
  END

UNION ALL

SELECT 
  'empresas (soma)',
  (SELECT COUNT(*) FROM mizukiairflows.bronze.empresas_aereas_nacionais) + (SELECT COUNT(*) FROM mizukiairflows.bronze.empresas_aereas_estrangeiras),
  (SELECT COUNT(*) FROM mizukiairflows.silver.empresas),
  ((SELECT COUNT(*) FROM mizukiairflows.bronze.empresas_aereas_nacionais) + (SELECT COUNT(*) FROM mizukiairflows.bronze.empresas_aereas_estrangeiras)) - (SELECT COUNT(*) FROM mizukiairflows.silver.empresas),
  CASE 
    WHEN ((SELECT COUNT(*) FROM mizukiairflows.bronze.empresas_aereas_nacionais) + (SELECT COUNT(*) FROM mizukiairflows.bronze.empresas_aereas_estrangeiras)) = (SELECT COUNT(*) FROM mizukiairflows.silver.empresas) 
    THEN '✅ OK' 
    ELSE '❌ ERRO' 
  END;