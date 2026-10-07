/**
 * Medidor da avaliação. Só existe em teste local, sob `wrangler dev` — nunca é publicado.
 *
 * Roda o Worker de verdade e anota cada chamada que ele faz ao provedor: modelo, status,
 * tempo até os cabeçalhos, tempo total e o usageMetadata (tokens de entrada, de raciocínio e
 * de saída). Não muda uma linha do Worker: embrulha o fetch global e acrescenta
 * GET /__medidas, que devolve o que foi anotado desde a última leitura e zera a lista.
 *
 * Existe porque o contador do KV vê PERGUNTAS, e a cota do provedor gasta CHAMADAS. A
 * diferença entre as duas — a reserva atrasada, as rodadas de insistência, a fila percorrida
 * na narração — só aparece daqui.
 */

const PROVEDORES = ["generativelanguage.googleapis.com", "api.anthropic.com"];

export function medir(worker) {
  const anotadas = [];
  const pendentes = new Set();
  const original = globalThis.fetch.bind(globalThis);

  globalThis.fetch = async (entrada, init) => {
    const url = String(entrada instanceof Request ? entrada.url : entrada);
    if (!PROVEDORES.some((p) => url.includes(p))) return original(entrada, init);

    const nota = {
      modelo: decodeURIComponent(url.match(/models\/([^:?]+)/)?.[1] ?? "?"),
      stream: url.includes("streamGenerateContent"),
      status: null,
      ms_cabecalho: null,
      ms_total: null,
      desfecho: "pendente",
      uso: null,
      erro: null,
    };
    const inicio = Date.now();
    anotadas.push(nota);

    /* Quem perde a corrida da reserva é abortado antes dos cabeçalhos: cai aqui. A chamada
       já saiu, então conta como chamada ao provedor mesmo sem resposta. */
    let resposta;
    try {
      resposta = await original(entrada, init);
    } catch (e) {
      nota.ms_total = Date.now() - inicio;
      nota.desfecho = e?.name === "AbortError" ? "abortada" : "rede";
      throw e;
    }
    nota.status = resposta.status;
    nota.ms_cabecalho = Date.now() - inicio;

    /* O corpo é do Worker. Uma cópia (tee) é lida aqui em paralelo, sem atrasar quem usa. */
    const ler = (fluxo, aoTerminar) => {
      const leitura = new Response(fluxo).text()
        .then(aoTerminar)
        .catch(() => { nota.desfecho = "abortada"; })
        .finally(() => { nota.ms_total = Date.now() - inicio; pendentes.delete(leitura); });
      pendentes.add(leitura);
    };

    if (!resposta.body) {
      nota.desfecho = resposta.ok ? "ok" : "erro";
      nota.ms_total = nota.ms_cabecalho;
      return resposta;
    }
    const [doWorker, daqui] = resposta.body.tee();
    ler(daqui, (texto) => {
      if (resposta.ok) {
        nota.uso = usoDe(texto, nota.stream);
        nota.desfecho = "ok";
      } else {
        nota.erro = texto.slice(0, 300);
        nota.desfecho = "erro";
      }
    });
    return new Response(doWorker, {
      status: resposta.status, statusText: resposta.statusText, headers: resposta.headers,
    });
  };

  return {
    async fetch(req, env, ctx) {
      if (new URL(req.url).pathname === "/__medidas") {
        await Promise.allSettled([...pendentes]);   /* espera as leituras de corpo em curso */
        return Response.json(anotadas.splice(0));
      }
      return worker.fetch(req, env, ctx);
    },
  };
}

/* No streaming, cada pedaço do SSE traz um usageMetadata acumulado; vale o último. */
function usoDe(texto, stream) {
  if (!stream) {
    try { return JSON.parse(texto).usageMetadata ?? null; } catch { return null; }
  }
  let ultimo = null;
  for (const linha of texto.split("\n")) {
    if (!linha.startsWith("data:")) continue;
    try {
      const j = JSON.parse(linha.slice(5));
      if (j.usageMetadata) ultimo = j.usageMetadata;
    } catch { /* pedaço que não é JSON completo */ }
  }
  return ultimo;
}
