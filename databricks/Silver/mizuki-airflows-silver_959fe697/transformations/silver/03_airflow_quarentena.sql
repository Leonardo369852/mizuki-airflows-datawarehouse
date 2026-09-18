-- ============================================================================
-- 03_airflow_quarentena.sql
-- Materialized View: registros em quarentena que falharam nas validacoes
--
-- Espelho de diagnostico dos registros bronze rejeitados. Cada linha traz o
-- motivo_exclusao que explica qual validacao falhou, permitindo investigacao
-- e correcao de problemas de qualidade na origem.
-- Garante que airflow_auditado + airflow_quarentena = 100% dos registros bronze.
-- ============================================================================

CREATE OR REFRESH MATERIALIZED VIEW mizukiairflows.silver.airflow_quarentena
COMMENT 'Camada Silver - VRA em quarentena: registros que falharam nas validacoes de qualidade (ICAO invalido, horarios ausentes, situacao desconhecida). Inclui motivo_exclusao para investigacao. A soma com airflow_auditado representa 100% dos registros bronze.'
CLUSTER BY (motivo_exclusao)
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
  motivo_exclusao,
  current_timestamp() AS transformado_em
FROM airflow_marcado
WHERE is_valid = false;
