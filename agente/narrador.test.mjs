// node --test "agente/**/*.test.mjs"
import { test } from "node:test";
import assert from "node:assert/strict";
import { narrar, preencherFrase, frase, desconhecidos, numerosConhecidos, conferirConversa, formatar } from "./narrador.js";

/* As 16 partidas por aeroporto do estado de SP, como estão nos Parquet: somam 317.327. */
const SP = [["GUARULHOS", 147976], ["SÃO PAULO", 95707], ["CAMPINAS", 60387], ["SÃO JOSÉ DO RIO PRETO", 4555],
  ["RIBEIRÃO PRETO", 4261], ["PRESIDENTE PRUDENTE", 1236], ["ARAÇATUBA", 603], ["SÃO JOSÉ DOS CAMPOS", 563],
  ["BAURU", 489], ["JUNDIAÍ", 388], ["MARÍLIA", 324], ["ARARAQUARA", 268], ["SÃO CARLOS", 236], ["FRANCA", 142],
  ["BARRETOS", 138], ["SOROCABA", 54]].map(([aeroporto, voos]) => ({ aeroporto, voos }));
const PLANO_SP = { tipo: "consulta", grafico: "barra_horizontal", x: "voos", y: "aeroporto", unidade: "voos",
                   titulo: "Partidas por aeroporto — estado de SP", aviso: "", sql: "SELECT ... LIMIT 40",
                   frase: "Os {n} aeroportos do estado de SP somam {total.voos} partidas; o maior é {maior.rotulo}, com {maior.voos}." };

test("formata como a página", () => {
  assert.equal(formatar(73.79378, "%"), "73,8%");
  assert.equal(formatar(23.63, "min"), "23,6 min");
  assert.equal(formatar(1024.09, "km"), "1.024 km");
  assert.equal(formatar(317327, "voos"), "317.327");
});

test("o caso do print: o total sai da soma das linhas, 317.327", () => {
  const n = narrar(PLANO_SP, SP);
  assert.equal(n.origem, "modelo");
  assert.equal(n.texto, "Os 16 aeroportos do estado de SP somam 317.327 partidas; o maior é GUARULHOS, com 147.976.");
});

test("número que não saiu da consulta derruba a frase do modelo", () => {
  const n = narrar({ ...PLANO_SP, frase: "Os {n} aeroportos somam 322.327 partidas; o maior é {maior.rotulo}." }, SP);
  assert.equal(n.origem, "codigo");
  assert.deepEqual(n.desconhecidos, ["322.327"]);
  assert.match(n.texto, /317\.327/, "a frase do código soma certo");
  assert.doesNotMatch(n.texto, /322/);
});

test("marcador que não fecha devolve null, e a narração cai na frase do código", () => {
  assert.equal(preencherFrase("{maior.coluna_que_nao_existe}", PLANO_SP, SP), null);
  const taxas = [{ empresa: "A", taxa: 3.5 }, { empresa: "B", taxa: 2.1 }];
  const plano = { grafico: "barra_horizontal", x: "taxa", y: "empresa", unidade: "%" };
  assert.equal(preencherFrase("Somam {total.taxa}.", plano, taxas), null, "taxa não se soma");
  assert.equal(narrar({ ...plano, frase: "Somam {total.taxa}." }, taxas).origem, "codigo");
});

test("maior e menor são as linhas de maior e menor medida, com a unidade dela", () => {
  const meses = [{ mes: "ago/2025", otp: 85.94 }, { mes: "dez/2025", otp: 72.02 }, { mes: "jul/2026", otp: 83.2 }];
  const plano = { grafico: "linha", x: "mes", y: "otp", unidade: "%",
                  frase: "Ficou entre {menor.otp}, em {menor.rotulo}, e {maior.otp}, em {maior.rotulo}." };
  assert.equal(narrar(plano, meses).texto, "Ficou entre 72,0%, em dez/2025, e 85,9%, em ago/2025.");
});

test("uma linha só: {col} é o valor da coluna", () => {
  const plano = { grafico: "tabela", x: "realizados", y: "otp", unidade: "%",
                  frase: "A pontualidade da GOL é de {otp}, sobre {realizados} voos realizados." };
  assert.equal(narrar(plano, [{ otp: 86.0519, realizados: 245812 }]).texto,
               "A pontualidade da GOL é de 86,1%, sobre 245.812 voos realizados.");
});

test("a frase do código narra os formatos comuns", () => {
  assert.match(frase(PLANO_SP, SP), /^No topo, GUARULHOS, com 147\.976 voos, seguido de SÃO PAULO \(95\.707 voos\) e CAMPINAS \(60\.387 voos\)\. Os 16 aeroportos somam 317\.327 voos\.$/);
  const serie = { grafico: "linha", x: "mes", y: "otp", unidade: "%", titulo: "OTP de partida por mês" };
  assert.equal(frase(serie, [{ mes: "ago/2025", otp: 85.9 }, { mes: "dez/2025", otp: 72 }]),
               "OTP de partida por mês: de 72,0% em dez/2025 a 85,9% em ago/2025, entre ago/2025 e dez/2025.");
  const halteres = { grafico: "halteres", x: "saindo", y: "chegando", unidade: "%" };
  assert.match(frase(halteres, [{ rota: "SÃO LUÍS", saindo: 64.984, chegando: 81.447 }, { rota: "X", saindo: 70, chegando: 80 }]),
               /^No topo, SÃO LUÍS: 65,0% em saindo contra 81,4% em chegando\./);
  for (const p of [PLANO_SP, serie, halteres]) assert.deepEqual(desconhecidos(frase(p, SP), numerosConhecidos(p, SP)), []);
});

test("o verificador aceita arredondamento e escala, e recusa conta de cabeça", () => {
  const conhecidos = numerosConhecidos(PLANO_SP, SP);
  assert.deepEqual(desconhecidos("Somam 317.327 partidas, cerca de 317 mil.", conhecidos), []);
  assert.deepEqual(desconhecidos("Guarulhos tem 46,6% do total.", conhecidos), ["46,6"], "fatia calculada de cabeça");
  assert.deepEqual(desconhecidos("Os 3 maiores, em 2025.", [2025]), [], "contagem pequena e ano conhecido passam");
});

test("conversa só cita número que já apareceu", () => {
  const historico = [{ pergunta: "voos em sao paulo", amostra: [{ aeroporto: "GUARULHOS", voos: 147976 }], total: 16,
                       resposta: "Os 16 aeroportos somam 317.327 partidas." }];
  assert.equal(conferirConversa("Guarulhos responde por 147.976 das 317.327 partidas.", { historico }).ok, true);
  const r = conferirConversa("É 46,6% do total do estado.", { historico });
  assert.equal(r.ok, false);
  assert.deepEqual(r.desconhecidos, ["46,6"]);
});
