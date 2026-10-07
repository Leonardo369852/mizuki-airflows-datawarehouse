// Ponte entre o avaliar.py e o código da página: roda o roteador e o narrador exatamente como
// eles são, sem cópia em Python. Lê um pedido JSON por linha e responde uma linha.
//   {"op": "iniciar", "dims": {...}}                    cria o roteador com as dimensões do banco
//   {"op": "rotear", "pergunta", "historico"}            a rota e o plano ou o texto
//   {"op": "narrar", "plano", "linhas", "pergunta"}      o texto que a página mostra para o resultado
//   {"op": "conversa", "resposta", "historico", "pergunta"}  a prosa do modelo, depois do verificador
import { createInterface } from "node:readline";
import { readFileSync } from "node:fs";

const raiz = new URL("../", import.meta.url);
const ler = (p) => JSON.parse(readFileSync(new URL(p, raiz), "utf8"));
const { criarRoteador } = await import(new URL("roteador.js", raiz));
const narrador = await import(new URL("narrador.js", raiz));
const montar = await import(new URL("conhecimento/montar.js", raiz));
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
  narrar: ({ plano, linhas, pergunta }) => narrador.narrar(plano, linhas, { fatos: conhecimento.fatos, pergunta }),
  /* O mesmo texto de troca que a página mostra quando a prosa traz número de fora. */
  conversa: ({ resposta, historico, pergunta }) => {
    const c = narrador.conferirConversa(resposta, { historico: historico ?? [], fatos: conhecimento.fatos, pergunta });
    return { ...c, texto: c.ok ? resposta
      : montar.respostaFixa(conhecimento.identidade, conhecimento.fatos, "conversa_descartada") };
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
