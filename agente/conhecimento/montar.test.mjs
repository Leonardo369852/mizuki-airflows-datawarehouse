// node --test "agente/**/*.test.mjs"
// O que conferir.py não alcança, porque é montagem e não dado: toda {chave} vira texto, os
// exemplos viram planos utilizáveis e o prompt fica dentro do orçamento — teto e piso.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import * as m from "./montar.js";

const bruto = (n) => readFileSync(new URL(`./${n}.json`, import.meta.url), "utf8");
const ler = (n) => JSON.parse(bruto(n));
const semantica = ler("semantica"), identidade = ler("identidade");
const exemplos = ler("exemplos").exemplos, fatos = ler("fatos").fatos;
const conh = { semantica, identidade, fatos };

test("chave de fato desconhecida estoura, em vez de sumir do texto", () => {
  assert.throws(() => m.preencher("{nao_existe}", fatos), /fato desconhecido/);
});

test("nenhuma {chave} de fato sobra em texto montado", () => {
  const respostas = Object.entries(identidade.respostas).flatMap(([k, v]) =>
    typeof v === "string" ? [m.respostaFixa(identidade, fatos, k)]
                          : Object.keys(v).map((sub) => m.respostaFixa(identidade, fatos, k, sub)));
  /* A regra da frase e as frases dos exemplos ficam de fora de propósito: as chaves delas são
     marcadores que a página preenche com o resultado, não fatos. */
  const planos = exemplos.map((ex) => m.planoDoExemplo(ex, fatos));
  const tudo = [m.semanticaEmTexto(semantica, fatos), m.resumoEmTexto(identidade, fatos),
                m.limitesEmTexto(identidade, fatos), m.roteamentoEmTexto(identidade), m.regrasSqlEmTexto(semantica),
                ...planos.flatMap((p) => [p.titulo ?? "", p.aviso ?? "", p.resposta ?? ""]), ...respostas].join("\n");
  assert.doesNotMatch(tudo, /\{[a-z_]+\}/);
});

test("o prompt do /consulta ensina a frase com marcadores, e os exemplos trazem a deles", () => {
  const prompt = m.promptConsulta(conh);
  assert.match(prompt, /FRASE/);
  assert.match(prompt, /\{total\.col\}/);
  const texto = m.exemplosEmTexto(exemplos.slice(0, 3), fatos);
  assert.match(texto, /"frase":"[^"]*\{maior\.rotulo\}/);
});

test("o prompt do /consulta cabe no orçamento", () => {
  const n = m.promptConsulta(conh).length;
  // Teto: acima disto o prompt voltou a inchar — cada pergunta paga por ele inteiro.
  assert.ok(n <= 13000, `prompt do /consulta com ${n} caracteres, teto 13.000`);
  // Piso: abaixo disto uma seção sumiu sem ninguém notar (a semântica sozinha passa de 6 mil).
  assert.ok(n >= 9000, `prompt do /consulta com ${n} caracteres, piso 9.000`);
});

test("cada exemplo vira um plano que a página e o modelo entendem", () => {
  for (const ex of exemplos) {
    const p = m.planoDoExemplo(ex, fatos);
    if (p.tipo === "conversa") {
      assert.ok(p.resposta.length > 20, ex.pergunta);
      continue;
    }
    assert.match(p.sql, /\bLIMIT \d+/, ex.pergunta);
    for (const campo of ["grafico", "x", "y", "titulo"]) assert.ok(p[campo], `${ex.pergunta}: ${campo}`);
  }
  assert.equal(exemplos.filter((e) => e.chip).length, 6, "as seis perguntas prontas da página");
});

test("o período vem do export, nunca digitado", () => {
  assert.ok(m.promptConsulta(conh).includes(fatos.periodo.texto));
  for (const n of ["semantica", "identidade", "exemplos"]) {
    assert.doesNotMatch(bruto(n), /\b[a-z]{3}\/20\d\d a [a-z]{3}\/20\d\d\b/, `${n}.json digita um período`);
  }
});
