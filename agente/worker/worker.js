/**
 * Agente público do Mizuki Airflows — proxy de LLM.
 *
 * Existe por um motivo só: guardar a chave da API longe do navegador. A página é estática
 * (GitHub Pages), então qualquer chave que ela carregasse estaria em texto puro no view-source.
 *
 * O que NÃO passa daqui:
 *   - a chave da API (fica em variável de ambiente do Worker)
 *   - o prompt do sistema (fica neste arquivo — ver nota de segurança abaixo)
 *
 * NOTA DE SEGURANÇA. O prompt não vem da página de propósito. Se o cliente pudesse mandar o
 * prompt, este endpoint seria um relay de LLM aberto: alguém acharia a URL e usaria a cota para
 * gerar qualquer coisa. Aceitando só `pergunta` (texto curto) e devolvendo só SQL contra um
 * schema fixo, o pior uso possível continua sendo perguntar sobre voos brasileiros.
 *
 * O SQL gerado NÃO roda aqui. Ele volta para a página e é executado pelo DuckDB-WASM no
 * navegador do visitante, em memória, sobre cinco Parquet estáticos, sem credencial nenhuma.
 * Não existe banco para atacar. A validação em `sqlSuspeito()` é cinto sobre suspensório.
 *
 * Rotas
 *   POST /consulta  {pergunta}              -> {sql, grafico, x, y, titulo, unidade, aviso}
 *   POST /narrar    {pergunta, sql, linhas} -> text/event-stream (a resposta em português)
 *   GET  /saude                             -> {ok, provedor, modelo, gasto_hoje}
 */

// ─────────────────────────────────────────────────────────────────────────────
// Configuração
// ─────────────────────────────────────────────────────────────────────────────

const ORIGENS_PERMITIDAS = [
  "https://leonardo369852.github.io",
  "http://localhost:8000",
  "http://127.0.0.1:8000",
];

const MAX_CARACTERES_PERGUNTA = 300;
const MAX_LINHAS_PARA_NARRAR = 40;
const REQUISICOES_POR_MINUTO_POR_IP = 6;
const LIMITE_DIARIO_PADRAO = 400; // chamadas de LLM por dia, somando as duas rotas
const MAX_TURNOS_HISTORICO = 5;   // conversa enviada ao modelo; mais que isso é token gasto

// ─────────────────────────────────────────────────────────────────────────────
// O schema que o modelo vê
// ─────────────────────────────────────────────────────────────────────────────
//
// Isto é a camada semântica. É a parte do projeto que decide se o agente acerta ou inventa:
// não basta listar colunas, é preciso dizer o que NÃO fazer com elas.

const SCHEMA = `
Banco DuckDB em memória com cinco tabelas sobre voos comerciais brasileiros
(dados abertos VRA da ANAC, set/2025 a ago/2026, 1.014.705 voos).

TABELA fato_voos — agregada, uma linha por combinação de chaves
  Chaves:
    ano_mes            TEXT   'AAAA-MM'. NULL em 30.800 voos sem data de partida prevista.
    icao_empresa       TEXT   junta com dim_empresa.icao_empresa
    icao_origem        TEXT   junta com dim_aerodromo.icao
    icao_destino       TEXT   junta com dim_aerodromo.icao
    situacao_voo       TEXT   'REALIZADO' | 'CANCELADO'
    periodo_partida    TEXT   'madrugada' | 'manha' | 'tarde' | 'noite' (NULL sem horário)
    fim_de_semana      BOOL
    codigo_tipo_linha  TEXT   junta com nada; 'N' nacional, 'I' internacional, entre outros
  Medidas (TODAS aditivas — sempre agregue com SUM, nunca com AVG):
    voos, realizados, cancelados
    partidas_pontuais, chegadas_pontuais, partidas_atrasadas, partidas_severas
    com_atraso_partida, soma_atraso_partida
    com_atraso_chegada, soma_atraso_chegada
    com_duracao, soma_duracao
    com_atraso_plausivel, soma_atraso_plausivel

TABELA dim_empresa
  icao_empresa TEXT, nome TEXT, iata TEXT, servico TEXT, origem_cadastro TEXT,
  situacao TEXT, voos_no_periodo BIGINT, nacional BOOL

TABELA dim_aerodromo
  icao TEXT, nome TEXT, municipio TEXT, uf TEXT, rotulo TEXT,
  latitude DOUBLE, longitude DOUBLE, partidas BIGINT, chegadas BIGINT
  Use SEMPRE "rotulo" para nomear um aeroporto — ver problema 6.

TABELA dim_rota
  icao_origem TEXT, icao_destino TEXT, distancia_km DOUBLE, faixa_distancia TEXT,
  origem_igual_destino BOOL, voos BIGINT

TABELA dim_tempo
  ano_mes TEXT, ano INT, mes INT, nome_mes TEXT, trimestre INT, estacao TEXT,
  primeiro_dia DATE, ultimo_dia DATE, dias_com_voo INT, voos BIGINT, ordem INT
  nome_mes é o rótulo pronto em português, único por linha: 'ago/2025', 'set/2025'.
  Use ele no eixo e ordene por `ordem`. Para comparar o mesmo mês entre anos, use `mes`.
  A linha com ano_mes NULL é o marcador dos voos sem data prevista, e nome_mes nela é NULL.

MÉTRICAS — use exatamente estas fórmulas
  OTP de partida (pontualidade, a métrica nº 1 do setor):
    100.0 * SUM(partidas_pontuais) / NULLIF(SUM(realizados), 0)
    Pontual = atraso <= 15 min (padrão ANAC/IATA). Cancelado NÃO entra no denominador:
    voo que não saiu não pode ser pontual nem atrasado.
  Taxa de cancelamento:
    100.0 * SUM(cancelados) / NULLIF(SUM(voos), 0)
  Atraso médio de partida, em minutos:
    SUM(soma_atraso_partida) / NULLIF(SUM(com_atraso_partida), 0)
  Duração média do voo, em minutos:
    SUM(soma_duracao) / NULLIF(SUM(com_duracao), 0)

  NUNCA escreva AVG() sobre uma medida. O fato é agregado: AVG daria média de média, errada
  sempre que os grupos têm tamanhos diferentes. Sempre SUM(numerador)/SUM(denominador).

PROBLEMAS DA FONTE — considere em toda resposta
  1. ano_mes IS NULL em 30.800 voos (3,0%). Nenhum deles pode ser pontual, mas todos entram
     no denominador. É por isso que o OTP global (79,9%) é MENOR que o de todos os doze meses
     individuais. Em pergunta sobre pontualidade geral, filtre ano_mes IS NOT NULL e diga que
     filtrou. Em pergunta sobre um mês específico, o filtro já é natural.
  2. Atrasos implausíveis: a fonte tem timestamps invertidos e existem empresas com atraso
     médio de -4.313 min. Em ranking de atraso, use soma_atraso_plausivel/com_atraso_plausivel
     (restrito a [-60, 1440] min) e avise no campo "aviso".
  3. dim_rota.origem_igual_destino = true em rotas tipo SBGR->SBGR, 0 km. Em pergunta sobre
     distância, exclua com "AND NOT r.origem_igual_destino".
  4. Cauda longa: empresa com 3 voos pode ter 100% ou 0% de pontualidade. Em ranking, filtre
     com HAVING SUM(realizados) >= 500 (ou >= 100 para aeroportos) e diga o corte no título.
  5. codigo_justificativa dos cancelamentos é 'N/A' em 100% dos casos — a coluna não foi
     exportada porque não tem informação. Se perguntarem o MOTIVO de cancelamentos, responda
     que o dado não existe na fonte. Não invente motivo.
  6. O cadastro de aeródromos da ANAC só cobre aeródromo brasileiro: em 85 dos 224,
     nome/municipio/uf/latitude são NULL — 79 estrangeiros (SCEL Santiago, SABE e SAEZ
     Buenos Aires, KMIA Miami, LPPT Lisboa, MPTO Panamá) e 6 brasileiros fora do cadastro
     (SBIZ, SNCL, SBUY, SSOU, SBCR, SDLO). São 10,5% das partidas. Nomeie aeroporto sempre
     por "rotulo" (= municipio, senão nome, senão o ICAO), nunca por municipio direto. Em
     mapa, filtre latitude IS NOT NULL e avise que os estrangeiros ficam de fora.
  7. Ranking de pontualidade POR AERÓDROMO fica dominado por origens estrangeiras de
     pouco volume: os oito piores são todos estrangeiros. Voo internacional tem
     pontualidade registrada pior (67,2% contra 81,8% dos nacionais). Nesse tipo de
     pergunta, diga no "aviso" que a lista é de aeroportos estrangeiros — ou, se a
     pergunta for sobre o Brasil, restrinja com "a.uf IS NOT NULL".
`;

const QUEM_SOU = `
QUEM VOCÊ É — use isto quando perguntarem sobre você ou sobre o projeto
Você é o agente do Mizuki Airflows, um data warehouse de voos comerciais brasileiros
construído em Databricks em três camadas (Bronze, Silver e Gold) sobre os dados abertos
do VRA da ANAC. Você traduz perguntas em português para SQL. A consulta NÃO roda em
servidor: ela roda no navegador de quem pergunta, com DuckDB compilado em WebAssembly,
sobre um fato agregado de 86.518 linhas exportado da camada Gold. Você não calcula nada
e não guarda dados — quem calcula é a máquina de quem pergunta, e é por isso que cada
resposta mostra o SQL que produziu o número.

VOCÊ É UMA DEMONSTRAÇÃO, E DEVE DIZER ISSO
O agente principal do projeto é um Genie space dentro do Databricks, que consulta a
obt_voos inteira: 1.014.705 linhas, 56 colunas, uma linha por voo. Ele não pode ser
aberto por link porque todo recurso do Databricks exige que o visitante exista dentro
do workspace, com SELECT nas tabelas do Unity Catalog. Você existe para mostrar o
trabalho a quem não tem conta, sobre um recorte agregado que caiba em 1,5 MB.

O que você NÃO consegue responder, por causa do grão agregado — diga com franqueza
quando for o caso, e mencione que o Genie responde:
  · um voo específico: número do voo, data exata, horário de partida ou chegada
  · qualquer corte por dia, ou por dia da semana (você só tem mês, e do dia da semana
    só tem útil contra fim de semana)
  · horário exato (você só tem o período: madrugada, manhã, tarde, noite)
  · minutos de atraso recuperados em voo — medida não exportada
  · status operacional do aeródromo — não exportado
Nunca finja que consegue. Nunca invente uma consulta para uma dessas: responda em
"conversa", diga o que falta e por quê.
`;

const ROTEAMENTO = `
PRIMEIRO decida o campo "tipo". É a decisão mais importante da resposta.

"consulta" — a pergunta pede número, lista, comparação ou evolução que saia das tabelas.
  Inclui pergunta curta que CONTINUA a anterior: "e em fevereiro?", "e a GOL?",
  "por aeroporto", "só as nacionais", "e o pior?". Nesses casos monte a consulta a partir
  da CONVERSA ATÉ AGORA — reaproveite o SQL anterior e troque só o que a pergunta pede.

"conversa" — a pergunta NÃO pede dado novo. Escreva a resposta em "resposta" e deixe
  "sql" vazio. Três casos:
  · sobre a resposta anterior — "o que isso significa?", "por quê?", "isso é bom?",
    "compare com o mês passado" quando os dois números já estão no histórico. Interprete
    os números que estão lá, sem inventar nenhum.
  · sobre você, o projeto, a origem dos dados ou como funciona — use QUEM VOCÊ É.
  · saudação, agradecimento, ou assunto fora de voos. Diga o que você sabe responder.

NUNCA escreva uma consulta que retorne um texto como se fosse resultado — por exemplo
um SELECT com uma mensagem de desculpa. Isso apresenta uma frase inventada com a
aparência de dado consultado, e é o pior erro possível aqui. Se não há consulta a fazer,
o tipo é "conversa".
`;

const REGRAS_SQL = `
Você traduz uma pergunta em português para UMA consulta SQL do DuckDB sobre o schema acima.

Obrigatório:
- Um único SELECT. Sem ponto e vírgula, sem CTE múltipla desnecessária, sem DDL, sem ATTACH,
  sem COPY, sem INSTALL, sem LOAD, sem acesso a arquivo.
- Sempre LIMIT, no máximo 100.
- Nomes de empresa e aeroporto vêm das dimensões por JOIN — nunca invente um nome, nunca
  escreva um ICAO que não esteja na pergunta.
- Apelide toda coluna de saída com AS e um nome curto em minúsculas.
- Nomes de coluna em "x" e "y" têm de ser exatamente os apelidos do SELECT.

Escolha de "grafico":
  barra_horizontal  ranking com rótulo comprido (empresas, aeroportos, rotas) — o padrão
  barra_vertical    poucas categorias curtas
  linha             série temporal (ordene por dim_tempo.ordem)
  dispersao         duas medidas numéricas, uma por entidade
  halteres          mesma entidade em dois estados (ida vs volta, dois meses)
  mapa              precisa de latitude e longitude no SELECT
  tabela            mais de 3 colunas de medida, ou nada disso serve

Preencha "aviso" (uma frase, ou vazio) quando um problema da fonte afeta ESTE número.
Um mês com dias_com_voo menor que 28 está incompleto: a fonte termina no meio dele. Ao
mostrar série por mês, diga isso no "aviso" — senão o último ponto parece uma queda.
Pergunta que o schema não responde NÃO vira consulta: ela é "conversa", como manda o
roteamento. Nunca devolva um SELECT que retorna uma frase de explicação.
`;

/* A narração recebe só o que usa: como as métricas se chamam, quais ressalvas existem
   e o formato. Mandar o SCHEMA inteiro (colunas, fórmulas, regras de SQL) era dobrar a
   entrada de graça — e entrada é latência. */
const CONTEXTO_NARRACAO = `
Dados: voos comerciais brasileiros (VRA/ANAC, set-2025 a ago-2026, 1.014.705 voos).
OTP = pontualidade de partida, atraso <= 15 min, sobre os voos REALIZADOS.
Atraso severo = acima de 60 min. Atraso é sempre em minutos.

Ressalvas da fonte, cite quando afetarem o número em questão:
- 30.800 voos (3,0%) não têm data de partida prevista e ficam fora de qualquer corte
  por tempo; é por isso que o OTP global (79,9%) é menor que o de todos os doze meses.
  Sobre os voos com horário previsto o OTP é 82,5%.
- Alguns atrasos são implausíveis (timestamps invertidos na fonte).
- O motivo dos cancelamentos não existe na fonte: nunca atribua uma causa.
- 10,5% das partidas saem de aeródromo sem cadastro na ANAC (estrangeiros sobretudo).
  Eles aparecem só pelo código ICAO, sem nome: escreva "o aeroporto de código ZBAA",
  nunca apresente um código como se fosse nome de cidade.
- Voo internacional tem pontualidade registrada pior que o nacional (67,2% contra 81,8%),
  então ranking de aeroporto por pontualidade costuma ser todo de estrangeiros de pouco
  volume — se for o caso das linhas recebidas, diga isso.
`;

const REGRAS_NARRACAO = `
Você é um analista de dados do setor aéreo. Recebe uma pergunta, o SQL que foi executado e as
linhas que voltaram. Escreva a resposta em português do Brasil.

- No máximo 4 frases. Comece pela resposta, não pelo método.
- Cite números com unidade: "73,8% dos voos", "18,2 minutos", "3.026 voos".
- Formato brasileiro: vírgula decimal, ponto de milhar.
- Só use números que estão nas linhas recebidas. Nunca estime, nunca complete, nunca arredonde
  para um número "mais bonito". Se as linhas não respondem a pergunta, diga isso.
- Se vier um aviso de qualidade, incorpore em uma frase — o usuário precisa saber quando o
  número tem ressalva.
- Sem saudação, sem "ótima pergunta", sem oferecer ajuda extra, sem repetir a pergunta.
`;

// Enum fechado: o que estiver fora disso a página renderiza como tabela.
const GRAFICOS = [
  "barra_horizontal", "barra_vertical", "linha",
  "dispersao", "halteres", "mapa", "tabela",
];

/**
 * A conversa vira texto para o modelo.
 *
 * Sem isto cada pergunta chega sozinha, e "e em fevereiro?" não tem a que se referir.
 * Vai o SQL de cada turno — para a pergunta seguinte reaproveitar e alterar só o que
 * mudou — e as primeiras linhas do resultado, para as perguntas de interpretação
 * ("o que isso significa?") terem números reais em vez de inventar.
 */
function historicoEmTexto(historico) {
  if (!Array.isArray(historico) || !historico.length) return "";

  const turnos = historico.slice(-MAX_TURNOS_HISTORICO).map((h, i) => {
    const l = [`[${i + 1}] Pergunta: ${String(h.pergunta ?? "").slice(0, 300)}`];
    if (h.sql) {
      l.push(`    SQL executado: ${String(h.sql).replace(/\s+/g, " ").slice(0, 420)}`);
    }
    if (Array.isArray(h.amostra) && h.amostra.length) {
      l.push(`    Resultado (${h.total ?? h.amostra.length} linhas, primeiras): `
             + JSON.stringify(h.amostra).slice(0, 700));
    }
    if (h.resposta) {
      l.push(`    Você respondeu: ${String(h.resposta).slice(0, 320)}`);
    }
    return l.join("\n");
  });

  return "\nCONVERSA ATÉ AGORA — a pergunta nova pode se referir a isto\n"
       + turnos.join("\n") + "\n";
}

// ─────────────────────────────────────────────────────────────────────────────
// Provedores
// ─────────────────────────────────────────────────────────────────────────────
//
// Trocar de IA é mudar PROVEDOR e a chave no painel do Cloudflare. A página não muda.

const PROVEDORES = {
  // Free tier real, sem cartão: ~10 req/min, ~1.500 req/dia nos modelos Flash.
  // Modelos disponíveis:
  //   GET https://generativelanguage.googleapis.com/v1beta/models?key=SUA_CHAVE
  gemini: {
    modeloPadrao: "gemini-flash-latest",
    envChave: "GEMINI_API_KEY",

    url(modelo, chave, stream) {
      const metodo = stream ? "streamGenerateContent?alt=sse&" : "generateContent?";
      return `https://generativelanguage.googleapis.com/v1beta/models/${modelo}:${metodo}key=${chave}`;
    },

    corpo({ sistema, usuario, esquema, maxTokens }) {
      return {
        systemInstruction: { parts: [{ text: sistema }] },
        contents: [{ role: "user", parts: [{ text: usuario }] }],
        generationConfig: {
          temperature: 0,
          maxOutputTokens: maxTokens,
          // Os Gemini 3.x pensam por padrão, e o raciocínio consome maxOutputTokens antes
          // de sobrar texto: com o budget ligado, 3.6-flash e 3.5-flash devolviam resposta
          // VAZIA. Traduzir pergunta em SQL sobre um schema fixo não precisa de raciocínio
          // extenso, então desligamos e todo o orçamento vira resposta.
          thinkingConfig: { thinkingBudget: 0 },
          ...(esquema
            ? { responseMimeType: "application/json", responseSchema: esquema }
            : {}),
        },
      };
    },

    texto(json) {
      return json?.candidates?.[0]?.content?.parts?.map((p) => p.text).join("") ?? "";
    },

    // Um chunk de SSE do Gemini é um JSON completo com o delta em parts[].text.
    delta(json) {
      return json?.candidates?.[0]?.content?.parts?.map((p) => p.text).join("") ?? "";
    },
  },

  // Pago. ~US$ 0,004 por pergunta neste desenho. Melhor qualidade no SQL difícil.
  anthropic: {
    modeloPadrao: "claude-haiku-4-5-20251001",
    envChave: "ANTHROPIC_API_KEY",

    url() {
      return "https://api.anthropic.com/v1/messages";
    },

    cabecalhos(chave) {
      return {
        "x-api-key": chave,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
      };
    },

    corpo({ sistema, usuario, esquema, maxTokens, stream }) {
      return {
        model: this.modelo,
        max_tokens: maxTokens,
        temperature: 0,
        // Marca o schema para cache: é a parte fixa e grande do prompt. Até 90% de desconto
        // na releitura, e é ela que domina os tokens de entrada.
        system: [{ type: "text", text: sistema, cache_control: { type: "ephemeral" } }],
        messages: [{ role: "user", content: usuario }],
        ...(stream ? { stream: true } : {}),
        // JSON garantido via tool use: o modelo é obrigado a preencher o schema.
        ...(esquema
          ? {
              tools: [{ name: "responder", description: "Devolve a consulta", input_schema: esquema }],
              tool_choice: { type: "tool", name: "responder" },
            }
          : {}),
      };
    },

    texto(json) {
      const bloco = json?.content?.find((c) => c.type === "tool_use");
      if (bloco) return JSON.stringify(bloco.input);
      return json?.content?.filter((c) => c.type === "text").map((c) => c.text).join("") ?? "";
    },

    delta(json) {
      return json?.type === "content_block_delta" ? (json.delta?.text ?? "") : "";
    },
  },
};

// ─────────────────────────────────────────────────────────────────────────────
// Guardas
// ─────────────────────────────────────────────────────────────────────────────

const PALAVRAS_PROIBIDAS = [
  "attach", "copy", "install", "load", "export", "import", "create", "insert",
  "update", "delete", "drop", "alter", "pragma", "set ", "read_csv", "read_parquet",
  "read_json", "glob", "system", "shell",
];

/** Devolve o motivo da recusa, ou null se o SQL passou. */
function sqlSuspeito(sql) {
  if (!sql || typeof sql !== "string") return "SQL vazio";
  const s = sql.toLowerCase();
  if (!s.trimStart().startsWith("select") && !s.trimStart().startsWith("with")) {
    return "não começa com SELECT";
  }
  // Ponto e vírgula só é aceito no fim, para não encadear comando.
  if (sql.slice(0, -1).includes(";")) return "mais de um comando";
  for (const p of PALAVRAS_PROIBIDAS) {
    if (new RegExp(`\\b${p.trim()}\\b`).test(s)) return `usa "${p.trim()}"`;
  }
  return null;
}

function cors(origem) {
  const permitida = ORIGENS_PERMITIDAS.includes(origem) ? origem : ORIGENS_PERMITIDAS[0];
  return {
    "Access-Control-Allow-Origin": permitida,
    "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
    "Access-Control-Allow-Headers": "content-type",
    "Access-Control-Max-Age": "86400",
    Vary: "Origin",
  };
}

function json(dados, status, origem) {
  return new Response(JSON.stringify(dados), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", ...cors(origem) },
  });
}

/**
 * Duas travas, as duas em KV.
 *
 * Ressalva honesta: KV é eventualmente consistente, então em rajada simultânea a contagem
 * pode subestimar por alguns segundos. Para um portfólio isso é irrelevante — o que importa é
 * que ninguém consegue rodar mil perguntas num laço. Se um dia precisar de precisão, o
 * binding nativo de Rate Limiting do Cloudflare resolve.
 */
async function semCota(env, ip) {
  if (!env.CONTADORES) return null; // KV não configurado: segue sem trava

  const agora = new Date();
  const minuto = `ip:${ip}:${agora.toISOString().slice(0, 16)}`;
  const dia = `gasto:${agora.toISOString().slice(0, 10)}`;
  const limiteDiario = Number(env.LIMITE_DIARIO ?? LIMITE_DIARIO_PADRAO);

  const [porMinuto, porDia] = await Promise.all([
    env.CONTADORES.get(minuto),
    env.CONTADORES.get(dia),
  ]);

  if (Number(porMinuto ?? 0) >= REQUISICOES_POR_MINUTO_POR_IP) {
    return "Muitas perguntas seguidas. Espere um minuto.";
  }
  if (Number(porDia ?? 0) >= limiteDiario) {
    return "O limite de perguntas do dia foi atingido. Os gráficos da página continuam funcionando — volte amanhã para conversar com o agente.";
  }

  await Promise.all([
    env.CONTADORES.put(minuto, String(Number(porMinuto ?? 0) + 1), { expirationTtl: 120 }),
    env.CONTADORES.put(dia, String(Number(porDia ?? 0) + 1), { expirationTtl: 172800 }),
  ]);
  return null;
}

// ─────────────────────────────────────────────────────────────────────────────
// Chamada ao modelo
// ─────────────────────────────────────────────────────────────────────────────

function resolverProvedor(env) {
  const nome = (env.PROVEDOR ?? "gemini").toLowerCase();
  const p = PROVEDORES[nome];
  if (!p) throw new Error(`PROVEDOR desconhecido: ${nome}`);
  const chave = env[p.envChave];
  if (!chave) throw new Error(`Falta a variável ${p.envChave} no Worker`);
  return { nome, p: { ...p, modelo: env.MODELO ?? p.modeloPadrao }, chave };
}

/* Status que valem nova tentativa: o modelo está ocupado ou o provedor tropeçou.
   503 é rotina no free tier do Gemini — sem retry, o visitante conclui que a demo quebrou. */
const TRANSITORIOS = new Set([500, 502, 503, 504]);

const espera = ms => new Promise(r => setTimeout(r, ms));

/**
 * Chama o modelo com duas defesas:
 *
 *   retry    — até 3 tentativas no mesmo modelo, com espera crescente, quando o erro é
 *              transitório (503 "high demand" e afins).
 *   fallback — esgotadas as tentativas, ou se o modelo sumiu (404) ou estourou a cota
 *              dele (429), passa para o próximo da lista.
 *
 * A lista vem de MODELO + MODELOS_RESERVA, ambos do wrangler.toml, para trocar sem
 * mexer em código. `modeloForcado` só é usado pelo diagnóstico /saude?modelo=...
 */
/* Orçamento de tempo, calibrado por medição — e recalibrado duas vezes.
   12 s abortava consultas que davam certo em 12,6 s. 25 s passou a abortar depois que o
   prompt cresceu com o roteamento e o histórico (de ~1,5 k para ~3 k tokens de entrada).
   A lição é que o prazo tem de acompanhar o tamanho do prompt, então agora ele vem do
   ambiente: dá para ajustar com `wrangler deploy` sem tocar em código.
   Passado o total, a página diz que a IA está ocupada e oferece nova tentativa; as
   perguntas prontas nunca dependeram dela. */
const PRAZO_POR_TENTATIVA_PADRAO = 40000;
const PRAZO_TOTAL_PADRAO = 80000;

async function chamar(env, { sistema, usuario, esquema, maxTokens, stream, modeloForcado }) {
  const { p, chave } = resolverProvedor(env);
  const prazoTentativa = Number(env.PRAZO_TENTATIVA_MS ?? PRAZO_POR_TENTATIVA_PADRAO);
  const limite = Date.now() + Number(env.PRAZO_TOTAL_MS ?? PRAZO_TOTAL_PADRAO);

  const fila = modeloForcado
    ? [modeloForcado]
    : [p.modelo, ...String(env.MODELOS_RESERVA ?? "").split(",").map(s => s.trim()).filter(Boolean)]
        .filter((m, i, a) => a.indexOf(m) === i);   /* sem repetidos */

  let ultimo = null;
  /* Um 429 em qualquer modelo da fila é o diagnóstico que importa — cota esgotada é
     acionável, congestionamento não. Sem isto, se o último modelo da fila apenas
     demorar, o erro final vira 503 e esconde o motivo verdadeiro. */
  let viuCota = false;

  for (const modelo of fila) {
    /* Uma tentativa por modelo. "High demand" é por modelo e não passa em meio segundo,
       então repetir no mesmo só queima orçamento — trocar de modelo é o que resolve.
       A segunda tentativa existe só para erro de rede, que é instantâneo. */
    for (let tentativa = 1; tentativa <= 2; tentativa++) {
      if (Date.now() > limite) {
        ultimo = Object.assign(new Error("prazo esgotado antes de uma resposta"), { status: 503 });
        break;
      }

      let resposta;
      try {
        resposta = await fetch(p.url(modelo, chave, stream), {
          method: "POST",
          headers: p.cabecalhos ? p.cabecalhos(chave) : { "content-type": "application/json" },
          body: JSON.stringify(
            p.corpo.call({ ...p, modelo }, { sistema, usuario, esquema, maxTokens, stream }),
          ),
          /* Sem isto, um upstream pendurado consome sozinho todo o prazo total. */
          signal: AbortSignal.timeout(
            Math.min(prazoTentativa, Math.max(1000, limite - Date.now())),
          ),
        });
      } catch (e) {
        const expirou = e.name === "TimeoutError" || e.name === "AbortError";
        ultimo = Object.assign(
          new Error(expirou ? `${modelo}: sem resposta a tempo` : `rede: ${e.message}`),
          { status: 503 },
        );
        break;   /* pendurado ou rede fora: troca de modelo em vez de repetir */
      }

      if (resposta.ok) return { resposta, p: { ...p, modelo } };

      const detalhe = (await resposta.text()).slice(0, 300);
      ultimo = Object.assign(new Error(`${modelo} ${resposta.status}: ${detalhe}`), {
        status: resposta.status,
      });
      if (resposta.status === 429) viuCota = true;

      /* Qualquer erro de status: trocar de modelo. 404 (sumiu) e 429 (cota) não melhoram
         repetindo; 503 (ocupado) também não melhora em meio segundo. */
      break;
    }
    if (Date.now() > limite) break;
  }

  if (viuCota || ultimo?.status === 429) {
    throw Object.assign(
      new Error(`cota do provedor esgotada${ultimo ? ` — último: ${ultimo.message}` : ""}`),
      { status: 429 },
    );
  }
  if (ultimo && TRANSITORIOS.has(ultimo.status)) {
    throw Object.assign(new Error(`modelos ocupados — ${ultimo.message}`), { status: 503 });
  }
  throw ultimo ?? new Error("falha desconhecida ao chamar o provedor");
}

// ─────────────────────────────────────────────────────────────────────────────
// Rotas
// ─────────────────────────────────────────────────────────────────────────────

const ESQUEMA_CONSULTA = {
  type: "object",
  properties: {
    /* O roteamento vem primeiro de propósito: o modelo decide o tipo antes de tentar
       escrever SQL, em vez de forçar toda pergunta a virar consulta. */
    tipo: { type: "string", enum: ["consulta", "conversa"],
            description: "consulta = precisa de SQL; conversa = responde em prosa" },
    resposta: { type: "string",
                description: "quando tipo=conversa, a resposta em português; senão vazio" },
    sql: { type: "string", description: "quando tipo=consulta, um único SELECT com LIMIT" },
    grafico: { type: "string", enum: GRAFICOS },
    x: { type: "string", description: "apelido da coluna do eixo x" },
    y: { type: "string", description: "apelido da coluna do eixo y" },
    serie: { type: "string", description: "apelido da coluna que separa séries, ou vazio" },
    /* Sem string vazia no enum: o Gemini rejeita o schema inteiro por causa dela.
       "nenhuma" vira "" na página. */
    unidade: { type: "string", enum: ["%", "min", "voos", "km", "nenhuma"] },
    titulo: { type: "string", description: "título do gráfico, com o corte aplicado" },
    aviso: { type: "string", description: "ressalva de qualidade sobre este número, ou vazio" },
  },
  /* Só "tipo" é obrigatório: uma conversa não tem SQL nem eixos. O código valida
     o resto conforme o tipo. */
  required: ["tipo"],
};

async function rotaConsulta(req, env, origem, modeloForcado) {
  const { pergunta, historico } = await req.json();

  if (typeof pergunta !== "string" || !pergunta.trim()) {
    return json({ erro: "pergunta vazia" }, 400, origem);
  }
  if (pergunta.length > MAX_CARACTERES_PERGUNTA) {
    return json({ erro: `pergunta acima de ${MAX_CARACTERES_PERGUNTA} caracteres` }, 400, origem);
  }

  const { resposta, p } = await chamar(env, {
    sistema: SCHEMA + QUEM_SOU + ROTEAMENTO + REGRAS_SQL + historicoEmTexto(historico),
    usuario: pergunta.trim(),
    esquema: ESQUEMA_CONSULTA,
    maxTokens: 900,
    modeloForcado,
  });

  let plano;
  try {
    plano = JSON.parse(p.texto(await resposta.json()));
  } catch {
    return json({ erro: "o modelo não devolveu um plano válido" }, 502, origem);
  }

  /* Conversa: sem SQL, sem gráfico, sem tabela. A página mostra só o texto — é o que
     evita apresentar uma frase do modelo com a aparência de resultado consultado. */
  if (plano.tipo === "conversa") {
    const texto = String(plano.resposta ?? "").trim();
    if (!texto) return json({ erro: "o modelo não escreveu a resposta" }, 502, origem);
    return json({ tipo: "conversa", resposta: texto }, 200, origem);
  }

  const motivo = sqlSuspeito(plano.sql);
  if (motivo) return json({ erro: `consulta recusada: ${motivo}` }, 422, origem);

  plano.tipo = "consulta";
  if (!GRAFICOS.includes(plano.grafico)) plano.grafico = "tabela";
  /* O enum do schema não aceita string vazia, então "sem unidade" viaja como "nenhuma"
     e volta a ser "" aqui — senão o rótulo do gráfico sairia "12 nenhuma". */
  if (plano.unidade === "nenhuma") plano.unidade = "";

  return json(plano, 200, origem);
}

async function rotaNarrar(req, env, origem, modeloForcado) {
  const { pergunta, sql, linhas, aviso, historico } = await req.json();

  if (!Array.isArray(linhas)) return json({ erro: "linhas ausentes" }, 400, origem);

  const amostra = linhas.slice(0, MAX_LINHAS_PARA_NARRAR);
  const usuario = [
    `Pergunta: ${String(pergunta).slice(0, MAX_CARACTERES_PERGUNTA)}`,
    ``,
    `SQL executado:`,
    String(sql).slice(0, 2000),
    ``,
    `Linhas que voltaram (${linhas.length}${linhas.length > amostra.length ? `, mostrando ${amostra.length}` : ""}):`,
    JSON.stringify(amostra),
    aviso ? `\nRessalva de qualidade a incorporar: ${aviso}` : "",
  ].join("\n");

  const { resposta, p } = await chamar(env, {
    sistema: CONTEXTO_NARRACAO + REGRAS_NARRACAO + historicoEmTexto(historico),
    usuario,
    maxTokens: 400,
    stream: true,
    modeloForcado,
  });

  // Reempacota o SSE do provedor num formato único, para a página não saber qual IA respondeu.
  const { readable, writable } = new TransformStream();
  (async () => {
    const escritor = writable.getWriter();
    const codificar = new TextEncoder();
    const leitor = resposta.body.getReader();
    const decodificar = new TextDecoder();
    let sobra = "";

    try {
      for (;;) {
        const { done, value } = await leitor.read();
        if (done) break;
        sobra += decodificar.decode(value, { stream: true });
        const linhasSse = sobra.split("\n");
        sobra = linhasSse.pop() ?? "";

        for (const linha of linhasSse) {
          if (!linha.startsWith("data:")) continue;
          const bruto = linha.slice(5).trim();
          if (!bruto || bruto === "[DONE]") continue;
          try {
            const pedaco = p.delta(JSON.parse(bruto));
            if (pedaco) {
              await escritor.write(codificar.encode(`data: ${JSON.stringify({ t: pedaco })}\n\n`));
            }
          } catch {
            /* chunk parcial: o próximo ciclo completa */
          }
        }
      }
      await escritor.write(codificar.encode(`data: ${JSON.stringify({ fim: true })}\n\n`));
    } catch (e) {
      await escritor.write(codificar.encode(`data: ${JSON.stringify({ erro: String(e) })}\n\n`));
    } finally {
      await escritor.close();
    }
  })();

  return new Response(readable, {
    headers: {
      "content-type": "text/event-stream; charset=utf-8",
      "cache-control": "no-cache",
      ...cors(origem),
    },
  });
}

/**
 * GET /saude            — confere a configuração, sem gastar cota
 * GET /saude?testar=1   — faz uma chamada mínima de verdade ao provedor
 *
 * O teste existe porque um nome de modelo errado ou uma secret ausente passam pela
 * configuração sem erro e só falham na primeira pergunta de um visitante. Melhor
 * descobrir num curl.
 */
async function rotaSaude(env, url, origem) {
  const hoje = new Date().toISOString().slice(0, 10);
  let cfg;
  try {
    cfg = resolverProvedor(env);
  } catch (e) {
    return json({ ok: false, etapa: "configuracao", erro: String(e.message) }, 500, origem);
  }

  const base = {
    provedor: cfg.nome,
    modelo: cfg.p.modelo,
    kv: !!env.CONTADORES,
    gasto_hoje: env.CONTADORES ? Number((await env.CONTADORES.get(`gasto:${hoje}`)) ?? 0) : null,
    limite_diario: Number(env.LIMITE_DIARIO ?? LIMITE_DIARIO_PADRAO),
    prazo_tentativa_ms: Number(env.PRAZO_TENTATIVA_MS ?? PRAZO_POR_TENTATIVA_PADRAO),
    prazo_total_ms: Number(env.PRAZO_TOTAL_MS ?? PRAZO_TOTAL_PADRAO),
  };

  if (url.searchParams.get("testar") !== "1") {
    return json({ ok: true, testado: false, ...base }, 200, origem);
  }

  try {
    const forcado = url.searchParams.get("modelo") || undefined;
    const { resposta, p } = await chamar(env, {
      sistema: "Responda com uma única palavra.",
      usuario: "Diga: funcionando",
      maxTokens: 8,
      modeloForcado: forcado,
    });
    const texto = p.texto(await resposta.json());
    return json(
      { ok: true, testado: true, modelo_que_respondeu: p.modelo,
        resposta_do_modelo: texto.trim(), ...base },
      200, origem,
    );
  } catch (e) {
    return json(
      {
        ok: false,
        testado: true,
        etapa: "chamada ao provedor",
        erro: String(e.message),
        dica: "404 = modelo inexistente ou descontinuado (veja /modelos). 503 = todos os modelos "
            + "da fila ocupados, tente de novo. 400/403 = chave inválida. 429 = cota esgotada.",
        ...base,
      },
      502,
      origem,
    );
  }
}

/** GET /modelos — quais modelos a chave gravada aceita. Só o Gemini expõe isso. */
async function rotaModelos(env, origem) {
  let cfg;
  try {
    cfg = resolverProvedor(env);
  } catch (e) {
    return json({ ok: false, erro: String(e.message) }, 500, origem);
  }
  if (cfg.nome !== "gemini") {
    return json({ ok: false, erro: "só disponível com PROVEDOR=gemini" }, 400, origem);
  }
  const r = await fetch(
    `https://generativelanguage.googleapis.com/v1beta/models?key=${cfg.chave}&pageSize=200`,
  );
  if (!r.ok) {
    return json({ ok: false, erro: `${r.status}: ${(await r.text()).slice(0, 200)}` }, 502, origem);
  }
  const j = await r.json();
  /* Só os que servem para gerar texto, sem o prefixo "models/". */
  const nomes = (j.models ?? [])
    .filter(m => (m.supportedGenerationMethods ?? []).includes("generateContent"))
    .map(m => m.name.replace(/^models\//, ""))
    .sort();
  return json({ ok: true, em_uso: cfg.p.modelo, disponiveis: nomes }, 200, origem);
}

// ─────────────────────────────────────────────────────────────────────────────

export default {
  async fetch(req, env) {
    const origem = req.headers.get("Origin") ?? "";
    const url = new URL(req.url);

    if (req.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: cors(origem) });
    }
    /* Rotas de diagnóstico: não consomem cota (salvo /saude?testar=1, que gasta 8 tokens). */
    if (url.pathname === "/saude") return rotaSaude(env, url, origem);
    if (url.pathname === "/modelos") return rotaModelos(env, origem);

    if (req.method !== "POST") {
      return json({ erro: "use POST" }, 405, origem);
    }

    const ip = req.headers.get("CF-Connecting-IP") ?? "desconhecido";
    const bloqueio = await semCota(env, ip);
    if (bloqueio) return json({ erro: bloqueio }, 429, origem);

    try {
      /* ?modelo= é diagnóstico: mede um modelo específico sem um ciclo de deploy. */
      const forcado = url.searchParams.get("modelo") || undefined;
      if (url.pathname === "/consulta") return await rotaConsulta(req, env, origem, forcado);
      if (url.pathname === "/narrar") return await rotaNarrar(req, env, origem, forcado);
      return json({ erro: "rota inexistente" }, 404, origem);
    } catch (e) {
      const status = [429, 503].includes(e.status) ? e.status : 500;
      const mensagem = {
        429: "A cota diária de IA do free tier acabou — ela reinicia à meia-noite no "
           + "Pacífico. As perguntas prontas continuam funcionando: elas rodam SQL local "
           + "e não dependem do modelo.",
        503: "A IA está congestionada neste momento. Tente de novo em alguns segundos — "
           + "as perguntas prontas não dependem dela.",
        500: "Não consegui responder agora.",
      }[status];
      console.error("falha:", e.message);
      /* O detalhe do provedor volta junto. É o JSON de erro do Gemini — não carrega
         credencial nenhuma — e sem ele qualquer diagnóstico daqui vira adivinhação em
         ciclos de deploy. A mensagem amigável é o que a página mostra; `detalhe` é o
         que aparece no console de quem for depurar. */
      return json({ erro: mensagem, detalhe: String(e.message).slice(0, 400) }, status, origem);
    }
  },
};
