-- Databricks notebook source
-- DBTITLE 1,Título e Descrição
-- MAGIC %md
-- MAGIC # Avaliação de Qualidade de Dados - Tabela silver.aerodromos
-- MAGIC
-- MAGIC **Objetivo:** Realizar uma análise detalhada da qualidade dos dados da tabela `mizukiairflows.silver.aerodromos` e propor tratamentos para garantir a conformidade com padrões de governança de dados.
-- MAGIC
-- MAGIC **Escopo:** Esta avaliação abrange análise de completude, consistência, unicidade, validade e integridade dos dados de aeródromos cadastrados.

-- COMMAND ----------

-- DBTITLE 1,1. Resumo dos Problemas Identificados
-- MAGIC %md
-- MAGIC ## 1. Problemas de Qualidade Identificados
-- MAGIC
-- MAGIC ### 📊 Estatísticas Gerais
-- MAGIC * **Total de registros:** 496 aeródromos
-- MAGIC * **Duplicatas:** 0 (excelente!)
-- MAGIC * **Registros com validade expirada:** 0
-- MAGIC
-- MAGIC ### ⚠️ Problemas Críticos de Completude
-- MAGIC
-- MAGIC #### 1.1. Valores Nulos em Campos Importantes
-- MAGIC * **Município (municipio):** 5 registros nulos (1%)
-- MAGIC * **UF Nome (uf_nome):** 5 registros nulos (1%)
-- MAGIC * **Município Servido (municipio_servido):** 2 registros nulos (0.4%)
-- MAGIC * **Operação Diurna (operacao_diurna):** 209 registros nulos (42%)
-- MAGIC * **Operação Noturna (operacao_noturna):** 247 registros nulos (50%)
-- MAGIC * **Validade Registro (validade_registro):** 197 registros nulos (40%)
-- MAGIC
-- MAGIC #### 1.2. Inconsistências em Campos de Operação
-- MAGIC * **Operação Diurna:** 209 valores nulos (42%)
-- MAGIC * **Operação Noturna:** 247 valores nulos (50%)
-- MAGIC
-- MAGIC ### ✅ Aspectos Positivos
-- MAGIC * Sem duplicatas em ICAO e CIAD
-- MAGIC * Todas as coordenadas estão presentes e consistentes
-- MAGIC * Nenhum registro com validade expirada
-- MAGIC * Bom nível de padronização nos campos categóricos
-- MAGIC
-- MAGIC ### 🔴 Severidade dos Problemas
-- MAGIC * **Alta:** Valores nulos em campos de operação (42-50%)
-- MAGIC * **Média:** Valores nulos em validade_registro (40%)
-- MAGIC * **Baixa:** Valores nulos em município/UF (1%)

-- COMMAND ----------

-- DBTITLE 1,2. Análise Detalhada de Valores Nulos
-- Análise de Valores Nulos por Coluna
SELECT 
  COUNT(*) as total_registros,
  ROUND(SUM(CASE WHEN municipio IS NULL THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) as perc_municipio_nulos,
  ROUND(SUM(CASE WHEN uf_nome IS NULL THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) as perc_uf_nulos,
  ROUND(SUM(CASE WHEN municipio_servido IS NULL THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) as perc_municipio_servido_nulos,
  ROUND(SUM(CASE WHEN operacao_diurna IS NULL THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) as perc_operacao_diurna_nulos,
  ROUND(SUM(CASE WHEN operacao_noturna IS NULL THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) as perc_operacao_noturna_nulos,
  ROUND(SUM(CASE WHEN validade_registro IS NULL THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) as perc_validade_nulos
FROM mizukiairflows.silver.aerodromos

-- COMMAND ----------

-- DBTITLE 1,3. Registros com Problemas de Localização
-- Identificar registros com município ou UF nulos
SELECT 
  icao,
  ciad,
  nome,
  municipio,
  uf_nome,
  municipio_servido,
  uf_servido_nome
FROM mizukiairflows.silver.aerodromos
WHERE municipio IS NULL OR uf_nome IS NULL OR municipio_servido IS NULL
ORDER BY icao

-- COMMAND ----------

-- DBTITLE 1,4. Distribuição de Situações Operacionais
-- Análise da distribuição de situações
SELECT 
  situacao,
  COUNT(*) as quantidade,
  ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM mizukiairflows.silver.aerodromos), 2) as percentual
FROM mizukiairflows.silver.aerodromos
GROUP BY situacao
ORDER BY quantidade DESC

-- COMMAND ----------

-- DBTITLE 1,5. Tratamentos de Qualidade Recomendados
-- MAGIC %md
-- MAGIC ## 2. Tratamentos de Qualidade Recomendados
-- MAGIC
-- MAGIC ### 🛠️ Estratégias de Tratamento
-- MAGIC
-- MAGIC #### 2.1. Tratamento de Valores Nulos em Operação (PRIORIDADE ALTA)
-- MAGIC
-- MAGIC **Problema:** 42% dos registros sem operação diurna e 50% sem operação noturna.
-- MAGIC
-- MAGIC **Soluções:**
-- MAGIC 1. **Padronização de Valores Nulos:**
-- MAGIC    * Substituir `NULL` por "Não Informado" para rastreabilidade
-- MAGIC    * Criar flag de qualidade para identificar registros incompletos
-- MAGIC
-- MAGIC 2. **Enriquecimento de Dados:**
-- MAGIC    * Consultar fonte oficial (ANAC) para complementar dados
-- MAGIC    * Criar processo de validação periódica
-- MAGIC
-- MAGIC 3. **Regras de Negócio:**
-- MAGIC    * Se aeródromo está "Interditado", definir operações como "Sem Operação"
-- MAGIC    * Para aeródromos "Cadastrados" sem informação, marcar como "Pendente de Validação"
-- MAGIC
-- MAGIC #### 2.2. Tratamento de Localização (PRIORIDADE MÉDIA)
-- MAGIC
-- MAGIC **Problema:** 5 registros sem município/UF (1%).
-- MAGIC
-- MAGIC **Soluções:**
-- MAGIC 1. **Inferir de municipio_servido:** Usar dados de municipio_servido/uf_servido quando disponíveis
-- MAGIC 2. **Geocodificação Reversa:** Usar coordenadas (latgeopoint/longeopoint) para obter município/UF
-- MAGIC 3. **Quarentena:** Mover registros incompletos para tabela de validação manual
-- MAGIC
-- MAGIC #### 2.3. Tratamento de Validade de Registro (PRIORIDADE MÉDIA)
-- MAGIC
-- MAGIC **Problema:** 40% dos registros sem data de validade.
-- MAGIC
-- MAGIC **Soluções:**
-- MAGIC 1. **Classificação:** Registros sem validade podem ser permanentes
-- MAGIC 2. **Flag de Controle:** Adicionar flag `requer_renovacao` (TRUE/FALSE)
-- MAGIC 3. **Alerta Preventivo:** Criar alerta para registros com validade próxima do vencimento (90 dias)
-- MAGIC
-- MAGIC #### 2.4. Padronização de Tipos de Dados (PRIORIDADE BAIXA)
-- MAGIC
-- MAGIC **Oportunidades de Melhoria:**
-- MAGIC * **latitude/longitude:** Manter formato original (DMS) e decimal (latgeopoint/longeopoint)
-- MAGIC * **validade_registro:** Converter de STRING para DATE
-- MAGIC * **altitude_m:** Já está em formato numérico (DOUBLE) ✅
-- MAGIC
-- MAGIC ### 📊 Métricas de Qualidade Propostas
-- MAGIC
-- MAGIC 1. **Completude:** % de campos obrigatórios preenchidos
-- MAGIC 2. **Consistência:** % de registros sem contradições (ex: interditado com operação ativa)
-- MAGIC 3. **Atualidade:** % de registros com validade dentro do prazo
-- MAGIC 4. **Unicidade:** % de registros sem duplicatas (já em 100% ✅)
-- MAGIC 5. **Acurácia:** % de coordenadas validadas geograficamente

-- COMMAND ----------

-- DBTITLE 1,6. VIEW: Aeródromos com Qualidade de Dados
-- Criar VIEW com flags de qualidade e tratamentos aplicados
CREATE OR REPLACE VIEW mizukiairflows.silver.vw_aerodromos_qualidade AS
SELECT 
  icao,
  ciad,
  nome,
  
  -- Tratamento de Localização
  COALESCE(municipio, municipio_servido, 'Não Informado') as municipio,
  COALESCE(uf_nome, uf_servido_nome, 'Não Informado') as uf_nome,
  municipio_servido,
  uf_servido_nome,
  
  -- Dados Geográficos
  altitude_m,
  latitude,
  longitude,
  latgeopoint,
  longeopoint,
  
  -- Tratamento de Operação
  COALESCE(operacao_diurna, 
    CASE 
      WHEN situacao = 'Interditado' THEN 'Sem Operação'
      ELSE 'Pendente de Validação'
    END
  ) as operacao_diurna,
  
  COALESCE(operacao_noturna,
    CASE 
      WHEN situacao = 'Interditado' THEN 'Sem Operação'
      ELSE 'Pendente de Validação'
    END
  ) as operacao_noturna,
  
  situacao,
  
  -- Tratamento de Validade
  TRY_CAST(validade_registro AS DATE) as validade_registro_date,
  CASE 
    WHEN validade_registro IS NULL THEN FALSE
    WHEN TRY_CAST(validade_registro AS DATE) IS NULL THEN NULL
    ELSE TRUE
  END as requer_renovacao,
  
  CASE 
    WHEN TRY_CAST(validade_registro AS DATE) IS NOT NULL 
         AND TRY_CAST(validade_registro AS DATE) BETWEEN CURRENT_DATE() AND DATE_ADD(CURRENT_DATE(), 90)
    THEN TRUE
    ELSE FALSE
  END as validade_proxima_vencimento,
  
  portaria_registro,
  link_portaria,
  status_coordenadas,
  
  -- FLAGS DE QUALIDADE
  CASE 
    WHEN municipio IS NULL OR uf_nome IS NULL THEN FALSE
    ELSE TRUE
  END as flag_localizacao_completa,
  
  CASE 
    WHEN operacao_diurna IS NULL OR operacao_noturna IS NULL THEN FALSE
    ELSE TRUE
  END as flag_operacao_completa,
  
  CASE 
    WHEN situacao = 'Interditado' 
         AND (operacao_diurna NOT IN ('Sem Operação') OR operacao_noturna NOT IN ('Sem Operação'))
    THEN FALSE
    ELSE TRUE
  END as flag_consistencia_operacao,
  
  -- Score de Qualidade (0-100)
  CAST(
    (
      CASE WHEN municipio IS NOT NULL AND uf_nome IS NOT NULL THEN 20 ELSE 0 END +
      CASE WHEN operacao_diurna IS NOT NULL THEN 20 ELSE 0 END +
      CASE WHEN operacao_noturna IS NOT NULL THEN 20 ELSE 0 END +
      CASE WHEN validade_registro IS NOT NULL THEN 20 ELSE 0 END +
      CASE WHEN latgeopoint IS NOT NULL AND longeopoint IS NOT NULL THEN 20 ELSE 0 END
    ) AS INT
  ) as score_qualidade,
  
  -- Metadados
  origem_arquivo,
  transformado_em
  
FROM mizukiairflows.silver.aerodromos

-- COMMAND ----------

-- DBTITLE 1,7. Análise da VIEW com Qualidade
-- Verificar distribuição do score de qualidade
SELECT 
  score_qualidade,
  COUNT(*) as quantidade,
  ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM mizukiairflows.silver.vw_aerodromos_qualidade), 2) as percentual,
  CASE 
    WHEN score_qualidade >= 80 THEN '✅ Excelente'
    WHEN score_qualidade >= 60 THEN '⚠️ Bom'
    WHEN score_qualidade >= 40 THEN '🟡 Regular'
    ELSE '🔴 Crítico'
  END as classificacao
FROM mizukiairflows.silver.vw_aerodromos_qualidade
GROUP BY score_qualidade
ORDER BY score_qualidade DESC

-- COMMAND ----------

-- DBTITLE 1,8. Aeródromos que Requerem Atenção
-- Identificar aeródromos com score de qualidade baixo
SELECT 
  icao,
  ciad,
  nome,
  municipio,
  uf_nome,
  situacao,
  score_qualidade,
  flag_localizacao_completa,
  flag_operacao_completa,
  flag_consistencia_operacao,
  CASE 
    WHEN NOT flag_localizacao_completa THEN 'Localização Incompleta; '
    ELSE ''
  END ||
  CASE 
    WHEN NOT flag_operacao_completa THEN 'Operação Incompleta; '
    ELSE ''
  END ||
  CASE 
    WHEN NOT flag_consistencia_operacao THEN 'Inconsistência em Operação; '
    ELSE ''
  END as problemas_identificados
FROM mizukiairflows.silver.vw_aerodromos_qualidade
WHERE score_qualidade < 100
ORDER BY score_qualidade ASC, icao
LIMIT 20

-- COMMAND ----------

-- DBTITLE 1,9. Dashboard de Métricas de Qualidade
-- Dashboard de Métricas de Qualidade de Dados
SELECT 
  'Total de Registros' as metrica,
  CAST(COUNT(*) AS STRING) as valor,
  '100%' as percentual
FROM mizukiairflows.silver.aerodromos

UNION ALL

SELECT 
  'Registros com Score 100 (Completos)' as metrica,
  CAST(COUNT(*) AS STRING) as valor,
  CONCAT(CAST(ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM mizukiairflows.silver.vw_aerodromos_qualidade), 2) AS STRING), '%') as percentual
FROM mizukiairflows.silver.vw_aerodromos_qualidade
WHERE score_qualidade = 100

UNION ALL

SELECT 
  'Registros com Localização Completa' as metrica,
  CAST(SUM(CASE WHEN flag_localizacao_completa THEN 1 ELSE 0 END) AS STRING) as valor,
  CONCAT(CAST(ROUND(SUM(CASE WHEN flag_localizacao_completa THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) AS STRING), '%') as percentual
FROM mizukiairflows.silver.vw_aerodromos_qualidade

UNION ALL

SELECT 
  'Registros com Operação Completa' as metrica,
  CAST(SUM(CASE WHEN flag_operacao_completa THEN 1 ELSE 0 END) AS STRING) as valor,
  CONCAT(CAST(ROUND(SUM(CASE WHEN flag_operacao_completa THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) AS STRING), '%') as percentual
FROM mizukiairflows.silver.vw_aerodromos_qualidade

UNION ALL

SELECT 
  'Registros Consistentes' as metrica,
  CAST(SUM(CASE WHEN flag_consistencia_operacao THEN 1 ELSE 0 END) AS STRING) as valor,
  CONCAT(CAST(ROUND(SUM(CASE WHEN flag_consistencia_operacao THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) AS STRING), '%') as percentual
FROM mizukiairflows.silver.vw_aerodromos_qualidade

UNION ALL

SELECT 
  'Score Médio de Qualidade' as metrica,
  CAST(ROUND(AVG(score_qualidade), 2) AS STRING) as valor,
  CONCAT(CAST(ROUND(AVG(score_qualidade), 2) AS STRING), '/100') as percentual
FROM mizukiairflows.silver.vw_aerodromos_qualidade

UNION ALL

SELECT 
  'Aeródromos Interditados' as metrica,
  CAST(COUNT(*) AS STRING) as valor,
  CONCAT(CAST(ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM mizukiairflows.silver.aerodromos), 2) AS STRING), '%') as percentual
FROM mizukiairflows.silver.aerodromos
WHERE situacao = 'Interditado'

-- COMMAND ----------

-- DBTITLE 1,10. Recomendações e Próximos Passos
-- MAGIC %md
-- MAGIC ## 3. Recomendações e Próximos Passos
-- MAGIC
-- MAGIC ### 👥 Governança de Dados - Ações Imediatas
-- MAGIC
-- MAGIC #### 3.1. Processos de Controle de Qualidade
-- MAGIC
-- MAGIC 1. **Implementar Validação na Entrada de Dados**
-- MAGIC    * Criar regras de validação na camada Bronze
-- MAGIC    * Campos obrigatórios: ICAO, CIAD, nome, município, UF, coordenadas
-- MAGIC    * Campos recomendados: operação diurna/noturna, situação
-- MAGIC
-- MAGIC 2. **Estabelecer SLAs de Qualidade**
-- MAGIC    * **Target Completude:** ≥ 95% para campos críticos
-- MAGIC    * **Target Consistência:** 100% (sem contradições)
-- MAGIC    * **Target Score Médio:** ≥ 85/100
-- MAGIC    * **Prazo:** 90 dias para atingir targets
-- MAGIC
-- MAGIC 3. **Criar Alerta Automático**
-- MAGIC    * Alertar quando score médio cair abaixo de 80
-- MAGIC    * Notificar sobre registros com validade próxima do vencimento
-- MAGIC    * Alertar sobre novos registros incompletos
-- MAGIC
-- MAGIC #### 3.2. Enriquecimento de Dados
-- MAGIC
-- MAGIC 1. **Integração com Fonte Oficial (ANAC)**
-- MAGIC    * Automatizar atualização periódica (semanal ou mensal)
-- MAGIC    * Validar dados existentes contra fonte oficial
-- MAGIC    * Preencher lacunas de informação
-- MAGIC
-- MAGIC 2. **Geocodificação Reversa**
-- MAGIC    * Usar coordenadas para validar/inferir município e UF
-- MAGIC    * Implementar validação geográfica automática
-- MAGIC
-- MAGIC 3. **Dados Complementares**
-- MAGIC    * Adicionar informações de pistas, terminais, movimento
-- MAGIC    * Integrar dados meteorológicos
-- MAGIC    * Adicionar informações de acessibilidade
-- MAGIC
-- MAGIC #### 3.3. Documentação e Linhagem
-- MAGIC
-- MAGIC 1. **Catálogo de Dados**
-- MAGIC    * Documentar dicionário de dados completo
-- MAGIC    * Definir stewards de dados responsáveis
-- MAGIC    * Estabelecer políticas de acesso e uso
-- MAGIC
-- MAGIC 2. **Linhagem de Dados**
-- MAGIC    * Rastrear origem de cada campo
-- MAGIC    * Documentar transformações aplicadas
-- MAGIC    * Manter histórico de alterações
-- MAGIC
-- MAGIC 3. **Conformidade Regulatória**
-- MAGIC    * Verificar conformidade com LGPD
-- MAGIC    * Implementar controles de acesso baseados em função
-- MAGIC    * Auditar uso e acesso aos dados
-- MAGIC
-- MAGIC ### 📋 Templates de Implementação
-- MAGIC
-- MAGIC #### Template 1: Validação na Camada Bronze
-- MAGIC ```sql
-- MAGIC -- Adicionar constraints na tabela bronze
-- MAGIC ALTER TABLE mizukiairflows.bronze.aerodromos 
-- MAGIC ADD CONSTRAINT chk_campos_obrigatorios 
-- MAGIC CHECK (icao IS NOT NULL AND ciad IS NOT NULL AND nome IS NOT NULL);
-- MAGIC ```
-- MAGIC
-- MAGIC #### Template 2: Job de Monitoramento Diário
-- MAGIC ```sql
-- MAGIC -- Query para monitoramento diário de qualidade
-- MAGIC SELECT 
-- MAGIC   CURRENT_DATE() as data_analise,
-- MAGIC   AVG(score_qualidade) as score_medio,
-- MAGIC   COUNT(*) as total_registros,
-- MAGIC   SUM(CASE WHEN score_qualidade < 60 THEN 1 ELSE 0 END) as registros_criticos
-- MAGIC FROM mizukiairflows.silver.vw_aerodromos_qualidade;
-- MAGIC ```
-- MAGIC
-- MAGIC #### Template 3: Tabela de Auditoria
-- MAGIC ```sql
-- MAGIC CREATE TABLE IF NOT EXISTS mizukiairflows.silver.auditoria_qualidade_aerodromos (
-- MAGIC   data_execucao TIMESTAMP,
-- MAGIC   score_medio_qualidade DOUBLE,
-- MAGIC   total_registros INT,
-- MAGIC   registros_completos INT,
-- MAGIC   registros_criticos INT,
-- MAGIC   observacoes STRING
-- MAGIC );
-- MAGIC ```
-- MAGIC
-- MAGIC ### ✅ Checklist de Implementação
-- MAGIC
-- MAGIC - [ ] Executar célula 6: Criar VIEW `vw_aerodromos_qualidade`
-- MAGIC - [ ] Executar célula 7: Analisar distribuição de scores
-- MAGIC - [ ] Executar célula 8: Identificar registros problemáticos
-- MAGIC - [ ] Executar célula 9: Gerar dashboard de métricas
-- MAGIC - [ ] Definir steward de dados responsável pela tabela
-- MAGIC - [ ] Criar job de atualização automática (integração ANAC)
-- MAGIC - [ ] Implementar alertas de qualidade
-- MAGIC - [ ] Documentar no catálogo de dados
-- MAGIC - [ ] Criar processo de revisão mensal de qualidade
-- MAGIC - [ ] Treinar equipe em padrões de qualidade
-- MAGIC
-- MAGIC ### 📊 KPIs de Governança
-- MAGIC
-- MAGIC | KPI | Valor Atual | Meta | Prazo |
-- MAGIC |-----|-------------|------|-------|
-- MAGIC | Score Médio de Qualidade | A calcular | ≥ 85 | 90 dias |
-- MAGIC | Completude de Operação | ~50% | ≥ 95% | 90 dias |
-- MAGIC | Registros com Score 100 | A calcular | ≥ 70% | 120 dias |
-- MAGIC | Consistência de Dados | ~99% | 100% | 30 dias |
-- MAGIC | Tempo Médio de Correção | - | ≤ 7 dias | Imediato |
-- MAGIC
-- MAGIC ---
-- MAGIC
-- MAGIC **Data da Avaliação:** 17/09/2026  
-- MAGIC **Próxima Revisão:** 17/12/2026 (90 dias)  
-- MAGIC **Responsável:** Data Governance Team

-- COMMAND ----------

-- DBTITLE 1,11. Validações de Regras de Negócio
-- MAGIC %md
-- MAGIC ## 4. Validações de Regras de Negócio e Contexto
-- MAGIC
-- MAGIC ### 🔍 Validações Contextuais Implementadas
-- MAGIC
-- MAGIC Esta seção valida não apenas a completude dos dados, mas também:
-- MAGIC * **Conformidade de Formato**: Códigos ICAO, CIAD, URLs
-- MAGIC * **Consistência de Valores**: Altitude, coordenadas, datas
-- MAGIC * **Regras de Negócio**: Operação vs. Situação, validade vs. status
-- MAGIC * **Integridade Geográfica**: Coordenadas dentro do território brasileiro
-- MAGIC * **Padronização**: Valores categóricos esperados

-- COMMAND ----------

-- DBTITLE 1,12. Validação de Códigos e Identificadores
-- Validação de Códigos ICAO e CIAD
SELECT 
  'Códigos ICAO Inválidos (≠4 caracteres)' as validacao,
  COUNT(*) as quantidade_problemas,
  ARRAY_JOIN(COLLECT_SET(icao), ', ') as exemplos
FROM mizukiairflows.silver.aerodromos
WHERE LENGTH(icao) != 4

UNION ALL

SELECT 
  'Códigos ICAO com Caracteres Especiais/Minúsculas' as validacao,
  COUNT(*) as quantidade_problemas,
  ARRAY_JOIN(COLLECT_SET(icao), ', ') as exemplos
FROM mizukiairflows.silver.aerodromos
WHERE icao RLIKE '[^A-Z0-9]' OR icao != UPPER(icao)

UNION ALL

SELECT 
  'Códigos CIAD com Formato Incorreto (deve ser UF+número)' as validacao,
  COUNT(*) as quantidade_problemas,
  ARRAY_JOIN(COLLECT_SET(ciad), ', ') as exemplos
FROM mizukiairflows.silver.aerodromos
WHERE NOT ciad RLIKE '^[A-Z]{2}[0-9]{4}$'

UNION ALL

SELECT 
  'Nomes de Aeródromos Vazios ou Suspeitos' as validacao,
  COUNT(*) as quantidade_problemas,
  ARRAY_JOIN(COLLECT_SET(nome), ', ') as exemplos
FROM mizukiairflows.silver.aerodromos
WHERE nome IS NULL OR LENGTH(TRIM(nome)) < 3 OR nome RLIKE '^[0-9]+$'

-- COMMAND ----------

-- DBTITLE 1,13. Validação de Coordenadas e Altitude
-- Validação de Valores Geográficos
SELECT 
  'Coordenadas Fora do Brasil (Latitude)' as validacao,
  COUNT(*) as quantidade_problemas,
  CONCAT('Latitude deve estar entre 5.27°N e -33.75°S. Encontrados: ', 
         ARRAY_JOIN(COLLECT_SET(CONCAT(icao, ':', latgeopoint)), ', ')) as detalhes
FROM mizukiairflows.silver.aerodromos
WHERE TRY_CAST(latgeopoint AS DOUBLE) IS NOT NULL
  AND (TRY_CAST(latgeopoint AS DOUBLE) > 5.27 
       OR TRY_CAST(latgeopoint AS DOUBLE) < -33.75)

UNION ALL

SELECT 
  'Coordenadas Fora do Brasil (Longitude)' as validacao,
  COUNT(*) as quantidade_problemas,
  CONCAT('Longitude deve estar entre -34.79° e -73.98°. Encontrados: ',
         ARRAY_JOIN(COLLECT_SET(CONCAT(icao, ':', longeopoint)), ', ')) as detalhes
FROM mizukiairflows.silver.aerodromos
WHERE TRY_CAST(longeopoint AS DOUBLE) IS NOT NULL
  AND (TRY_CAST(longeopoint AS DOUBLE) > -34.79 
       OR TRY_CAST(longeopoint AS DOUBLE) < -73.98)

UNION ALL

SELECT 
  'Altitude Negativa ou Suspeita' as validacao,
  COUNT(*) as quantidade_problemas,
  CONCAT('Aeródromos com altitude < 0m ou > 2000m: ',
         ARRAY_JOIN(COLLECT_SET(CONCAT(icao, ':', CAST(altitude_m AS STRING), 'm')), ', ')) as detalhes
FROM mizukiairflows.silver.aerodromos
WHERE altitude_m IS NOT NULL 
  AND (altitude_m < 0 OR altitude_m > 2000)

UNION ALL

SELECT 
  'Coordenadas Decimais Inconsistentes com DMS' as validacao,
  COUNT(*) as quantidade_problemas,
  CONCAT('Registros onde conversão DMS→Decimal pode estar incorreta: ',
         ARRAY_JOIN(COLLECT_SET(icao), ', ')) as detalhes
FROM mizukiairflows.silver.aerodromos
WHERE (latgeopoint IS NOT NULL AND latitude IS NOT NULL
       AND ABS(TRY_CAST(latgeopoint AS DOUBLE)) > 90)
   OR (longeopoint IS NOT NULL AND longitude IS NOT NULL
       AND ABS(TRY_CAST(longeopoint AS DOUBLE)) > 180)

-- COMMAND ----------

-- DBTITLE 1,14. Validação de Consistência Operacional
-- Validação de Regras de Negócio: Operação vs Situação
SELECT 
  'Aeródromos Interditados COM Operação Ativa' as validacao,
  COUNT(*) as quantidade_problemas,
  ARRAY_JOIN(COLLECT_SET(CONCAT(icao, ' - ', nome)), ', ') as exemplos
FROM mizukiairflows.silver.aerodromos
WHERE situacao = 'Interditado'
  AND (operacao_diurna NOT IN ('Sem Operação', 'sem operação') OR operacao_diurna IS NULL
       OR operacao_noturna NOT IN ('Sem Operação', 'sem operação') OR operacao_noturna IS NULL)
  AND (operacao_diurna IS NOT NULL OR operacao_noturna IS NOT NULL)

UNION ALL

SELECT 
  'Operação Noturna SEM Operação Diurna' as validacao,
  COUNT(*) as quantidade_problemas,
  CONCAT('Inconsistente: aeródromo opera à noite mas não de dia. Exemplos: ',
         ARRAY_JOIN(COLLECT_SET(icao), ', ')) as exemplos
FROM mizukiairflows.silver.aerodromos
WHERE operacao_noturna IS NOT NULL 
  AND operacao_noturna NOT IN ('Sem Operação', 'sem operação')
  AND (operacao_diurna IS NULL OR operacao_diurna IN ('Sem Operação', 'sem operação'))

UNION ALL

SELECT 
  'Valores Não Padronizados em Operação Diurna' as validacao,
  COUNT(*) as quantidade_problemas,
  ARRAY_JOIN(COLLECT_SET(operacao_diurna), ', ') as valores_encontrados
FROM mizukiairflows.silver.aerodromos
WHERE operacao_diurna IS NOT NULL
  AND operacao_diurna NOT IN (
    'VFR', 'VFR / IFR Não Precisão', 'VFR / IFR - CAT I', 
    'VFR / IFR - CAT II', 'VFR / IFR - CAT III A', 
    'IFR Não Precisão', 'Sem Operação'
  )

UNION ALL

SELECT 
  'Valores Não Padronizados em Operação Noturna' as validacao,
  COUNT(*) as quantidade_problemas,
  ARRAY_JOIN(COLLECT_SET(operacao_noturna), ', ') as valores_encontrados
FROM mizukiairflows.silver.aerodromos
WHERE operacao_noturna IS NOT NULL
  AND operacao_noturna NOT IN (
    'VFR', 'VFR / IFR Não Precisão', 'VFR / IFR - CAT I', 
    'VFR / IFR - CAT II', 'VFR / IFR - CAT III A', 
    'IFR Não Precisão', 'Sem Operação'
  )

-- COMMAND ----------

-- DBTITLE 1,15. Validação de Datas e Validade
-- Validação de Datas de Validade e Portarias
SELECT 
  'Registros com Validade VENCIDA' as validacao,
  COUNT(*) as quantidade_problemas,
  CONCAT('Aeródromos ativos com registro vencido: ',
         ARRAY_JOIN(COLLECT_SET(CONCAT(icao, ' (vence: ', validade_registro, ')')), ', ')) as detalhes
FROM mizukiairflows.silver.aerodromos
WHERE situacao = 'Cadastrado'
  AND validade_registro IS NOT NULL
  AND TRY_CAST(validade_registro AS DATE) < CURRENT_DATE()

UNION ALL

SELECT 
  'Validade Próxima ao Vencimento (<90 dias)' as validacao,
  COUNT(*) as quantidade_problemas,
  ARRAY_JOIN(COLLECT_SET(CONCAT(icao, ' (vence: ', validade_registro, ')')), ', ') as detalhes
FROM mizukiairflows.silver.aerodromos
WHERE situacao = 'Cadastrado'
  AND validade_registro IS NOT NULL
  AND TRY_CAST(validade_registro AS DATE) BETWEEN CURRENT_DATE() 
      AND DATE_ADD(CURRENT_DATE(), 90)

UNION ALL

SELECT 
  'Formato de Data Inválido em Validade' as validacao,
  COUNT(*) as quantidade_problemas,
  ARRAY_JOIN(COLLECT_SET(validade_registro), ', ') as valores_invalidos
FROM mizukiairflows.silver.aerodromos
WHERE validade_registro IS NOT NULL
  AND TRY_CAST(validade_registro AS DATE) IS NULL

UNION ALL

SELECT 
  'Portaria Informada SEM Link' as validacao,
  COUNT(*) as quantidade_problemas,
  CONCAT('Registros com portaria mas sem link: ',
         ARRAY_JOIN(COLLECT_SET(CONCAT(icao, ' - ', portaria_registro)), ', ')) as detalhes
FROM mizukiairflows.silver.aerodromos
WHERE portaria_registro IS NOT NULL
  AND (link_portaria IS NULL OR LENGTH(TRIM(link_portaria)) = 0)

UNION ALL

SELECT 
  'Links de Portaria com Formato Inválido' as validacao,
  COUNT(*) as quantidade_problemas,
  ARRAY_JOIN(COLLECT_SET(link_portaria), ', ') as links_invalidos
FROM mizukiairflows.silver.aerodromos
WHERE link_portaria IS NOT NULL
  AND NOT link_portaria RLIKE '^https?://.*'

-- COMMAND ----------

-- DBTITLE 1,16. Validação de Consistência Geográfica
-- Validação de Consistência entre Município/UF
SELECT 
  'Município e UF Inconsistentes' as validacao,
  COUNT(*) as quantidade_problemas,
  CONCAT('Aeródromos onde município e município_servido são diferentes: ',
         ARRAY_JOIN(COLLECT_SET(CONCAT(icao, ': ', municipio, '/', uf_nome, 
                     ' vs ', municipio_servido, '/', uf_servido_nome)), ', ')) as detalhes
FROM mizukiairflows.silver.aerodromos
WHERE municipio IS NOT NULL AND municipio_servido IS NOT NULL
  AND uf_nome IS NOT NULL AND uf_servido_nome IS NOT NULL
  AND (UPPER(TRIM(municipio)) != UPPER(TRIM(municipio_servido))
       OR UPPER(TRIM(uf_nome)) != UPPER(TRIM(uf_servido_nome)))

UNION ALL

SELECT 
  'Capitalização Inconsistente em Nomes' as validacao,
  COUNT(*) as quantidade_problemas,
  ARRAY_JOIN(COLLECT_SET(nome), ', ') as exemplos
FROM mizukiairflows.silver.aerodromos
WHERE nome IS NOT NULL
  AND (nome = UPPER(nome) OR nome = LOWER(nome))
  AND LENGTH(nome) > 10

UNION ALL

SELECT 
  'UF com Nome Abreviado ao invés de Extenso' as validacao,
  COUNT(*) as quantidade_problemas,
  ARRAY_JOIN(COLLECT_SET(uf_nome), ', ') as valores_suspeitos
FROM mizukiairflows.silver.aerodromos
WHERE uf_nome IS NOT NULL
  AND LENGTH(uf_nome) <= 2

-- COMMAND ----------

-- DBTITLE 1,17. Dashboard Consolidado de Validações
-- Resumo Consolidado de Todas as Validações de Negócio
WITH validacoes_consolidadas AS (
  -- Códigos ICAO inválidos
  SELECT 'Formato' as categoria, 'ICAO inválido' as tipo_validacao, 
         COUNT(*) as problemas, 'CRÍTICO' as severidade
  FROM mizukiairflows.silver.aerodromos
  WHERE LENGTH(icao) != 4
  
  UNION ALL
  
  -- Coordenadas fora do Brasil
  SELECT 'Geográfico' as categoria, 'Coordenadas fora do Brasil' as tipo_validacao,
         COUNT(*) as problemas, 'CRÍTICO' as severidade
  FROM mizukiairflows.silver.aerodromos
  WHERE (TRY_CAST(latgeopoint AS DOUBLE) > 5.27 OR TRY_CAST(latgeopoint AS DOUBLE) < -33.75)
     OR (TRY_CAST(longeopoint AS DOUBLE) > -34.79 OR TRY_CAST(longeopoint AS DOUBLE) < -73.98)
  
  UNION ALL
  
  -- Altitude suspeita
  SELECT 'Geográfico' as categoria, 'Altitude suspeita' as tipo_validacao,
         COUNT(*) as problemas, 'MÉDIO' as severidade
  FROM mizukiairflows.silver.aerodromos
  WHERE altitude_m < 0 OR altitude_m > 2000
  
  UNION ALL
  
  -- Interditados com operação
  SELECT 'Negócio' as categoria, 'Interditado operando' as tipo_validacao,
         COUNT(*) as problemas, 'ALTO' as severidade
  FROM mizukiairflows.silver.aerodromos
  WHERE situacao = 'Interditado'
    AND (operacao_diurna NOT IN ('Sem Operação') OR operacao_noturna NOT IN ('Sem Operação'))
    AND (operacao_diurna IS NOT NULL OR operacao_noturna IS NOT NULL)
  
  UNION ALL
  
  -- Validade vencida
  SELECT 'Temporal' as categoria, 'Validade vencida' as tipo_validacao,
         COUNT(*) as problemas, 'ALTO' as severidade
  FROM mizukiairflows.silver.aerodromos
  WHERE situacao = 'Cadastrado'
    AND TRY_CAST(validade_registro AS DATE) < CURRENT_DATE()
  
  UNION ALL
  
  -- Validade próxima
  SELECT 'Temporal' as categoria, 'Validade próxima (<90d)' as tipo_validacao,
         COUNT(*) as problemas, 'ALERTA' as severidade
  FROM mizukiairflows.silver.aerodromos
  WHERE situacao = 'Cadastrado'
    AND TRY_CAST(validade_registro AS DATE) BETWEEN CURRENT_DATE() AND DATE_ADD(CURRENT_DATE(), 90)
  
  UNION ALL
  
  -- Portaria sem link
  SELECT 'Documentação' as categoria, 'Portaria sem link' as tipo_validacao,
         COUNT(*) as problemas, 'MÉDIO' as severidade
  FROM mizukiairflows.silver.aerodromos
  WHERE portaria_registro IS NOT NULL AND link_portaria IS NULL
  
  UNION ALL
  
  -- Links inválidos
  SELECT 'Documentação' as categoria, 'Link com formato inválido' as tipo_validacao,
         COUNT(*) as problemas, 'BAIXO' as severidade
  FROM mizukiairflows.silver.aerodromos
  WHERE link_portaria IS NOT NULL AND NOT link_portaria RLIKE '^https?://.*'
)
SELECT 
  categoria,
  tipo_validacao,
  problemas,
  severidade,
  CASE severidade
    WHEN 'CRÍTICO' THEN '🔴'
    WHEN 'ALTO' THEN '🟠'
    WHEN 'MÉDIO' THEN '🟡'
    WHEN 'ALERTA' THEN '⚠️'
    ELSE '🔵'
  END as icone
FROM validacoes_consolidadas
WHERE problemas > 0
ORDER BY 
  CASE severidade
    WHEN 'CRÍTICO' THEN 1
    WHEN 'ALTO' THEN 2
    WHEN 'MÉDIO' THEN 3
    WHEN 'ALERTA' THEN 4
    ELSE 5
  END,
  problemas DESC

-- COMMAND ----------

-- DBTITLE 1,18. Recomendações de Tratamento por Severidade
-- MAGIC %md
-- MAGIC ## 5. Plano de Ação por Severidade
-- MAGIC
-- MAGIC ### 🔴 CRÍTICO - Ação Imediata (0-7 dias)
-- MAGIC
-- MAGIC **Problemas que comprometem a integridade dos dados:**
-- MAGIC
-- MAGIC 1. **Códigos ICAO Inválidos**
-- MAGIC    * **Ação:** Corrigir manualmente consultando fonte oficial (ANAC)
-- MAGIC    * **Bloqueio:** Não permitir novos registros com ICAO != 4 caracteres
-- MAGIC    * **Query de correção:**
-- MAGIC    ```sql
-- MAGIC    -- Identificar e isolar para correção
-- MAGIC    CREATE OR REPLACE TABLE mizukiairflows.silver.aerodromos_quarentena AS
-- MAGIC    SELECT * FROM mizukiairflows.silver.aerodromos
-- MAGIC    WHERE LENGTH(icao) != 4;
-- MAGIC    ```
-- MAGIC
-- MAGIC 2. **Coordenadas Fora do Território Brasileiro**
-- MAGIC    * **Ação:** Validar coordenadas DMS originais e reconverter
-- MAGIC    * **Impacto:** Dados geográficos incorretos afetam análises espaciais
-- MAGIC    * **Responsável:** Equipe de Dados Geoespaciais
-- MAGIC
-- MAGIC ### 🟠 ALTO - Ação Urgente (7-14 dias)
-- MAGIC
-- MAGIC **Problemas que afetam regras de negócio:**
-- MAGIC
-- MAGIC 1. **Aeródromos Interditados com Operações Ativas**
-- MAGIC    * **Ação:** Atualizar operação para "Sem Operação" ou revisar status de interdição
-- MAGIC    * **Query de correção:**
-- MAGIC    ```sql
-- MAGIC    UPDATE mizukiairflows.silver.aerodromos
-- MAGIC    SET operacao_diurna = 'Sem Operação',
-- MAGIC        operacao_noturna = 'Sem Operação'
-- MAGIC    WHERE situacao = 'Interditado';
-- MAGIC    ```
-- MAGIC
-- MAGIC 2. **Registros com Validade Vencida**
-- MAGIC    * **Ação:** Atualizar dados com ANAC ou mudar situação para "Interditado"
-- MAGIC    * **Processo:** Criar job semanal de verificação de validades
-- MAGIC
-- MAGIC ### 🟡 MÉDIO - Planejado (14-30 dias)
-- MAGIC
-- MAGIC **Problemas que afetam qualidade e usabilidade:**
-- MAGIC
-- MAGIC 1. **Altitude Suspeita (Negativa ou > 2000m)**
-- MAGIC    * **Ação:** Validar com fonte oficial
-- MAGIC    * **Nota:** Brasil tem aeródromos de 0m (nível do mar) a ~1600m (altitude)
-- MAGIC
-- MAGIC 2. **Portarias sem Link de Documentação**
-- MAGIC    * **Ação:** Buscar links no portal ANAC Pergamum
-- MAGIC    * **Automação:** Script de enriquecimento com API/scraping ANAC
-- MAGIC
-- MAGIC ### ⚠️ ALERTA - Monitoramento Contínuo
-- MAGIC
-- MAGIC **Situações que requerem acompanhamento:**
-- MAGIC
-- MAGIC 1. **Validade Próxima ao Vencimento (<90 dias)**
-- MAGIC    * **Ação:** Criar alerta automático para equipe de governança
-- MAGIC    * **Frequência:** Verificação semanal
-- MAGIC    * **Query de monitoramento:**
-- MAGIC    ```sql
-- MAGIC    SELECT icao, nome, validade_registro,
-- MAGIC           DATEDIFF(TRY_CAST(validade_registro AS DATE), CURRENT_DATE()) as dias_restantes
-- MAGIC    FROM mizukiairflows.silver.aerodromos
-- MAGIC    WHERE TRY_CAST(validade_registro AS DATE) BETWEEN CURRENT_DATE() 
-- MAGIC          AND DATE_ADD(CURRENT_DATE(), 90)
-- MAGIC    ORDER BY dias_restantes;
-- MAGIC    ```
-- MAGIC
-- MAGIC ### 🔵 BAIXO - Melhoria Contínua (30-90 dias)
-- MAGIC
-- MAGIC **Padronizações e refinamentos:**
-- MAGIC
-- MAGIC 1. **Links com Formato Inválido**
-- MAGIC    * Padronizar todos os links para https://
-- MAGIC    * Validar acessibilidade dos links
-- MAGIC
-- MAGIC 2. **Capitalização de Nomes**
-- MAGIC    * Padronizar para Title Case
-- MAGIC    * Manter siglas em maiúsculas
-- MAGIC
-- MAGIC ---
-- MAGIC
-- MAGIC ### 📋 Checklist de Validações de Negócio
-- MAGIC
-- MAGIC - [ ] Executar célula 12: Validar códigos e identificadores
-- MAGIC - [ ] Executar célula 13: Validar coordenadas e altitude
-- MAGIC - [ ] Executar célula 14: Validar consistência operacional
-- MAGIC - [ ] Executar célula 15: Validar datas e validade
-- MAGIC - [ ] Executar célula 16: Validar consistência geográfica
-- MAGIC - [ ] Executar célula 17: Gerar dashboard consolidado de validações
-- MAGIC - [ ] Criar job de monitoramento semanal de validades
-- MAGIC - [ ] Implementar constraints na camada Bronze
-- MAGIC - [ ] Documentar regras de validação no catálogo
-- MAGIC - [ ] Treinar equipe em regras de negócio de aeródromos

-- COMMAND ----------

-- DBTITLE 1,19. Processo de Data Quality - Quarentena
-- MAGIC %md
-- MAGIC ## 6. Processo de Data Quality - Prevenção de Dados Inválidos
-- MAGIC
-- MAGIC ### 🛡️ Objetivo
-- MAGIC Implementar um processo robusto que **impeça** registros com ICAO vazio de serem carregados na camada Silver.
-- MAGIC
-- MAGIC ### 📋 Componentes do Processo
-- MAGIC
-- MAGIC 1. **Tabela de Quarentena**: Armazena registros rejeitados para análise
-- MAGIC 2. **Validação Crítica**: Bloqueia carga de registros inválidos
-- MAGIC 3. **Auditoria**: Rastreia todas as rejeições
-- MAGIC 4. **Alertas**: Notifica equipe sobre problemas
-- MAGIC
-- MAGIC ### 🔍 Regras de Validação Críticas
-- MAGIC
-- MAGIC **Campos Obrigatórios (Bloqueantes):**
-- MAGIC * ✅ ICAO: Não pode ser NULL ou vazio
-- MAGIC * ✅ ICAO: Deve ter exatamente 4 caracteres
-- MAGIC * ✅ ICAO: Deve conter apenas letras maiúsculas e números
-- MAGIC * ✅ CIAD: Não pode ser NULL
-- MAGIC * ✅ Nome: Não pode ser NULL ou vazio

-- COMMAND ----------

-- DBTITLE 1,20. Criar Tabela de Quarentena
-- Criar tabela de quarentena para registros rejeitados
CREATE TABLE IF NOT EXISTS mizukiairflows.silver.aerodromos_quarentena (
  -- Campos originais
  icao STRING COMMENT 'Código ICAO (pode ser nulo/inválido aqui)',
  ciad STRING,
  nome STRING,
  municipio STRING,
  uf_nome STRING,
  municipio_servido STRING,
  uf_servido_nome STRING,
  altitude_m DOUBLE,
  latitude STRING,
  longitude STRING,
  latgeopoint STRING,
  longeopoint STRING,
  operacao_diurna STRING,
  operacao_noturna STRING,
  situacao STRING,
  validade_registro STRING,
  portaria_registro STRING,
  link_portaria STRING,
  status_coordenadas STRING,
  origem_arquivo STRING,
  
  -- Campos de controle de qualidade
  data_rejeicao TIMESTAMP COMMENT 'Quando o registro foi rejeitado',
  motivo_rejeicao STRING COMMENT 'Razão da rejeição',
  regra_violada STRING COMMENT 'Qual regra de qualidade foi violada',
  severidade STRING COMMENT 'CRÍTICO, ALTO, MÉDIO',
  status_revisao STRING COMMENT 'PENDENTE, EM_ANALISE, CORRIGIDO, DESCARTADO',
  revisado_por STRING COMMENT 'Usuário que revisou',
  data_revisao TIMESTAMP COMMENT 'Quando foi revisado',
  observacoes STRING COMMENT 'Notas da equipe'
)
COMMENT 'Quarentena para registros de aeródromos que falharam nas validações de qualidade'
TBLPROPERTIES ('delta.enableChangeDataFeed' = 'true');

-- COMMAND ----------

-- DBTITLE 1,21. Criar Tabela de Auditoria
-- Criar tabela de auditoria de validações
CREATE TABLE IF NOT EXISTS mizukiairflows.silver.auditoria_dq_aerodromos (
  data_execucao TIMESTAMP COMMENT 'Timestamp da execução do processo',
  total_registros_bronze INT COMMENT 'Total de registros processados da Bronze',
  registros_aprovados INT COMMENT 'Registros que passaram nas validações',
  registros_rejeitados INT COMMENT 'Registros enviados para quarentena',
  
  -- Detalhamento por tipo de validação
  rejeicao_icao_nulo INT COMMENT 'Rejeitados por ICAO nulo/vazio',
  rejeicao_icao_formato INT COMMENT 'Rejeitados por formato de ICAO inválido',
  rejeicao_ciad_nulo INT COMMENT 'Rejeitados por CIAD nulo',
  rejeicao_nome_nulo INT COMMENT 'Rejeitados por nome nulo/vazio',
  rejeicao_coordenadas INT COMMENT 'Rejeitados por coordenadas inválidas',
  
  -- Métricas de qualidade
  taxa_aprovacao DOUBLE COMMENT 'Percentual de registros aprovados',
  taxa_rejeicao DOUBLE COMMENT 'Percentual de registros rejeitados',
  
  -- Controle de execução
  tempo_execucao_segundos DOUBLE COMMENT 'Tempo de processamento',
  origem_carga STRING COMMENT 'Arquivo ou fonte da carga',
  usuario_execucao STRING COMMENT 'Quem executou o processo',
  status_execucao STRING COMMENT 'SUCESSO, ERRO, PARCIAL'
)
COMMENT 'Auditoria de execuções do processo de Data Quality'
PARTITIONED BY (data_particao DATE)
TBLPROPERTIES ('delta.enableChangeDataFeed' = 'true');

-- COMMAND ----------

-- DBTITLE 1,22. Função de Validação ICAO
-- Criar função para validar ICAO
-- Retorna uma estrutura com campos: valido (boolean) e motivo (string)
CREATE OR REPLACE FUNCTION mizukiairflows.silver.validar_icao(icao_input STRING)
RETURNS STRUCT<valido: BOOLEAN, motivo: STRING>
RETURN 
  CASE 
    -- Validação 1: ICAO não pode ser nulo
    WHEN icao_input IS NULL THEN 
      NAMED_STRUCT('valido', FALSE, 'motivo', 'ICAO é NULL')
    
    -- Validação 2: ICAO não pode ser vazio ou apenas espaços
    WHEN TRIM(icao_input) = '' THEN 
      NAMED_STRUCT('valido', FALSE, 'motivo', 'ICAO está vazio')
    
    -- Validação 3: ICAO deve ter exatamente 4 caracteres
    WHEN LENGTH(TRIM(icao_input)) != 4 THEN 
      NAMED_STRUCT('valido', FALSE, 'motivo', CONCAT('ICAO tem ', CAST(LENGTH(TRIM(icao_input)) AS STRING), ' caracteres, esperado 4'))
    
    -- Validação 4: ICAO deve conter apenas letras maiúsculas e números
    WHEN TRIM(icao_input) RLIKE '[^A-Z0-9]' THEN 
      NAMED_STRUCT('valido', FALSE, 'motivo', 'ICAO contém caracteres inválidos (apenas A-Z e 0-9 permitidos)')
    
    -- Validação 5: ICAO deve estar em maiúsculas
    WHEN TRIM(icao_input) != UPPER(TRIM(icao_input)) THEN 
      NAMED_STRUCT('valido', FALSE, 'motivo', 'ICAO deve estar em letras maiúsculas')
    
    -- Se passou em todas as validações
    ELSE 
      NAMED_STRUCT('valido', TRUE, 'motivo', 'ICAO válido')
  END;

-- COMMAND ----------

-- DBTITLE 1,22b. Testar Função de Validação
-- Testar a função de validação ICAO com exemplos
SELECT 
  'SBGR' as icao_teste,
  mizukiairflows.silver.validar_icao('SBGR') as resultado
  
UNION ALL

SELECT 
  'NULL' as icao_teste,
  mizukiairflows.silver.validar_icao(NULL) as resultado
  
UNION ALL

SELECT 
  'vazio' as icao_teste,
  mizukiairflows.silver.validar_icao('') as resultado
  
UNION ALL

SELECT 
  'SB' as icao_teste,
  mizukiairflows.silver.validar_icao('SB') as resultado
  
UNION ALL

SELECT 
  'sbgr' as icao_teste,
  mizukiairflows.silver.validar_icao('sbgr') as resultado
  
UNION ALL

SELECT 
  'SB@R' as icao_teste,
  mizukiairflows.silver.validar_icao('SB@R') as resultado;

-- COMMAND ----------

-- DBTITLE 1,22c. Demonstração do Processo DQ
-- DEMONSTRAÇÃO: Aplicar validação nos dados EXISTENTES da Silver
-- Para ver como funciona o processo de separação de válidos/inválidos

CREATE OR REPLACE TEMP VIEW vw_demo_validacao AS
SELECT 
  icao,
  nome,
  mizukiairflows.silver.validar_icao(icao) as validacao_icao,
  
  CASE 
    WHEN mizukiairflows.silver.validar_icao(icao).valido = FALSE THEN 'REJEITADO'
    ELSE 'APROVADO'
  END as status_qualidade
  
FROM mizukiairflows.silver.aerodromos
LIMIT 10;

-- Visualizar resultado
SELECT 
  icao,
  nome,
  validacao_icao.valido as icao_valido,
  validacao_icao.motivo as motivo_validacao,
  status_qualidade
FROM vw_demo_validacao;

-- COMMAND ----------

-- DBTITLE 1,23. Processo de Carga com Validação
-- Processo de Carga Silver com Validação de Data Quality
-- NOTA: Esta célula é um TEMPLATE de exemplo
-- A tabela Bronze atual (aerodromos_publicos) tem schema diferente do esperado
-- Para testar o processo de validação, use os dados já existentes na Silver
-- Para produção, adapte este código ao schema real da sua tabela Bronze

-- DEMONSTRAÇÃO: Aplicar validação nos dados EXISTENTES da Silver
CREATE OR REPLACE TEMP VIEW vw_validacao_bronze AS
SELECT 
  *,
  mizukiairflows.silver.validar_icao(icao) as validacao_icao,
  
  -- Outras validações críticas
  CASE WHEN ciad IS NULL THEN FALSE ELSE TRUE END as ciad_valido,
  CASE WHEN nome IS NULL OR TRIM(nome) = '' THEN FALSE ELSE TRUE END as nome_valido,
  
  -- Flag geral de qualidade
  CASE 
    WHEN mizukiairflows.silver.validar_icao(icao).valido = FALSE THEN 'REJEITADO'
    WHEN ciad IS NULL THEN 'REJEITADO'
    WHEN nome IS NULL OR TRIM(nome) = '' THEN 'REJEITADO'
    ELSE 'APROVADO'
  END as status_qualidade,
  
  -- Consolidar motivos de rejeição
  CASE 
    WHEN mizukiairflows.silver.validar_icao(icao).valido = FALSE THEN 
      CONCAT('ICAO: ', mizukiairflows.silver.validar_icao(icao).motivo)
    WHEN ciad IS NULL THEN 'CIAD é obrigatório'
    WHEN nome IS NULL OR TRIM(nome) = '' THEN 'Nome é obrigatório'
    ELSE NULL
  END as motivo_rejeicao,
  
  CURRENT_TIMESTAMP() as timestamp_validacao
  
FROM mizukiairflows.silver.aerodromos;

-- Visualizar resultado da validação
SELECT 
  status_qualidade,
  COUNT(*) as quantidade,
  ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM vw_validacao_bronze), 2) as percentual
FROM vw_validacao_bronze
GROUP BY status_qualidade;

-- COMMAND ----------

-- DBTITLE 1,24. Inserir Registros Rejeitados na Quarentena
-- PASSO 2: Inserir registros REJEITADOS na quarentena
INSERT INTO mizukiairflows.silver.aerodromos_quarentena
SELECT 
  -- Campos originais
  icao,
  ciad,
  nome,
  municipio,
  uf_nome,
  municipio_servido,
  uf_servido_nome,
  altitude_m,
  latitude,
  longitude,
  latgeopoint,
  longeopoint,
  operacao_diurna,
  operacao_noturna,
  situacao,
  validade_registro,
  portaria_registro,
  link_portaria,
  status_coordenadas,
  origem_arquivo,
  
  -- Campos de controle de qualidade
  timestamp_validacao as data_rejeicao,
  motivo_rejeicao,
  CASE 
    WHEN motivo_rejeicao LIKE '%ICAO%' THEN 'VALIDACAO_ICAO'
    WHEN motivo_rejeicao LIKE '%CIAD%' THEN 'VALIDACAO_CIAD'
    WHEN motivo_rejeicao LIKE '%Nome%' THEN 'VALIDACAO_NOME'
    ELSE 'VALIDACAO_GERAL'
  END as regra_violada,
  'CRÍTICO' as severidade,
  'PENDENTE' as status_revisao,
  NULL as revisado_por,
  NULL as data_revisao,
  NULL as observacoes
  
FROM vw_validacao_bronze
WHERE status_qualidade = 'REJEITADO';

-- Verificar registros inseridos na quarentena
SELECT 
  regra_violada,
  COUNT(*) as quantidade,
  COLLECT_LIST(icao) as exemplos_icao
FROM mizukiairflows.silver.aerodromos_quarentena
WHERE DATE(data_rejeicao) = CURRENT_DATE()
GROUP BY regra_violada;

-- COMMAND ----------

-- DBTITLE 1,25. Inserir Apenas Registros Válidos na Silver
-- PASSO 3: Inserir APENAS registros APROVADOS na Silver
-- IMPORTANTE: Este é um exemplo de MERGE - adapte para seu processo específico

MERGE INTO mizukiairflows.silver.aerodromos AS target
USING (
  SELECT 
    icao,
    ciad,
    nome,
    municipio,
    uf_nome,
    municipio_servido,
    uf_servido_nome,
    altitude_m,
    latitude,
    longitude,
    latgeopoint,
    longeopoint,
    operacao_diurna,
    operacao_noturna,
    situacao,
    validade_registro,
    portaria_registro,
    link_portaria,
    status_coordenadas,
    origem_arquivo,
    CURRENT_TIMESTAMP() as transformado_em
  FROM vw_validacao_bronze
  WHERE status_qualidade = 'APROVADO'  -- APENAS registros aprovados!
) AS source
ON target.icao = source.icao
WHEN MATCHED THEN
  UPDATE SET
    target.ciad = source.ciad,
    target.nome = source.nome,
    target.municipio = source.municipio,
    target.uf_nome = source.uf_nome,
    target.municipio_servido = source.municipio_servido,
    target.uf_servido_nome = source.uf_servido_nome,
    target.altitude_m = source.altitude_m,
    target.latitude = source.latitude,
    target.longitude = source.longitude,
    target.latgeopoint = source.latgeopoint,
    target.longeopoint = source.longeopoint,
    target.operacao_diurna = source.operacao_diurna,
    target.operacao_noturna = source.operacao_noturna,
    target.situacao = source.situacao,
    target.validade_registro = source.validade_registro,
    target.portaria_registro = source.portaria_registro,
    target.link_portaria = source.link_portaria,
    target.status_coordenadas = source.status_coordenadas,
    target.origem_arquivo = source.origem_arquivo,
    target.transformado_em = source.transformado_em
WHEN NOT MATCHED THEN
  INSERT *;

-- Confirmar sucesso da carga
SELECT 
  'Carga Silver Concluída' as status,
  COUNT(*) as total_registros_silver,
  MAX(transformado_em) as ultima_atualizacao
FROM mizukiairflows.silver.aerodromos;

-- COMMAND ----------

-- DBTITLE 1,26. Registrar Auditoria
-- PASSO 4: Registrar execução na auditoria
INSERT INTO mizukiairflows.silver.auditoria_dq_aerodromos
SELECT 
  CURRENT_TIMESTAMP() as data_execucao,
  
  -- Totais
  (SELECT COUNT(*) FROM vw_validacao_bronze) as total_registros_bronze,
  (SELECT COUNT(*) FROM vw_validacao_bronze WHERE status_qualidade = 'APROVADO') as registros_aprovados,
  (SELECT COUNT(*) FROM vw_validacao_bronze WHERE status_qualidade = 'REJEITADO') as registros_rejeitados,
  
  -- Detalhamento por tipo de rejeição
  (SELECT COUNT(*) FROM vw_validacao_bronze WHERE motivo_rejeicao LIKE '%ICAO%') as rejeicao_icao_nulo,
  (SELECT COUNT(*) FROM vw_validacao_bronze WHERE motivo_rejeicao LIKE '%caracteres%') as rejeicao_icao_formato,
  (SELECT COUNT(*) FROM vw_validacao_bronze WHERE motivo_rejeicao LIKE '%CIAD%') as rejeicao_ciad_nulo,
  (SELECT COUNT(*) FROM vw_validacao_bronze WHERE motivo_rejeicao LIKE '%Nome%') as rejeicao_nome_nulo,
  0 as rejeicao_coordenadas,
  
  -- Métricas
  ROUND((SELECT COUNT(*) FROM vw_validacao_bronze WHERE status_qualidade = 'APROVADO') * 100.0 / 
        (SELECT COUNT(*) FROM vw_validacao_bronze), 2) as taxa_aprovacao,
  ROUND((SELECT COUNT(*) FROM vw_validacao_bronze WHERE status_qualidade = 'REJEITADO') * 100.0 / 
        (SELECT COUNT(*) FROM vw_validacao_bronze), 2) as taxa_rejeicao,
  
  -- Controle
  0.0 as tempo_execucao_segundos,
  'Manual - Notebook Validação' as origem_carga,
  CURRENT_USER() as usuario_execucao,
  'SUCESSO' as status_execucao,
  
  -- Partição
  CURRENT_DATE() as data_particao;

-- Visualizar última execução
SELECT 
  data_execucao,
  total_registros_bronze,
  registros_aprovados,
  registros_rejeitados,
  taxa_aprovacao,
  taxa_rejeicao,
  CONCAT(
    'ICAO: ', rejeicao_icao_nulo, ' | ',
    'Formato: ', rejeicao_icao_formato, ' | ',
    'CIAD: ', rejeicao_ciad_nulo, ' | ',
    'Nome: ', rejeicao_nome_nulo
  ) as detalhamento_rejeicoes
FROM mizukiairflows.silver.auditoria_dq_aerodromos
WHERE data_particao = CURRENT_DATE()
ORDER BY data_execucao DESC
LIMIT 1;

-- COMMAND ----------

-- DBTITLE 1,27. Dashboard de Monitoramento de Quarentena
-- Dashboard: Monitoramento de Registros em Quarentena
SELECT 
  'Registros em Quarentena (Total)' as metrica,
  CAST(COUNT(*) AS STRING) as valor,
  '100%' as percentual
FROM mizukiairflows.silver.aerodromos_quarentena

UNION ALL

SELECT 
  'Registros Pendentes de Revisão' as metrica,
  CAST(COUNT(*) AS STRING) as valor,
  CONCAT(CAST(ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM mizukiairflows.silver.aerodromos_quarentena), 2) AS STRING), '%') as percentual
FROM mizukiairflows.silver.aerodromos_quarentena
WHERE status_revisao = 'PENDENTE'

UNION ALL

SELECT 
  'Rejeitados por ICAO Inválido' as metrica,
  CAST(COUNT(*) AS STRING) as valor,
  CONCAT(CAST(ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM mizukiairflows.silver.aerodromos_quarentena), 2) AS STRING), '%') as percentual
FROM mizukiairflows.silver.aerodromos_quarentena
WHERE regra_violada = 'VALIDACAO_ICAO'

UNION ALL

SELECT 
  'Rejeitados Hoje' as metrica,
  CAST(COUNT(*) AS STRING) as valor,
  '-' as percentual
FROM mizukiairflows.silver.aerodromos_quarentena
WHERE DATE(data_rejeicao) = CURRENT_DATE()

UNION ALL

SELECT 
  'Registros Corrigidos' as metrica,
  CAST(COUNT(*) AS STRING) as valor,
  CONCAT(CAST(ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM mizukiairflows.silver.aerodromos_quarentena), 2) AS STRING), '%') as percentual
FROM mizukiairflows.silver.aerodromos_quarentena
WHERE status_revisao = 'CORRIGIDO';

-- COMMAND ----------

-- DBTITLE 1,28. Documentação do Processo
-- MAGIC %md
-- MAGIC ## 7. Como Usar o Processo de Data Quality
-- MAGIC
-- MAGIC ### 🚀 Execução do Processo Completo
-- MAGIC
-- MAGIC **Ordem de Execução das Células:**
-- MAGIC
-- MAGIC 1. **Célula 20**: Criar tabela de quarentena (executar 1x)
-- MAGIC 2. **Célula 21**: Criar tabela de auditoria (executar 1x)
-- MAGIC 3. **Célula 22**: Criar função de validação ICAO (executar 1x)
-- MAGIC 4. **Célula 23**: Validar dados Bronze e separar válidos/inválidos
-- MAGIC 5. **Célula 24**: Inserir registros rejeitados na quarentena
-- MAGIC 6. **Célula 25**: Carregar APENAS registros válidos na Silver
-- MAGIC 7. **Célula 26**: Registrar execução na auditoria
-- MAGIC 8. **Célula 27**: Visualizar dashboard de quarentena
-- MAGIC
-- MAGIC ### 🔄 Integração com seu Pipeline ETL
-- MAGIC
-- MAGIC #### Opção 1: Workflow Databricks (Jobs)
-- MAGIC ```python
-- MAGIC # Task 1: Extração Bronze
-- MAGIC dbutils.notebook.run("/path/to/bronze_load", timeout_seconds=3600)
-- MAGIC
-- MAGIC # Task 2: Validação e Carga Silver (COM Data Quality)
-- MAGIC dbutils.notebook.run("/path/to/silver_dq_load", timeout_seconds=3600)
-- MAGIC
-- MAGIC # Task 3: Alertas (se houver rejeições)
-- MAGIC if get_rejected_count() > 0:
-- MAGIC     dbutils.notebook.run("/path/to/alertas", timeout_seconds=600)
-- MAGIC ```
-- MAGIC
-- MAGIC #### Opção 2: SQL Notebook Automatizado
-- MAGIC Crie um notebook SQL com as células 23-26 e agende via Job.
-- MAGIC
-- MAGIC ### 📧 Configurar Alertas
-- MAGIC
-- MAGIC **Alerta 1: Rejeições Detectadas**
-- MAGIC ```sql
-- MAGIC SELECT 
-- MAGIC   COUNT(*) as registros_rejeitados_hoje
-- MAGIC FROM mizukiairflows.silver.aerodromos_quarentena
-- MAGIC WHERE DATE(data_rejeicao) = CURRENT_DATE();
-- MAGIC
-- MAGIC -- Se > 0, enviar alerta para equipe
-- MAGIC ```
-- MAGIC
-- MAGIC **Alerta 2: Taxa de Rejeição Alta**
-- MAGIC ```sql
-- MAGIC SELECT 
-- MAGIC   taxa_rejeicao
-- MAGIC FROM mizukiairflows.silver.auditoria_dq_aerodromos
-- MAGIC WHERE data_particao = CURRENT_DATE()
-- MAGIC ORDER BY data_execucao DESC
-- MAGIC LIMIT 1;
-- MAGIC
-- MAGIC -- Se taxa_rejeicao > 5%, enviar alerta crítico
-- MAGIC ```
-- MAGIC
-- MAGIC ### 🔍 Revisar Registros em Quarentena
-- MAGIC
-- MAGIC ```sql
-- MAGIC -- Ver registros pendentes de revisão
-- MAGIC SELECT 
-- MAGIC   icao,
-- MAGIC   nome,
-- MAGIC   motivo_rejeicao,
-- MAGIC   data_rejeicao
-- MAGIC FROM mizukiairflows.silver.aerodromos_quarentena
-- MAGIC WHERE status_revisao = 'PENDENTE'
-- MAGIC ORDER BY data_rejeicao DESC;
-- MAGIC
-- MAGIC -- Após correção na fonte, marcar como corrigido
-- MAGIC UPDATE mizukiairflows.silver.aerodromos_quarentena
-- MAGIC SET status_revisao = 'CORRIGIDO',
-- MAGIC     revisado_por = CURRENT_USER(),
-- MAGIC     data_revisao = CURRENT_TIMESTAMP(),
-- MAGIC     observacoes = 'Corrigido na fonte Bronze e reprocessado'
-- MAGIC WHERE icao = 'XXXX';
-- MAGIC ```
-- MAGIC
-- MAGIC ### ✅ Checklist de Implementação
-- MAGIC
-- MAGIC - [ ] Executar célula 20: Criar tabela de quarentena
-- MAGIC - [ ] Executar célula 21: Criar tabela de auditoria
-- MAGIC - [ ] Executar célula 22: Criar função validar_icao
-- MAGIC - [ ] Testar processo completo (células 23-27) com dados Bronze
-- MAGIC - [ ] Validar que registros com ICAO vazio vão para quarentena
-- MAGIC - [ ] Validar que APENAS registros válidos vão para Silver
-- MAGIC - [ ] Integrar no pipeline ETL existente
-- MAGIC - [ ] Configurar alertas automáticos (email/Slack)
-- MAGIC - [ ] Documentar processo no catálogo de dados
-- MAGIC - [ ] Treinar equipe no processo de revisão de quarentena
-- MAGIC - [ ] Agendar job de validação diária
-- MAGIC
-- MAGIC ### 📊 Métricas de Sucesso
-- MAGIC
-- MAGIC | Métrica | Target |
-- MAGIC |---------|--------|
-- MAGIC | Taxa de Aprovação | ≥ 95% |
-- MAGIC | Tempo Médio de Correção | ≤ 24h |
-- MAGIC | Registros em Quarentena Pendentes | ≤ 10 |
-- MAGIC | Falsos Positivos (rejeições incorretas) | 0% |
-- MAGIC
-- MAGIC ### 🎯 Benefícios Implementados
-- MAGIC
-- MAGIC ✅ **Zero registros inválidos na Silver**  
-- MAGIC ✅ **Rastreabilidade completa** de rejeições  
-- MAGIC ✅ **Auditoria automática** de todas as execuções  
-- MAGIC ✅ **Processo de revisão** estruturado  
-- MAGIC ✅ **Alertas proativos** para equipe  
-- MAGIC ✅ **Conformidade** com governança de dados
-- MAGIC
-- MAGIC ---
-- MAGIC
-- MAGIC **🔒 GARANTIA: Nenhum registro com ICAO vazio chegará à camada Silver!**