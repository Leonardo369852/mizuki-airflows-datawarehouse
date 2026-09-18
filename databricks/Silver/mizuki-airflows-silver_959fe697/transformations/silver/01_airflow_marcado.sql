-- ============================================================================
-- 01_airflow_marcado.sql
-- Temporary View: identifica ICAOs validos de diferentes fontes de referencia
--
-- Le os dados bronze da VRA (mizukiairflows.bronze.vra), valida os codigos ICAO
-- contra as tabelas de referencia silver.aerodromos e silver.empresas, e marca
-- cada registro com flags booleanas de qualidade. O resultado alimenta as MVs
-- downstream airflow_auditado (registros validos) e airflow_quarentena
-- (registros rejeitados com motivo de exclusao).
-- ============================================================================

CREATE TEMPORARY VIEW airflow_marcado
COMMENT 'Marcacao de qualidade VRA: enriquece dados bronze com flags de validacao de ICAO (empresa, origem, destino), horarios e situacao do voo.'
AS
SELECT
  v.`ICAO_Empresa_Aérea` AS icao_empresa,
  v.`Número_Voo`          AS numero_voo,
  v.`Código_Autorização_DI` AS codigo_di,
  v.`Código_Tipo_Linha`    AS codigo_tipo_linha,
  v.`ICAO_Aeródromo_Origem`  AS icao_origem,
  v.`ICAO_Aeródromo_Destino` AS icao_destino,
  v.`Partida_Prevista`     AS partida_prevista,
  v.`Partida_Real`         AS partida_real,
  v.`Chegada_Prevista`    AS chegada_prevista,
  v.`Chegada_Real`        AS chegada_real,
  v.`Situação_Voo`        AS situacao_voo,
  v.`Código_Justificativa` AS codigo_justificativa,
  v._source_file          AS origem_arquivo,
  v._ingestion_timestamp  AS ingestion_timestamp,
  -- Validacao: ICAO da empresa existe em silver.empresas
  (e.icao IS NOT NULL) AS valid_icao_empresa,
  -- Validacao: ICAO do aerodromo de origem existe em silver.aerodromos
  (ao.icao IS NOT NULL) AS valid_icao_origem,
  -- Validacao: ICAO do aerodromo de destino existe em silver.aerodromos
  (ad.icao IS NOT NULL) AS valid_icao_destino,
  -- Validacao: horarios previstos de partida e chegada presentes
  (v.`Partida_Prevista` IS NOT NULL AND v.`Chegada_Prevista` IS NOT NULL) AS valid_horarios,
  -- Validacao: situacao do voo e conhecida
  (v.`Situação_Voo` IN ('REALIZADO', 'CANCELADO')) AS valid_situacao,
  -- Flag combinado: registro passa em todas as validacoes
  (
    e.icao IS NOT NULL
    AND ao.icao IS NOT NULL
    AND ad.icao IS NOT NULL
    AND v.`Partida_Prevista` IS NOT NULL
    AND v.`Chegada_Prevista` IS NOT NULL
    AND v.`Situação_Voo` IN ('REALIZADO', 'CANCELADO')
  ) AS is_valid,
  -- Motivo de exclusao para quarentena (apenas quando is_valid = false)
  CASE
    WHEN e.icao IS NULL                                       THEN 'ICAO da empresa nao encontrado em silver.empresas'
    WHEN ao.icao IS NULL                                      THEN 'ICAO do aerodromo de origem nao encontrado em silver.aerodromos'
    WHEN ad.icao IS NULL                                      THEN 'ICAO do aerodromo de destino nao encontrado em silver.aerodromos'
    WHEN v.`Partida_Prevista` IS NULL OR v.`Chegada_Prevista` IS NULL THEN 'Horarios previstos de partida/chegada ausentes'
    WHEN v.`Situação_Voo` NOT IN ('REALIZADO', 'CANCELADO')   THEN 'Situacao do voo desconhecida'
    ELSE NULL
  END AS motivo_exclusao
FROM mizukiairflows.bronze.vra v
LEFT JOIN (SELECT DISTINCT icao FROM mizukiairflows.silver.empresas WHERE icao IS NOT NULL) e
  ON v.`ICAO_Empresa_Aérea` = e.icao
LEFT JOIN (SELECT DISTINCT icao FROM mizukiairflows.silver.aerodromos WHERE icao IS NOT NULL) ao
  ON v.`ICAO_Aeródromo_Origem` = ao.icao
LEFT JOIN (SELECT DISTINCT icao FROM mizukiairflows.silver.aerodromos WHERE icao IS NOT NULL) ad
  ON v.`ICAO_Aeródromo_Destino` = ad.icao;
