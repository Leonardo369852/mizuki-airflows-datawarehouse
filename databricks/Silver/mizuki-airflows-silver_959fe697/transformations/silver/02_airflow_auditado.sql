-- ============================================================================
-- 02_airflow_auditado.sql
-- Materialized View: registros da VRA validados e auditados na camada silver
--
-- Contem apenas os registros que passaram em todas as validacoes de qualidade
-- definidas na temporary view airflow_marcado. As constraints com EXPECT atuam
-- como rede de segurança documentando as regras de qualidade obrigatórias.
-- ============================================================================

CREATE OR REFRESH MATERIALIZED VIEW mizukiairflows.silver.airflow_auditado (
  CONSTRAINT expect_icao_empresa_not_null EXPECT (icao_empresa IS NOT NULL),
  CONSTRAINT expect_icao_empresa_valido   EXPECT (valid_icao_empresa = true),
  CONSTRAINT expect_icao_origem_valido    EXPECT (valid_icao_origem = true),
  CONSTRAINT expect_icao_destino_valido   EXPECT (valid_icao_destino = true),
  CONSTRAINT expect_horarios_presentes   EXPECT (valid_horarios = true),
  CONSTRAINT expect_situacao_conhecida    EXPECT (valid_situacao = true)
)
COMMENT 'Camada Silver - VRA auditada: voos validados contra tabelas de referencia (aerodromos e empresas). Contem apenas registros com ICAOs validos, horarios previstos presentes e situacao conhecida (REALIZADO ou CANCELADO).'
CLUSTER BY (situacao_voo, icao_empresa)
AS
SELECT
  icao_empresa,
  numero_voo,
  codigo_di,
  codigo_tipo_linha,
  icao_origem,
  icao_destino,
  partida_prevista,
  partida_real,
  chegada_prevista,
  chegada_real,
  situacao_voo,
  codigo_justificativa,
  origem_arquivo,
  ingestion_timestamp,
  valid_icao_empresa,
  valid_icao_origem,
  valid_icao_destino,
  valid_horarios,
  valid_situacao,
  current_timestamp() AS transformado_em
FROM airflow_marcado
WHERE is_valid = true;
