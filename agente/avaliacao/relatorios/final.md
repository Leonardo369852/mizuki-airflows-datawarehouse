# Avaliação — final

Worker `atual (offline)` · 2026-10-07T14:07:25

| Medida | Valor |
|---|---|
| Perguntas corrigidas | 24 de 31 (7 vão à IA e não foram medidas nesta rodada) |
| Acerto (o dado certo na tela) | 24 de 24 (100%) |
| Acerto nas perguntas simples (rota esperada sem IA) | 24 de 24 (100%) |
| Texto sem número inventado | 24 de 24 |
| Texto do modelo barrado pelo verificador da página | 0 |
| Latência das respondidas sem IA | p50 7 ms · p95 25 ms · máx 48 ms |
| Latência das que foram à IA | - |
| Chamadas ao provedor por pergunta | média 0,0 · máx 0 |
| Requisições que o KV conta, por pergunta | média 0,0 |
| Respondidas sem IA, das 31 perguntas | 24 (77%) |
| Reserva atrasada disparou | 0 de 0 planos |
| Planos que precisaram de mais de uma rodada | 0 |
| Chamadas com raciocínio (thoughtsTokenCount > 0) | 0 de 0 |

## Por pergunta

| id | rota esperada | rota | acerto | tempo | chamadas | POSTs | tokens de entrada | número fora |
|---|---|---|---|---|---|---|---|---|
| oi | fixa | fixa | ✓ | 1 ms | 0 | 0 | - | - |
| quem | fixa | fixa | ✓ | 0 ms | 0 | 0 | - | - |
| como | fixa | fixa | ✓ | 1 ms | 0 | 0 | - | - |
| obrigado | fixa | fixa | ✓ | 0 ms | 0 | 0 | - | - |
| ajuda | fixa | fixa | ✓ | 1 ms | 0 | 0 | - | - |
| motivo | fixa | fixa | ✓ | 1 ms | 0 | 0 | - | - |
| voo_especifico | fixa | fixa | ✓ | 1 ms | 0 | 0 | - | - |
| por_dia | fixa | fixa | ✓ | 1 ms | 0 | 0 | - | - |
| horario | fixa | fixa | ✓ | 0 ms | 0 | 0 | - | - |
| cancel_taxa | pronta | pronta | ✓ | 48 ms | 0 | 0 | - | - |
| otp_mes | pronta | pronta | ✓ | 20 ms | 0 | 0 | - | - |
| aero_mov | pronta | pronta | ✓ | 25 ms | 0 | 0 | - | - |
| madrugada | pronta | pronta | ✓ | 8 ms | 0 | 0 | - | - |
| nac_estr | pronta | pronta | ✓ | 21 ms | 0 | 0 | - | - |
| sp_sair | pronta | pronta | ✓ | 20 ms | 0 | 0 | - | - |
| sp_todos | template | template | ✓ | 15 ms | 0 | 0 | - | - |
| mg_partidas | template | template | ✓ | 14 ms | 0 | 0 | - | - |
| latam_voos | template | template | ✓ | 12 ms | 0 | 0 | - | - |
| gol_otp | template | template | ✓ | 9 ms | 0 | 0 | - | - |
| gru_voos | template | template | ✓ | 6 ms | 0 | 0 | - | - |
| cgh_otp | template | template | ✓ | 7 ms | 0 | 0 | - | - |
| dez_voos | template | template | ✓ | 4 ms | 0 | 0 | - | - |
| azul_cancel | template | template | ✓ | 10 ms | 0 | 0 | - | - |
| latam_mes | template | template | ✓ | 15 ms | 0 | 0 | - | - |
| rota_top | ia | ia | — | - | 0 | 0 | - | - |
| atraso_aero | ia | ia | — | - | 0 | 0 | - | - |
| dist_media | ia | ia | — | - | 0 | 0 | - | - |
| estr_top | ia | ia | — | - | 0 | 0 | - | - |
| cancel_periodo | ia | ia | — | - | 0 | 0 | - | - |
| fds | ia | ia | — | - | 0 | 0 | - | - |
| seguimento_mg | ia | ia | — | - | 0 | 0 | - | - |

## Chamadas ao provedor, por modelo

| modelo | chamadas | ok | 503 | 429 | abortadas | outras | entrada média (tokens) | tokens de raciocínio |
|---|---|---|---|---|---|---|---|---|

## Respostas

- **oi** (oi?) — Olá! Eu respondo perguntas sobre voos comerciais brasileiros de ago/2025 a jul/2026: pontualidade, atrasos, cancelamentos, empresas, aeroportos e rotas. Pergunte em português ou use uma das perguntas prontas.
- **quem** (quem é você?) — Sou o agente do Mizuki Airflows, um data warehouse de voos comerciais brasileiros feito em Databricks sobre os dados abertos da ANAC. Traduzo a sua pergunta em SQL, e a consulta roda aqui, no seu navegador, sobre 86.518 linhas agregadas de 1.014.705 voos (ago/
- **como** (como você funciona?) — Em três passos: a IA traduz a pergunta em uma consulta SQL; a consulta roda aqui, no seu navegador, com DuckDB, sobre os dados exportados da camada Gold; e o resultado vira gráfico, tabela e texto. Toda resposta mostra o SQL que produziu o número. As perguntas
- **obrigado** (obrigado!) — Por nada! Se quiser, é só perguntar outra coisa sobre os voos.
- **ajuda** (o que eu posso perguntar?) — Dá para perguntar sobre pontualidade, atrasos, cancelamentos, empresas, aeroportos, estados, rotas e meses — por exemplo, "qual a pontualidade da GOL?", "quantos voos partiram de Minas Gerais?" ou "quais rotas saindo de Guarulhos têm mais voos?". O que a base 
- **motivo** (qual o motivo dos cancelamentos?) — Não existe esse dado: a justificativa de cancelamento está vazia em todos os 29.145 cancelamentos da fonte. Posso mostrar quantos foram, quando e de quem — mas não o porquê.
- **voo_especifico** (o voo AD 4512 de ontem atrasou?) — Não consigo olhar um voo específico: a base que eu consulto é agregada por mês, empresa e rota, sem número de voo nem data exata. O Genie do projeto, no Databricks, consulta voo a voo.
- **por_dia** (quantos voos teve no dia 25 de dezembro?) — Não tenho corte por dia: a base é agregada por mês, e do dia da semana só separa dia útil de fim de semana. Posso responder pelo mês inteiro.
- **horario** (a que horas sai o primeiro voo de congonhas?) — Não tenho horário exato: só o período do dia da partida (madrugada, manhã, tarde e noite). Posso comparar os períodos.
- **cancel_taxa** (que empresa tem a maior taxa de cancelamentos?) — A maior taxa de cancelamento é a da ARAJET S.A.: 73,8% dos voos programados, entre as 15 empresas do gráfico.
  `SELECT e.nome AS empresa,
       100.0 * SUM(f.cancelados) / SUM(f.voos) AS taxa,
       SUM(f.voos) AS programados
FROM fato_voos f JOIN dim_empresa e ON f.icao_empresa = e.icao_empresa
GROUP BY e.nome
HAVING SUM(f.voos`
- **otp_mes** (como a pontualidade variou ao longo dos meses?) — A pontualidade de partida ficou entre 72,0%, em dez/2025, e 85,9%, em ago/2025.
  `SELECT t.nome_mes AS mes,
       100.0 * SUM(f.partidas_pontuais) / NULLIF(SUM(f.realizados), 0) AS otp,
       SUM(f.realizados) AS realizados
FROM fato_voos f JOIN dim_tempo t ON f.ano_mes = t.ano_mes
WHERE t.dias_com_`
- **aero_mov** (quais são os aeroportos mais movimentados?) — O aeródromo com mais partidas é GUARULHOS, com 147.976; o mapa mostra os 58 mais movimentados.
  `SELECT a.icao, a.rotulo AS local, a.latitude, a.longitude,
       SUM(f.voos) AS voos,
       100.0 * SUM(f.partidas_pontuais) / NULLIF(SUM(f.realizados), 0) AS otp
FROM fato_voos f JOIN dim_aerodromo a ON f.icao_origem `
- **madrugada** (vale a pena voar de madrugada?) — O período mais pontual é madrugada, com 87,7% dos voos no horário; o menos pontual é noite, com 77,2%.
  `SELECT f.periodo_partida AS periodo,
       100.0 * SUM(f.partidas_pontuais) / NULLIF(SUM(f.realizados), 0) AS otp,
       SUM(f.realizados) AS realizados
FROM fato_voos f
WHERE f.periodo_partida IS NOT NULL
GROUP BY f.p`
- **nac_estr** (as empresas nacionais atrasam menos que as estrangeiras?) — O atraso médio de partida é de 23,6 min entre as Estrangeiras e de 5,5 min entre as Nacionais.
  `SELECT CASE WHEN e.nacional THEN 'Nacionais' ELSE 'Estrangeiras' END AS grupo,
       SUM(f.soma_atraso_plausivel) / NULLIF(SUM(f.com_atraso_plausivel), 0) AS atraso,
       100.0 * SUM(f.partidas_pontuais) / NULLIF(SUM(`
- **sp_sair** (sair de sp é pior que chegar?) — Na rota com a maior diferença, SÃO LUÍS, a pontualidade é de 65,0% saindo de GRU/CGH contra 81,4% chegando.
  `WITH sp AS (SELECT 'SBGR' AS icao UNION ALL SELECT 'SBSP'),
saindo AS (
  SELECT f.icao_destino AS ponta,
         100.0 * SUM(f.partidas_pontuais) / NULLIF(SUM(f.realizados), 0) AS otp,
         SUM(f.realizados) AS n
 `
- **sp_todos** (voos em sao paulo, todos) — Os 16 aeroportos do estado de SP somam 317.327 partidas; o maior é GUARULHOS, com 147.976.
  `SELECT a.rotulo AS aeroporto, SUM(f.voos) AS voos
FROM fato_voos f
JOIN dim_aerodromo a ON f.icao_origem = a.icao
WHERE a.uf = 'SP'
GROUP BY a.icao, a.rotulo
ORDER BY voos DESC
LIMIT 40`
- **mg_partidas** (quantos voos partiram de minas gerais?) — Os 16 aeroportos do estado de MG somam 69.245 partidas; o maior é CONFINS, com 56.874.
  `SELECT a.rotulo AS aeroporto, SUM(f.voos) AS voos
FROM fato_voos f
JOIN dim_aerodromo a ON f.icao_origem = a.icao
WHERE a.uf = 'MG'
GROUP BY a.icao, a.rotulo
ORDER BY voos DESC
LIMIT 40`
- **latam_voos** (quantos voos a latam fez?) — A marca LATAM soma 320.579 voos; a maior operadora é a TAM LINHAS AÉREAS S.A., com 302.082.
  `SELECT e.nome AS empresa, SUM(f.voos) AS voos
FROM fato_voos f
JOIN dim_empresa e ON f.icao_empresa = e.icao_empresa
WHERE e.marca = 'LATAM'
GROUP BY e.nome
ORDER BY voos DESC
LIMIT 10`
- **gol_otp** (qual a pontualidade da gol?) — A pontualidade de partida da GOL é de 86,1%, sobre 251.589 voos realizados.
  `SELECT 100.0 * SUM(f.partidas_pontuais) / NULLIF(SUM(f.realizados), 0) AS otp, SUM(f.realizados) AS realizados
FROM fato_voos f
JOIN dim_empresa e ON f.icao_empresa = e.icao_empresa
WHERE e.marca = 'GOL' AND f.ano_mes IS`
- **gru_voos** (quantos voos saíram de gru?) — Saíram 147.976 voos de GUARULHOS (SBGR).
  `SELECT SUM(f.voos) AS voos
FROM fato_voos f
WHERE f.icao_origem = 'SBGR'
LIMIT 1`
- **cgh_otp** (qual a pontualidade de congonhas?) — A pontualidade de partida em SÃO PAULO (SBSP) é de 80,6%, sobre 93.061 voos realizados.
  `SELECT 100.0 * SUM(f.partidas_pontuais) / NULLIF(SUM(f.realizados), 0) AS otp, SUM(f.realizados) AS realizados
FROM fato_voos f
WHERE f.icao_origem = 'SBSP' AND f.ano_mes IS NOT NULL
LIMIT 1`
- **dez_voos** (quantos voos teve em dezembro de 2025?) — Foram 85.452 voos em dez/2025.
  `SELECT SUM(f.voos) AS voos
FROM fato_voos f
WHERE f.ano_mes = '2025-12'
LIMIT 1`
- **azul_cancel** (qual a taxa de cancelamento da azul?) — A taxa de cancelamento da AZUL é de 2,2%, com 6.497 voos cancelados.
  `SELECT SUM(f.cancelados) AS cancelados, 100.0 * SUM(f.cancelados) / NULLIF(SUM(f.voos), 0) AS taxa
FROM fato_voos f
JOIN dim_empresa e ON f.icao_empresa = e.icao_empresa
WHERE e.marca = 'AZUL'
LIMIT 1`
- **latam_mes** (voos por mês da latam) — Os voos por mês da LATAM variaram de 24.259, em fev/2026, a 28.629, em jul/2026.
  `SELECT t.nome_mes AS mes, SUM(f.voos) AS voos
FROM fato_voos f
JOIN dim_empresa e ON f.icao_empresa = e.icao_empresa
JOIN dim_tempo t ON f.ano_mes = t.ano_mes
WHERE t.dias_com_voo >= 28 AND e.marca = 'LATAM'
GROUP BY t.n`
