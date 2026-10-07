// Ponte entre o avaliar.py e o código da página: roda o roteador (e o que mais a página roda
// sem IA) exatamente como ele é, sem cópia em Python. Lê um pedido JSON por linha e responde
// uma linha.
//   {"op": "iniciar", "dims": {...}}          cria o roteador com as dimensões do banco
//   {"op": "rotear", "pergunta", "historico"}  a rota e o plano ou o texto
import { createInterface } from "node:readline";
import { readFileSync } from "node:fs";

const raiz = new URL("../", import.meta.url);
const ler = (p) => JSON.parse(readFileSync(new URL(p, raiz), "utf8"));
const { criarRoteador } = await import(new URL("roteador.js", raiz));
const conhecimento = {
  identidade: ler("conhecimento/identidade.json"), exemplos: ler("conhecimento/exemplos.json").exemplos,
  apelidos: ler("conhecimento/apelidos.json"), fatos: ler("conhecimento/fatos.json").fatos,
};
let roteador = null;

const ops = {
  iniciar: ({ dims }) => { roteador = criarRoteador(conhecimento, dims); return { ok: true }; },
  rotear: ({ pergunta, historico }) => {
    const t0 = performance.now();
    const r = roteador.rotear(pergunta, { historico: historico ?? [] });
    return { ...r, ms: performance.now() - t0 };
  },
};

for await (const linha of createInterface({ input: process.stdin })) {
  if (!linha.trim()) continue;
  let resposta;
  try {
    const pedido = JSON.parse(linha);
    resposta = ops[pedido.op](pedido);
  } catch (e) {
    resposta = { erro: String(e?.stack ?? e) };
  }
  process.stdout.write(JSON.stringify(resposta) + "\n");
}
