/**
 * Agente público do Mizuki Airflows — proxy de LLM.
 *
 * Existe por um motivo só: guardar a chave da API longe do navegador. A página é estática
 * (GitHub Pages), então qualquer chave que ela carregasse estaria em texto puro no view-source.
 *
 * O que NÃO passa daqui:
 *   - a chave da API (fica em variável de ambiente do Worker)
 *   - o prompt do sistema (montado aqui, de agente/conhecimento/, que entra no build)
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
 *   POST /consulta  {pergunta, historico}   -> {sql, grafico, x, y, titulo, unidade, aviso, frase}
 *
 * Não há /narrar: a resposta em texto vem na `frase` do plano, com marcadores no lugar dos
 * números, e a página a preenche com o resultado (agente/narrador.js). Era uma segunda
 * chamada à IA por pergunta, e foi ela que somou 16 linhas como 322.327 em vez de 317.327.
 *   GET  /saude                             -> configuração, contadores do dia e disjuntor
 */

import semantica from "../conhecimento/semantica.json" with { type: "json" };
import identidade from "../conhecimento/identidade.json" with { type: "json" };
import exemplosJson from "../conhecimento/exemplos.json" with { type: "json" };
import fatosJson from "../conhecimento/fatos.json" with { type: "json" };
import { promptConsulta, exemplosEmTexto } from "../conhecimento/montar.js";
import { normalizar, exemplosParecidos } from "../roteador.js";

// ─────────────────────────────────────────────────────────────────────────────
// Configuração
// ─────────────────────────────────────────────────────────────────────────────

const ORIGENS_PERMITIDAS = [
  "https://leonardo369852.github.io",
  "http://localhost:8000",
  "http://127.0.0.1:8000",
];

const MAX_CARACTERES_PERGUNTA = 300;
const REQUISICOES_POR_MINUTO_POR_IP = 6;
const LIMITE_DIARIO_PADRAO = 400; // perguntas que vão à IA por dia; as do cache não contam
const MAX_TURNOS_HISTORICO = 5;   // conversa enviada ao modelo; mais que isso é token gasto
const DISJUNTOR_FALHAS_PADRAO = 3;      // falhas seguidas que pausam a IA
const DISJUNTOR_PAUSA_PADRAO = 300000;  // por quanto tempo, em ms
/* Plano guardado por 7 dias. A chave já muda com o export e com o prompt; o prazo só limita
   quanto tempo um plano ruim que ninguém revisou sobrevive. */
const CACHE_PLANO_TTL = 7 * 24 * 3600;

// ─────────────────────────────────────────────────────────────────────────────
// O que o modelo sabe
// ─────────────────────────────────────────────────────────────────────────────
//
// A camada semântica é a parte do projeto que decide se o agente acerta ou inventa: não basta
// listar colunas, é preciso dizer o que NÃO fazer com elas. Ela mora em agente/conhecimento/,
// junto da identidade e dos fatos, e a página lê os mesmos arquivos — uma fonte só.
//
// Os números não são digitados: vêm de fatos.json, gerado do manifest do export. Quando eram
// digitados aqui, o período chegou a dizer set/2025 a ago/2026 para dados de ago/2025 a
// jul/2026. conferir.py prova cada coluna, exemplo e fato contra os Parquet.

const CONHECIMENTO = { semantica, identidade, fatos: fatosJson.fatos };
const PROMPT_CONSULTA = promptConsulta(CONHECIMENTO);
const EXEMPLOS = exemplosJson.exemplos;
/* Exemplos no prompt: só os parecidos com a pergunta. Os 18 inteiros custariam ~2,5 mil
   tokens em toda pergunta; quatro escolhidos, ~600. */
const EXEMPLOS_NO_PROMPT_PADRAO = 4;


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
    if (h.total === 0) {
      l.push("    Resultado: 0 linhas — nenhum registro bateu com os filtros desta consulta.");
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
 * Travas e contadores, em KV.
 *
 * Ressalva honesta: KV é eventualmente consistente, então em rajada simultânea a contagem
 * pode subestimar por alguns segundos. Para um portfólio isso é irrelevante — o que importa é
 * que ninguém consegue rodar mil perguntas num laço. Se um dia precisar de precisão, o
 * binding nativo de Rate Limiting do Cloudflare resolve.
 */
async function limitePorMinuto(env, ip) {
  if (!env.CONTADORES) return null; // KV não configurado: segue sem trava
  const chave = `ip:${ip}:${new Date().toISOString().slice(0, 16)}`;
  const n = Number((await env.CONTADORES.get(chave)) ?? 0);
  if (n >= REQUISICOES_POR_MINUTO_POR_IP) return "Muitas perguntas seguidas. Espere um minuto.";
  await env.CONTADORES.put(chave, String(n + 1), { expirationTtl: 120 });
  return null;
}

/* O DIA, NUMA CHAVE SÓ. O plano gratuito do KV aceita poucas escritas por dia e uma por
   segundo na mesma chave, então perguntas, chamadas ao provedor por modelo e desfecho, tokens,
   a reserva atrasada e o disjuntor moram juntos, e cada requisição grava uma vez, no fim, por
   waitUntil — depois de a resposta já ter saído. Antes o KV contava só perguntas; a cota do
   provedor gasta chamadas, e uma pergunta podia custar de 2 a 20 delas. */
const chaveDoDia = () => `dia:${new Date().toISOString().slice(0, 10)}`;
const diaVazio = () => ({ perguntas: 0, do_cache: 0, chamadas: {}, tokens: {},
                          reserva: { disparou: 0, venceu: 0 }, falhas_seguidas: 0, pausa_ate: 0 });

async function lerDia(env) {
  if (!env.CONTADORES) return diaVazio();
  try {
    return { ...diaVazio(), ...((await env.CONTADORES.get(chaveDoDia(), "json")) ?? {}) };
  } catch {
    return diaVazio();
  }
}

/** Lê de novo, aplica a mudança e grava. Contador é de melhor esforço: falha de KV não
    derruba resposta nenhuma. */
async function anotarDia(env, mudar) {
  if (!env.CONTADORES) return;
  try {
    const dia = await lerDia(env);
    mudar(dia);
    await env.CONTADORES.put(chaveDoDia(), JSON.stringify(dia), { expirationTtl: 172800 });
  } catch (e) {
    console.warn("contadores do dia:", e?.message);
  }
}

/** O que trabalho depois da resposta precisa: waitUntil no Worker; fora dele, só segue. */
const depois = (ctx, promessa) => (ctx?.waitUntil ? ctx.waitUntil(promessa) : promessa.catch(() => {}));

/**
 * O que uma ida ao provedor deixa no dia: a pergunta, as chamadas por modelo e desfecho, os
 * tokens (o de raciocínio prova se o thinkingBudget 0 está valendo), a reserva e o disjuntor.
 *
 * DISJUNTOR. Com o free tier fora do ar, cada pergunta esperava o prazo inteiro para cair no
 * mesmo erro, gastando chamadas nisso. Depois de DISJUNTOR_FALHAS falhas seguidas (503 ou 429),
 * a IA fica em pausa por DISJUNTOR_PAUSA_MS: a página recebe 503 na hora, sem chamada nenhuma,
 * e oferece as perguntas prontas. Passada a pausa, a próxima pergunta testa de novo — e se ela
 * falhar, a pausa volta sem esperar outras três.
 */
function contabilizar(dia, env, { registro = [], uso = null, modelo = null, reserva = null, falhou = null }) {
  dia.perguntas += 1;
  for (const c of registro) {
    const m = (dia.chamadas[c.modelo] ??= {});
    m[c.desfecho] = (m[c.desfecho] ?? 0) + 1;
  }
  if (uso && modelo) {
    const t = (dia.tokens[modelo] ??= { n: 0, entrada: 0, raciocinio: 0, saida: 0 });
    t.n += 1;
    t.entrada += uso.promptTokenCount ?? 0;
    t.raciocinio += uso.thoughtsTokenCount ?? 0;
    t.saida += uso.candidatesTokenCount ?? 0;
  }
  if (reserva?.disparou) dia.reserva.disparou += 1;
  if (reserva?.venceu) dia.reserva.venceu += 1;
  if (falhou === false) dia.falhas_seguidas = 0;
  if (falhou) {
    const limite = Number(env.DISJUNTOR_FALHAS ?? DISJUNTOR_FALHAS_PADRAO);
    dia.falhas_seguidas += 1;
    if (dia.falhas_seguidas >= limite) {
      dia.pausa_ate = Date.now() + Number(env.DISJUNTOR_PAUSA_MS ?? DISJUNTOR_PAUSA_PADRAO);
      dia.falhas_seguidas = limite - 1;      /* meia-aberta: uma falha depois da pausa basta */
    }
  }
}

/** O dia ainda permite chamar a IA? Limite de perguntas e disjuntor, sem gastar chamada. */
function bloqueioDoDia(dia, env) {
  if (dia.perguntas >= Number(env.LIMITE_DIARIO ?? LIMITE_DIARIO_PADRAO)) {
    return { status: 429, erro: "O limite de perguntas do dia foi atingido. As perguntas prontas continuam "
      + "funcionando, sem IA — volte amanhã para conversar com o agente." };
  }
  if (dia.pausa_ate > Date.now()) {
    const min = Math.max(1, Math.ceil((dia.pausa_ate - Date.now()) / 60000));
    return { status: 503, pausa_ate: dia.pausa_ate,
             erro: `A IA gratuita está congestionada, e eu dou uma pausa de ${min} min a ela. `
                 + "As perguntas prontas respondem na hora, sem ela." };
  }
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
/* Medido em 23/09/2026 com a pergunta real de um visitante: 3.6-flash e 3.1-flash-lite
   respondem em 4 a 5 s; 3.5-flash leva mais de 30 s e ainda falha. Os 40 s antigos
   existiam para esperar o 3.5-flash — um modelo calado depois de 15 s está congestionado,
   e trocar para o próximo sai mais barato que esperar. */
const PRAZO_POR_TENTATIVA_PADRAO = 15000;
const PRAZO_TOTAL_PADRAO = 40000;
/* Depois que o modelo começa a responder em streaming, este prazo só protege contra
   stream parado. */
const PRAZO_CORPO_MS = 30000;
/* Quanto o principal pode demorar antes de a reserva entrar junto, no /consulta. Acima
   dos 3 a 5 s de um principal saudável, para ela quase nunca disparar à toa. */
const ATRASO_RESERVA_PADRAO = 6000;
/* FALHA RÁPIDA. O /consulta chegou a insistir por um minuto, em quatro rodadas, para o
   visitante não ter de clicar em "tentar de novo" — e a espera de um minuto virou o problema.
   Agora são 20 s e duas rodadas; na falha a página oferece na hora as perguntas prontas mais
   parecidas, que não dependem da IA. Tudo vem do wrangler.toml. */
const PRAZO_CONSULTA_PADRAO = 20000;
const RODADAS_PADRAO = 2;              /* espera de 1,5 s entre elas */
const ESPERA_RODADA_PADRAO = 1500;

async function chamar(env, { sistema, usuario, esquema, maxTokens, stream, modeloForcado,
                              atrasoReserva, insistir, prazoTotal, registro = [] }) {
  const { p, chave } = resolverProvedor(env);
  const prazoTentativa = Number(env.PRAZO_TENTATIVA_MS ?? PRAZO_POR_TENTATIVA_PADRAO);
  const limite = Date.now() + Number(prazoTotal ?? env.PRAZO_TOTAL_MS ?? PRAZO_TOTAL_PADRAO);
  /* Menos que isto até o limite, uma tentativa nova não chega a responder: não vale lançar. */
  const minimoUtil = Math.min(4000, prazoTentativa / 3);

  const fila = modeloForcado
    ? [modeloForcado]
    : [p.modelo, ...String(env.MODELOS_RESERVA ?? "").split(",").map(s => s.trim())]
        .filter(Boolean)
        .filter((m, i, a) => a.indexOf(m) === i);   /* sem repetidos */

  let ultimo = null;
  /* Um 429 em qualquer modelo da fila é o diagnóstico que importa — cota esgotada é
     acionável, congestionamento não. Sem isto, se o último modelo da fila apenas
     demorar, o erro final vira 503 e esconde o motivo verdadeiro. */
  let viuCota = false;
  /* Último status de cada modelo nesta pergunta: decide quem volta na rodada seguinte. */
  const estado = new Map();

  /* Uma tentativa num modelo. Nunca rejeita: devolve {ok, resposta, modelo, ctl} ou
     {ok: false, erro}, para a corrida abaixo tratar sucesso e falha do mesmo jeito. Cada
     tentativa vai para o `registro` com o desfecho — o status HTTP, "tempo" (o prazo dela
     acabou) ou "perdeu" (outra respondeu antes) —, que é o que a cota do provedor de fato
     gasta. */
  async function tentar(modelo, ctl) {
    const inicio = Date.now();
    ctl.anotar = (desfecho) => {
      if (ctl.anotada) return;
      ctl.anotada = true;
      registro.push({ modelo, desfecho, ms: Date.now() - inicio });
    };
    /* O prazo vale até a resposta COMEÇAR. Com AbortSignal.timeout ele valia também
       para o corpo, e numa resposta em streaming um prazo curto cortaria o texto no
       meio. Chegados os cabeçalhos, um prazo folgado só protege contra stream parado. */
    /* Nunca além do limite total: é o que garante os ~20 s do /consulta. */
    const relogio = setTimeout(() => { ctl.anotar("tempo"); ctl.abort(); },
      Math.max(0, Math.min(prazoTentativa, limite - Date.now())));
    try {
      const resposta = await fetch(p.url(modelo, chave, stream), {
        method: "POST",
        headers: p.cabecalhos ? p.cabecalhos(chave) : { "content-type": "application/json" },
        body: JSON.stringify(
          p.corpo.call({ ...p, modelo }, { sistema, usuario, esquema, maxTokens, stream }),
        ),
        /* Sem isto, um upstream pendurado consome sozinho todo o prazo total. */
        signal: ctl.signal,
      });
      clearTimeout(relogio);
      ctl.anotar(String(resposta.status));
      if (resposta.ok) return { ok: true, resposta, modelo, ctl };
      const detalhe = (await resposta.text()).slice(0, 300);
      return { ok: false, erro: Object.assign(
        new Error(`${modelo} ${resposta.status}: ${detalhe}`), { status: resposta.status }) };
    } catch (e) {
      clearTimeout(relogio);
      const expirou = e.name === "TimeoutError" || e.name === "AbortError";
      ctl.anotar(expirou ? "tempo" : "rede");
      return { ok: false, erro: Object.assign(
        new Error(expirou ? `${modelo}: sem resposta a tempo` : `rede: ${e.message}`),
        { status: 503 }) };
    }
  }

  /* Uma rodada: os candidatos correm um por vez, e o próximo só entra quando o anterior
     falha. A exceção é a RESERVA ATRASADA (só no /consulta): se o primeiro passa de
     atrasoReserva sem responder, o segundo entra junto e fica quem responder primeiro.
     Medido em 23/09/2026: o principal saudável responde em 3 a 5 s, mas às vezes fica
     pendurado até o prazo de 15 s — e aí a pergunta levava 20 s; com a reserva aos 6 s,
     esse caso cai para uns 11 s. Ela dispara no máximo uma vez por rodada, e quem perde
     a corrida é abortado — e anotado como "perdeu" no dia, porque a chamada foi feita. */
  async function rodada(candidatos) {
    const inicio = Date.now();
    const correndo = new Map();                /* promessa da tentativa -> seu AbortController */
    let proximo = 0;
    let reservaPendente = atrasoReserva > 0 && candidatos.length > 1;
    let reservaUsada = false;

    const lancar = () => {
      if (proximo >= candidatos.length || limite - Date.now() < minimoUtil) return false;
      const ctl = new AbortController();
      const modelo = candidatos[proximo++];
      const promessa = tentar(modelo, ctl).then((r) => ({ promessa, r, modelo }));
      correndo.set(promessa, ctl);
      return true;
    };

    lancar();
    while (correndo.size) {
      const concorrentes = [...correndo.keys()];
      let relogioReserva;
      /* A reserva só vale enquanto o primeiro corre sozinho. */
      if (reservaPendente && proximo === 1 && correndo.size === 1) {
        const falta = Math.max(0, inicio + atrasoReserva - Date.now());
        concorrentes.push(new Promise((ok) => {
          relogioReserva = setTimeout(() => ok({ reserva: true }), falta);
        }));
      }
      const evento = await Promise.race(concorrentes);
      clearTimeout(relogioReserva);

      if (evento.reserva) {
        reservaPendente = false;
        reservaUsada = lancar();
        continue;
      }

      correndo.delete(evento.promessa);
      const { r, modelo } = evento;
      if (r.ok) {
        for (const ctl of correndo.values()) {   /* quem perdeu para de gastar */
          ctl.anotar?.("perdeu");
          ctl.abort();
        }
        if (stream) setTimeout(() => r.ctl.abort(), PRAZO_CORPO_MS);
        return { r, reservaUsada, reservaVenceu: reservaUsada && modelo !== candidatos[0] };
      }

      ultimo = r.erro;
      estado.set(modelo, r.erro.status);
      if (r.erro.status === 429) viuCota = true;
      /* Falhou. Se a reserva ainda não tinha disparado, ela deixa de fazer sentido: o
         próximo entra agora, como substituto. Com outra tentativa ainda correndo, espera
         por ela em vez de abrir uma terceira frente. */
      reservaPendente = false;
      if (!correndo.size) lancar();
    }
    return null;
  }

  /* INSISTIR (só no /consulta). No free tier, "high demand" é quase sempre momentâneo:
     medido, a mesma pergunta que falha agora responde em 6 s dez segundos depois. Mas a
     fila desistia na primeira volta — e, com os dois modelos rápidos devolvendo 503 em
     poucos segundos, ela caía no 3.5-flash, que leva mais de 30 s. Insistindo, cada rodada
     usa só os dois primeiros modelos ELEGÍVEIS, com uma espera entre elas: repetir os
     rápidos sai mais barato que esperar os lentos. Um modelo sai da disputa só com erro que
     não passa com o tempo (404, sumiu; 429, cota) — aí o próximo da fila sobe no lugar dele.
     Quantas rodadas, RODADAS_CONSULTA; quanto tempo ao todo, PRAZO_CONSULTA_MS. Sem
     insistir, a rodada é uma só e percorre a fila inteira, como sempre foi. */
  const temporario = (st) => TRANSITORIOS.has(st);
  const rodadas = insistir && !modeloForcado ? Math.max(1, Number(env.RODADAS_CONSULTA ?? RODADAS_PADRAO)) : 1;
  const esperaBase = Number(env.ESPERA_RODADA_MS ?? ESPERA_RODADA_PADRAO);

  for (let n = 1; n <= rodadas; n++) {
    const elegiveis = fila.filter(m => !estado.has(m) || temporario(estado.get(m)));
    if (!elegiveis.length) break;
    const venceu = await rodada(rodadas > 1 ? elegiveis.slice(0, 2) : elegiveis);
    if (venceu) {
      const { r, reservaUsada, reservaVenceu } = venceu;
      return { resposta: r.resposta, p: { ...p, modelo: r.modelo }, reserva: reservaUsada, reservaVenceu, rodadas: n };
    }
    if (n === rodadas) break;
    const espera = esperaBase * 2 ** (n - 1);
    if (limite - Date.now() < espera + minimoUtil) break;   /* não sobra tempo para uma tentativa útil */
    await new Promise((ok) => setTimeout(ok, espera));
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
    /* A resposta em texto, com marcadores no lugar dos números ({total.voos}, {maior.rotulo}):
       a página preenche com o resultado da consulta. É o que aposentou o /narrar — uma
       chamada a menos por pergunta, e nenhum número escrito de cabeça. */
    frase: { type: "string", description: "a resposta em até duas frases, com marcadores no lugar de todo número" },
  },
  /* Só "tipo" é obrigatório: uma conversa não tem SQL nem eixos. O código valida
     o resto conforme o tipo. */
  required: ["tipo"],
};

/* CACHE DE PLANO. A mesma pergunta, sem conversa antes, pede o mesmo plano: a segunda vez sai
   do KV, sem chamada nenhuma. A chave junta a pergunta normalizada, a data do export (dado
   novo, plano novo) e a versão do prompt (regra nova, plano novo). Plano que volta vazio na
   página é apagado — a revisão de consulta vazia chega aqui com ele no histórico —, e o
   "tentar de novo" da página pula o cache. */
let versaoDoPrompt = null;
async function sha256(texto) {
  const b = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(texto));
  return [...new Uint8Array(b)].map((x) => x.toString(16).padStart(2, "0")).join("");
}
async function chaveDoPlano(pergunta) {
  versaoDoPrompt ??= sha256(PROMPT_CONSULTA + JSON.stringify(EXEMPLOS)).then((h) => h.slice(0, 12));
  const base = `${normalizar(pergunta)}|${fatosJson.manifest_gerado_em}|${await versaoDoPrompt}`;
  return `plano:${(await sha256(base)).slice(0, 32)}`;
}

async function rotaConsulta(req, env, ctx, origem, modeloForcado) {
  const { pergunta, historico, semCache } = await req.json();

  if (typeof pergunta !== "string" || !pergunta.trim()) {
    return json({ erro: "pergunta vazia" }, 400, origem);
  }
  if (pergunta.length > MAX_CARACTERES_PERGUNTA) {
    return json({ erro: `pergunta acima de ${MAX_CARACTERES_PERGUNTA} caracteres` }, 400, origem);
  }
  const conversa = Array.isArray(historico) ? historico : [];

  const kv = env.CONTADORES && !modeloForcado ? env.CONTADORES : null;
  const chave = kv && !conversa.length ? await chaveDoPlano(pergunta) : null;
  if (chave && !semCache) {
    const guardado = await kv.get(chave, "json");
    if (guardado) {
      depois(ctx, anotarDia(env, (d) => { d.do_cache += 1; }));
      return json({ ...guardado, cache: true }, 200, origem);
    }
  }
  const anterior = conversa.at(-1);
  if (kv && anterior?.total === 0 && normalizar(anterior.pergunta) === normalizar(pergunta)) {
    depois(ctx, chaveDoPlano(pergunta).then((k) => kv.delete(k)));     /* o plano guardado voltou vazio */
  }

  const bloqueio = bloqueioDoDia(await lerDia(env), env);
  if (bloqueio) return json({ erro: bloqueio.erro, pausa_ate: bloqueio.pausa_ate ?? null }, bloqueio.status, origem);

  const escolhidos = exemplosParecidos(pergunta, EXEMPLOS,
    Number(env.EXEMPLOS_NO_PROMPT ?? EXEMPLOS_NO_PROMPT_PADRAO));
  const registro = [];
  const t0 = Date.now();
  let chamada;
  try {
    chamada = await chamar(env, {
      sistema: PROMPT_CONSULTA + exemplosEmTexto(escolhidos, CONHECIMENTO.fatos) + historicoEmTexto(conversa),
      usuario: pergunta.trim(),
      esquema: ESQUEMA_CONSULTA,
      maxTokens: 900,
      modeloForcado,
      atrasoReserva: Number(env.ATRASO_RESERVA_MS ?? ATRASO_RESERVA_PADRAO),
      insistir: true,
      prazoTotal: Number(env.PRAZO_CONSULTA_MS ?? PRAZO_CONSULTA_PADRAO),
      registro,
    });
  } catch (e) {
    console.log(JSON.stringify({ rota: "consulta", ms: Date.now() - t0, falhou: e.status ?? 500, registro }));
    depois(ctx, anotarDia(env, (d) => contabilizar(d, env, { registro, falhou: [429, 503].includes(e.status) })));
    throw e;
  }
  const { resposta, p, reserva, reservaVenceu, rodadas } = chamada;

  let corpo, plano;
  try {
    corpo = await resposta.json();
    plano = JSON.parse(p.texto(corpo));
  } catch {
    plano = null;
  }
  /* O que prova o raciocínio desligado é o thoughtsTokenCount de cada modelo — vai no log
     (wrangler tail) e nos contadores do dia, no /saude. */
  const uso = corpo?.usageMetadata ?? null;
  console.log(JSON.stringify({ rota: "consulta", modelo: p.modelo, ms: Date.now() - t0, rodadas, reserva,
                               reservaVenceu, uso, registro }));
  depois(ctx, anotarDia(env, (d) => contabilizar(d, env, { registro, uso, modelo: p.modelo,
    reserva: { disparou: reserva, venceu: reservaVenceu }, falhou: false })));
  if (!plano) return json({ erro: "o modelo não devolveu um plano válido" }, 502, origem);

  let saida;
  /* Conversa: sem SQL, sem gráfico, sem tabela. A página mostra só o texto — é o que
     evita apresentar uma frase do modelo com a aparência de resultado consultado. */
  if (plano.tipo === "conversa") {
    const texto = String(plano.resposta ?? "").trim();
    if (!texto) return json({ erro: "o modelo não escreveu a resposta" }, 502, origem);
    saida = { tipo: "conversa", resposta: texto };
  } else {
    const motivo = sqlSuspeito(plano.sql);
    if (motivo) return json({ erro: `consulta recusada: ${motivo}` }, 422, origem);
    plano.tipo = "consulta";
    if (!GRAFICOS.includes(plano.grafico)) plano.grafico = "tabela";
    /* O enum do schema não aceita string vazia, então "sem unidade" viaja como "nenhuma"
       e volta a ser "" aqui — senão o rótulo do gráfico sairia "12 nenhuma". */
    if (plano.unidade === "nenhuma") plano.unidade = "";
    plano.frase = String(plano.frase ?? "").trim().slice(0, 400);
    saida = plano;
  }
  if (chave) depois(ctx, kv.put(chave, JSON.stringify(saida), { expirationTtl: CACHE_PLANO_TTL }));
  return json({ ...saida, modelo: p.modelo, reserva, rodadas }, 200, origem);
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
  let cfg;
  try {
    cfg = resolverProvedor(env);
  } catch (e) {
    return json({ ok: false, etapa: "configuracao", erro: String(e.message) }, 500, origem);
  }

  const dia = await lerDia(env);
  const base = {
    provedor: cfg.nome,
    modelo: cfg.p.modelo,
    kv: !!env.CONTADORES,
    gasto_hoje: env.CONTADORES ? dia.perguntas : null,
    limite_diario: Number(env.LIMITE_DIARIO ?? LIMITE_DIARIO_PADRAO),
    prazo_tentativa_ms: Number(env.PRAZO_TENTATIVA_MS ?? PRAZO_POR_TENTATIVA_PADRAO),
    prazo_total_ms: Number(env.PRAZO_TOTAL_MS ?? PRAZO_TOTAL_PADRAO),
    reservas: String(env.MODELOS_RESERVA ?? "").split(",").map(x => x.trim()).filter(Boolean),
    atraso_reserva_ms: Number(env.ATRASO_RESERVA_MS ?? ATRASO_RESERVA_PADRAO),
    prazo_consulta_ms: Number(env.PRAZO_CONSULTA_MS ?? PRAZO_CONSULTA_PADRAO),
    rodadas_consulta: Number(env.RODADAS_CONSULTA ?? RODADAS_PADRAO),
    exemplos_no_prompt: Number(env.EXEMPLOS_NO_PROMPT ?? EXEMPLOS_NO_PROMPT_PADRAO),
    disjuntor: {
      falhas_para_pausar: Number(env.DISJUNTOR_FALHAS ?? DISJUNTOR_FALHAS_PADRAO),
      pausa_ms: Number(env.DISJUNTOR_PAUSA_MS ?? DISJUNTOR_PAUSA_PADRAO),
      falhas_seguidas: dia.falhas_seguidas,
      pausado_ate: dia.pausa_ate > Date.now() ? new Date(dia.pausa_ate).toISOString() : null,
    },
    /* O que a cota do provedor gastou hoje: chamadas por modelo e desfecho (200, 503, 429,
       "tempo", "perdeu"), tokens por modelo — "raciocinio" é o thoughtsTokenCount somado —,
       quantas vezes a reserva atrasada disparou e quantas venceu, e os planos que saíram do cache. */
    hoje: { perguntas: dia.perguntas, do_cache: dia.do_cache, chamadas: dia.chamadas, tokens: dia.tokens,
            reserva: dia.reserva },
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
  async fetch(req, env, ctx) {
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
    const bloqueio = await limitePorMinuto(env, ip);
    if (bloqueio) return json({ erro: bloqueio }, 429, origem);

    try {
      /* ?modelo= é diagnóstico: mede um modelo específico sem um ciclo de deploy. */
      const forcado = url.searchParams.get("modelo") || undefined;
      if (url.pathname === "/consulta") return await rotaConsulta(req, env, ctx, origem, forcado);
      return json({ erro: "rota inexistente" }, 404, origem);
    } catch (e) {
      const status = [429, 503].includes(e.status) ? e.status : 500;
      const mensagem = {
        429: "A cota diária de IA do free tier acabou — ela reinicia à meia-noite no "
           + "Pacífico. As perguntas prontas continuam funcionando: elas rodam SQL local "
           + "e não dependem do modelo.",
        503: "A IA gratuita não respondeu a tempo. As perguntas prontas respondem na hora, "
           + "sem ela.",
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
