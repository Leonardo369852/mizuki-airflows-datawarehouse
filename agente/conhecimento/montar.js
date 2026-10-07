/**
 * Monta os textos do agente a partir de agente/conhecimento/*.json: o prompt do /consulta e do
 * /narrar (no Worker), as respostas fixas e o plano das perguntas prontas (na página).
 *
 * Uma fonte só. Antes, o mesmo conhecimento vivia em cinco lugares — SCHEMA, QUEM_SOU e
 * CONTEXTO_NARRACAO no Worker, SUGESTOES e PROMPT_SQL na página — e eles já discordavam: o
 * período estava errado em dois, e o PROMPT_SQL não sabia de marca nem de estado.
 *
 * Sem dependência e sem importar JSON: recebe os dados prontos, para rodar igual no Worker (que
 * importa os JSON no build), no navegador (que os busca como arquivo) e no Node (nos testes).
 */

/** Troca {chave} pelo texto do fato. Chave que não existe é erro, nunca texto vazio: um número
    que some do prompt sem aviso é exatamente o tipo de defeito que esta base existe para evitar. */
export function preencher(texto, fatos) {
  return String(texto ?? "").replace(/\{([a-z_]+)\}/g, (_, chave) => {
    if (!fatos?.[chave]) throw new Error(`fato desconhecido: {${chave}}`);
    return fatos[chave].texto;
  });
}

const juntar = (x) => (Array.isArray(x) ? x.join("\n") : String(x ?? ""));

/** O SQL de um plano: nos JSON ele fica em linhas, para ser legível no diff. */
export const sqlDe = (plano) => juntar(plano?.sql);

/** Um exemplo pronto para usar: SQL inteiro e avisos com os fatos preenchidos. */
export function planoDoExemplo(exemplo, fatos) {
  const p = exemplo.plano;
  if (p.tipo === "conversa") return { tipo: "conversa", resposta: preencher(p.resposta, fatos) };
  return {
    ...p,
    sql: sqlDe(p),
    titulo: preencher(p.titulo, fatos),
    aviso: preencher(p.aviso, fatos),
    serie: p.serie ?? "",
    resposta: "",
  };
}

/** O schema que o modelo vê: tabelas, métricas e problemas da fonte. */
export function semanticaEmTexto(sem, fatos) {
  const p = (t) => preencher(t, fatos);
  const out = [p(sem.banco).trim(), ""];
  for (const t of sem.tabelas) {
    out.push(`TABELA ${t.nome}${t.descricao ? ` — ${t.descricao}` : ""}`);
    if (t.colunas.some((c) => c[2])) {
      if (t.medidas) out.push("  Chaves:");
      for (const [nome, tipo, nota] of t.colunas) {
        out.push(`    ${nome.padEnd(18)} ${tipo.padEnd(6)} ${nota ? p(nota) : ""}`.trimEnd());
      }
    } else {
      out.push("  " + t.colunas.map(([nome, tipo]) => `${nome} ${tipo}`).join(", "));
    }
    if (t.medidas) {
      out.push("  Medidas (TODAS aditivas — sempre agregue com SUM, nunca com AVG):",
               "    " + t.medidas.join(", "));
    }
    for (const nota of t.notas ?? []) out.push("  " + p(nota));
    out.push("");
  }
  out.push("MÉTRICAS — use exatamente estas fórmulas");
  for (const m of sem.metricas) {
    out.push(`  ${m.nome}:`, `    ${m.formula}`);
    if (m.nota) out.push(`    ${p(m.nota)}`);
  }
  out.push("", "  " + p(sem.regra_das_metricas), "", "PROBLEMAS DA FONTE — considere em toda resposta");
  sem.problemas.forEach((texto, i) => out.push(`  ${i + 1}. ${p(texto)}`));
  return "\n" + out.join("\n") + "\n";
}

export function regrasSqlEmTexto(sem) {
  return "\n" + juntar(sem.regras_sql) + "\n";
}

/** A identidade em duas linhas: saudação, "quem é você" e "como funciona" saem prontas na
    página, sem IA, então o prompt só precisa do bastante para o caso de uma escapar. */
export function resumoEmTexto(ide, fatos) {
  return "\nQUEM VOCÊ É\n" + ide.resumo.map((t) => preencher(t, fatos)).join("\n") + "\n";
}

/** O que o grão não sustenta. Fica no prompt mesmo com o roteador na página, porque é o que
    impede o modelo de inventar uma consulta para uma pergunta que escapou dele. */
export function limitesEmTexto(ide, fatos) {
  return [
    "",
    "O que você NÃO consegue responder, por causa do grão agregado — diga com franqueza quando for o caso:",
    ...ide.nao_responde.map((n) => `  · ${preencher(n.texto, fatos)}${n.genie ? "; o Genie do projeto responde" : ""}`),
    "Nunca finja que consegue. Nunca invente uma consulta para uma dessas: responda em \"conversa\", diga o que falta e por quê.",
    "",
  ].join("\n");
}

export function roteamentoEmTexto(ide) {
  return "\n" + juntar(ide.roteamento) + "\n";
}

export function contextoNarracaoEmTexto(ide, fatos) {
  const n = ide.narracao;
  return ["", ...n.contexto.map((t) => preencher(t, fatos)), "",
          "Ressalvas da fonte, cite quando afetarem o número em questão:",
          ...n.ressalvas.map((t) => "- " + preencher(t, fatos)), ""].join("\n");
}

export function regrasNarracaoEmTexto(ide) {
  return ["", ide.narracao.papel, "", ...ide.narracao.regras, ""].join("\n");
}

/** O prompt fixo do /consulta, na ordem em que vai ao modelo. Os exemplos escolhidos para a
    pergunta e a conversa entram depois, no fim: o começo igual entre perguntas é o que o
    provedor consegue reaproveitar. */
export function promptConsulta({ semantica, identidade, fatos }) {
  return semanticaEmTexto(semantica, fatos) + resumoEmTexto(identidade, fatos)
       + limitesEmTexto(identidade, fatos) + roteamentoEmTexto(identidade) + regrasSqlEmTexto(semantica);
}

/** O prompt fixo do /narrar: só o que a narração usa — nada de colunas nem regras de SQL. */
export function promptNarracao({ identidade, fatos }) {
  return contextoNarracaoEmTexto(identidade, fatos) + regrasNarracaoEmTexto(identidade);
}

/** Exemplos pergunta → plano, no formato que o modelo devolve. */
export function exemplosEmTexto(lista, fatos) {
  if (!lista?.length) return "";
  const blocos = lista.map((ex) => {
    const p = planoDoExemplo(ex, fatos);
    const plano = p.tipo === "conversa"
      ? { tipo: "conversa", resposta: p.resposta }
      : { tipo: "consulta", sql: p.sql.replace(/\s+/g, " "), grafico: p.grafico, x: p.x, y: p.y,
          unidade: p.unidade || "nenhuma", titulo: p.titulo, aviso: p.aviso };
    return `Pergunta: ${ex.pergunta}\nPlano: ${JSON.stringify(plano)}`;
  });
  return "\nEXEMPLOS — perguntas parecidas com a de agora, e o plano certo para cada uma\n"
       + blocos.join("\n\n") + "\n";
}

/** Uma resposta fixa (saudação, ajuda, fora do grão), com os fatos preenchidos. */
export function respostaFixa(ide, fatos, chave, sub) {
  const r = sub ? ide.respostas[chave]?.[sub] : ide.respostas[chave];
  if (typeof r !== "string") throw new Error(`resposta fixa desconhecida: ${chave}${sub ? "." + sub : ""}`);
  return preencher(r, fatos);
}
