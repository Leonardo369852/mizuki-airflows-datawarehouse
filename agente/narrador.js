/**
 * Narrador: o texto da resposta, escrito em código. Todo número sai das linhas da consulta.
 *
 * O /consulta devolve, junto com o SQL, uma `frase` com marcadores no lugar dos números —
 * "Os {n} aeroportos do estado somam {total.voos} partidas" —, escrita antes de o resultado
 * existir. Aqui ela é preenchida com os valores da consulta. Antes, uma segunda chamada à IA
 * (/narrar) recebia as linhas e escrevia o texto: somou as 16 linhas de São Paulo como 322.327
 * quando eram 317.327, e citava ressalvas que não afetavam o número.
 *
 * Sem frase, com marcador que não fecha, ou com algum número que não saiu da consulta, o texto
 * vem de `frase()`, que narra sozinha os formatos comuns. Sem dependência e sem DOM, para rodar
 * igual no navegador e no Node (testes e avaliação).
 */

export const ehNum = (v) => typeof v === "number" && Number.isFinite(v);
const nf = (n) => n.toLocaleString("pt-BR");
const pf = (n, d = 1) => n.toLocaleString("pt-BR", { minimumFractionDigits: d, maximumFractionDigits: d });
const COORDENADA = /latitude|longitude/;

/** Como a página escreve um valor: "73,8%", "23,6 min", "1.024 km", "147.976". */
export function formatar(v, unidade) {
  if (!ehNum(v)) return String(v ?? "—");
  if (unidade === "%") return pf(v, 1) + "%";
  if (unidade === "min") return pf(v, 1) + " min";
  if (unidade === "km") return nf(Math.round(v)) + " km";
  return Number.isInteger(v) || unidade === "voos" ? nf(Math.round(v)) : pf(v, 1);
}

/** A coluna da medida: a do eixo que o gráfico usa como valor, nunca coordenada. */
export function colunaMedida(plano, linhas) {
  const l = linhas[0] ?? {};
  for (const k of [plano.y, plano.x]) if (k in l && ehNum(l[k]) && !COORDENADA.test(k)) return k;
  return Object.keys(l).find((k) => ehNum(l[k]) && !COORDENADA.test(k)) ?? null;
}

/** A coluna que nomeia a linha: o eixo de texto, senão a primeira coluna de texto que não é ICAO. */
export function colunaRotulo(plano, linhas) {
  const l = linhas[0] ?? {};
  const textos = Object.keys(l).filter((k) => typeof l[k] === "string");
  for (const k of [plano.y, plano.x]) if (textos.includes(k)) return k;
  return textos.find((k) => k !== "icao") ?? textos[0] ?? null;
}

/** A unidade de uma coluna: a do plano para a medida; pelo nome, para as outras. */
export function unidadeDe(col, plano, linhas) {
  const temUnidade = ["%", "min", "km"].includes(plano.unidade);
  if (col === colunaMedida(plano, linhas) && temUnidade) return plano.unidade;
  /* No halteres os dois eixos são a mesma medida em dois estados (saindo, chegando). */
  if (plano.grafico === "halteres" && (col === plano.x || col === plano.y) && temUnidade) return plano.unidade;
  if (/otp|taxa|pct|percent|pontual/.test(col)) return "%";
  if (/atraso|duracao|minut/.test(col)) return "min";
  if (/km|distanc/.test(col)) return "km";
  return "";
}

/* Soma só faz sentido para contagem: somar taxas ou médias dá um número sem significado. */
const somavel = (col, plano, linhas) => !unidadeDe(col, plano, linhas)
  && linhas.every((l) => l[col] === null || l[col] === undefined || (ehNum(l[col]) && Number.isInteger(l[col])));

/**
 * Preenche os marcadores. "maior" e "menor" são as linhas de maior e menor MEDIDA; "primeiro"
 * e "ultimo", a primeira e a última na ordem do resultado. Devolve null se algum marcador não
 * fecha — coluna que não existe, soma de taxa, rótulo sem coluna de texto.
 *   {n}  {total.col}  {maior.col}  {maior.rotulo}  {menor.*}  {primeiro.*}  {ultimo.*}  {col}
 */
export function preencherFrase(frase, plano, linhas) {
  if (typeof frase !== "string" || !frase.trim() || !linhas.length) return null;
  const medida = colunaMedida(plano, linhas);
  const rotulo = colunaRotulo(plano, linhas);
  const ordenadas = medida ? linhas.filter((l) => ehNum(l[medida])) : [];
  const porMedida = (sinal) => ordenadas.reduce((a, b) => (sinal * (b[medida] - a[medida]) > 0 ? b : a), ordenadas[0]);
  const linha = { primeiro: linhas[0], ultimo: linhas.at(-1),
                  maior: ordenadas.length ? porMedida(1) : null, menor: ordenadas.length ? porMedida(-1) : null };
  let falhou = false;
  const texto = frase.replace(/\{([a-z_0-9]+)(?:\.([a-z_0-9]+))?\}/g, (marca, a, b) => {
    let valor, col;
    if (a === "n" && !b) {
      valor = linhas.length;
      col = null;
    } else if (a === "total" && b) {
      if (!(b in linhas[0]) || !somavel(b, plano, linhas)) { falhou = true; return marca; }
      valor = linhas.reduce((s, l) => s + (ehNum(l[b]) ? l[b] : 0), 0);
      col = b;
    } else if (b && a in linha) {
      const l = linha[a];
      col = b === "rotulo" ? rotulo : b;
      if (!l || !col || !(col in l)) { falhou = true; return marca; }
      valor = l[col];
    } else if (!b && a in linhas[0]) {
      valor = linhas[0][a];
      col = a;
    } else {
      falhou = true;
      return marca;
    }
    if (valor === null || valor === undefined) { falhou = true; return marca; }
    return ehNum(valor) ? formatar(valor, col ? unidadeDe(col, plano, linhas) : "") : String(valor);
  });
  return falhou ? null : texto.replace(/\s+/g, " ").trim();
}

/** O texto sem frase do modelo: os formatos comuns, narrados com os números da própria tabela. */
export function frase(plano, linhas) {
  if (!linhas.length) return "A consulta não encontrou nenhuma linha.";
  const medida = colunaMedida(plano, linhas);
  const rotulo = colunaRotulo(plano, linhas);
  if (!medida) return `${nf(linhas.length)} ${linhas.length === 1 ? "linha" : "linhas"}. O SQL e a tabela estão abaixo.`;
  const un = unidadeDe(medida, plano, linhas);
  const comUnidade = (v, col = medida) => {
    const u = unidadeDe(col, plano, linhas);
    return formatar(v, u) + (!u && plano.unidade === "voos" && col === medida ? " voos" : "");
  };
  const titulo = String(plano.titulo || "").trim();

  if (linhas.length === 1) {
    const l = linhas[0];
    const extra = Object.keys(l).filter((k) => k !== medida && ehNum(l[k]) && !COORDENADA.test(k))
      .map((k) => `${comUnidade(l[k], k)} ${k.replace(/_/g, " ")}`);
    const nome = rotulo && l[rotulo] ? `${l[rotulo]}: ` : titulo ? `${titulo}: ` : "";
    return `${nome}${comUnidade(l[medida])}${extra.length ? ` (${extra.join(", ")})` : ""}.`;
  }

  const comMedida = linhas.filter((l) => ehNum(l[medida]));
  const maior = comMedida.reduce((a, b) => (b[medida] > a[medida] ? b : a));
  const menor = comMedida.reduce((a, b) => (b[medida] < a[medida] ? b : a));
  const nome = (l) => (rotulo ? l[rotulo] : "");

  if (plano.grafico === "linha" && rotulo) {
    return `${titulo || medida}: de ${comUnidade(menor[medida])} em ${nome(menor)} a ${comUnidade(maior[medida])} `
      + `em ${nome(maior)}, entre ${nome(linhas[0])} e ${nome(linhas.at(-1))}.`;
  }
  if (plano.grafico === "halteres" && rotulo && ehNum(linhas[0][plano.x]) && ehNum(linhas[0][plano.y])) {
    const l = linhas[0];
    return `No topo, ${nome(l)}: ${comUnidade(l[plano.x], plano.x)} em ${plano.x.replace(/_/g, " ")} contra `
      + `${comUnidade(l[plano.y], plano.y)} em ${plano.y.replace(/_/g, " ")}. São ${nf(linhas.length)} linhas — `
      + "a tabela está abaixo.";
  }
  const topo = rotulo
    ? [linhas[0], linhas[1], linhas[2]].filter(Boolean).map((l, i) =>
        i === 0 ? `${nome(l)}, com ${comUnidade(l[medida])}` : `${nome(l)} (${comUnidade(l[medida])})`)
    : [];
  const abre = topo.length
    ? `No topo, ${topo[0]}${topo.length > 1 ? `, seguido de ${topo.slice(1).join(" e ")}` : ""}.`
    : `Maior valor: ${comUnidade(maior[medida])}.`;
  const [artigo, coisas] = PLURAIS[rotulo] ?? ["As", "linhas"];
  const soma = !un && somavel(medida, plano, linhas)
    ? ` ${artigo} ${nf(linhas.length)} ${coisas} somam ${comUnidade(linhas.reduce((s, l) => s + (ehNum(l[medida]) ? l[medida] : 0), 0))}.`
    : ` São ${nf(linhas.length)} ${coisas}.`;
  return abre + soma;
}

/* O rótulo vira o substantivo da soma: "Os 16 aeroportos somam", não "as 16 linhas". */
const PLURAIS = {
  aeroporto: ["Os", "aeroportos"], local: ["Os", "aeródromos"], empresa: ["As", "empresas"],
  estado: ["Os", "estados"], mes: ["Os", "meses"], destino: ["Os", "destinos"], rota: ["As", "rotas"],
  periodo: ["Os", "períodos"], grupo: ["Os", "grupos"], origem: ["As", "origens"], municipio: ["Os", "municípios"],
};

// ─── Verificador de números ───────────────────────────────────────────────────
// O mesmo critério de agente/avaliacao/avaliar.py: formato brasileiro, tolerância de meia
// unidade da última casa escrita ("73,8" cobre 73,75 a 73,85; "317 mil", 316.500 a 317.500).

const NUMERO = /(?<![\p{L}\p{N}_/.,])(\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:,\d+)?)(?:\s*(mil|milh(?:ão|ões|ao|oes)|bilh(?:ão|ões|ao|oes))(?![\p{L}]))?(?![\p{L}\p{N}_/])/giu;

function lerNumero(bruto, escala = "") {
  const [inteiro, decimais = ""] = bruto.replace(/\./g, "").split(",");
  const valor = Number(decimais ? `${inteiro}.${decimais}` : inteiro);
  const e = escala.toLowerCase();
  const fator = e === "mil" ? 1e3 : e.startsWith("milh") ? 1e6 : e ? 1e9 : 1;
  return { valor: valor * fator, tol: 0.5 * 10 ** -decimais.length * fator + 1e-9 };
}

export function numerosEm(texto) {
  return [...String(texto ?? "").matchAll(NUMERO)].map((m) => ({ ...lerNumero(m[1], m[2] ?? ""), trecho: m[0].trim() }));
}

/** Os números que um texto pode citar: células e somas de coluna do resultado, a contagem de
    linhas, os números do SQL e da pergunta, e os fatos da base de conhecimento. */
export function numerosConhecidos(plano, linhas, { fatos = {}, pergunta = "" } = {}) {
  const vals = [linhas.length];
  for (const l of linhas) {
    for (const v of Object.values(l)) {
      if (ehNum(v)) vals.push(v);
      else if (typeof v === "string") vals.push(...numerosEm(v).map((n) => n.valor));
    }
  }
  if (linhas.length > 1) {
    for (const k of Object.keys(linhas[0])) {
      if (linhas.some((l) => ehNum(l[k]))) vals.push(linhas.reduce((s, l) => s + (ehNum(l[k]) ? l[k] : 0), 0));
    }
  }
  for (const t of [plano?.sql, plano?.titulo, plano?.aviso, pergunta]) vals.push(...numerosEm(t).map((n) => n.valor));
  for (const f of Object.values(fatos)) if (ehNum(f?.valor)) vals.push(f.valor);
  return vals;
}

/** Os números do texto que não estão em lugar nenhum de onde poderiam ter saído. */
export function desconhecidos(texto, conhecidos) {
  return numerosEm(texto)
    .filter(({ valor, tol }) => !(tol < 0.51 && Number.isInteger(valor) && valor >= 0 && valor <= 31))
    .filter(({ valor, tol }) => !conhecidos.some((k) => Math.abs(valor - k) <= tol))
    .map((n) => n.trecho);
}

/**
 * O texto da resposta de uma consulta: a frase do modelo preenchida, se ela fecha e não traz
 * número de fora; senão, a frase do código.
 */
export function narrar(plano, linhas, { fatos = {}, pergunta = "" } = {}) {
  if (plano?.frase) {
    const texto = preencherFrase(plano.frase, plano, linhas);
    if (texto) {
      const fora = desconhecidos(texto, numerosConhecidos(plano, linhas, { fatos, pergunta }));
      if (!fora.length) return { texto, origem: "modelo" };
      return { texto: frase(plano, linhas), origem: "codigo", descartada: texto, desconhecidos: fora };
    }
  }
  return { texto: frase(plano, linhas), origem: "codigo" };
}

/**
 * A resposta em prosa do modelo ("o que isso significa?"): só pode citar números que já
 * apareceram na conversa, na pergunta ou nos fatos. Se cita outro, é conta de cabeça — e a
 * resposta não vai para a tela.
 */
export function conferirConversa(texto, { historico = [], fatos = {}, pergunta = "" } = {}) {
  const conhecidos = [];
  for (const h of historico) {
    for (const l of h.amostra ?? []) for (const v of Object.values(l)) if (ehNum(v)) conhecidos.push(v);
    if (ehNum(h.total)) conhecidos.push(h.total);
    for (const t of [h.pergunta, h.resposta, h.sql]) conhecidos.push(...numerosEm(t).map((n) => n.valor));
  }
  conhecidos.push(...numerosConhecidos(null, [], { fatos, pergunta }));
  const fora = desconhecidos(texto, conhecidos);
  return { ok: !fora.length, desconhecidos: fora };
}
