// node --test "agente/**/*.test.mjs"
// O roteador sobre um pedaço pequeno das dimensões, escrito aqui — o comportamento com a base
// inteira é medido por agente/avaliacao/avaliar.py offline.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { criarRoteador, normalizar, radical, prontasParecidas, exemplosParecidos } from "./roteador.js";

const ler = (n) => JSON.parse(readFileSync(new URL(`./conhecimento/${n}.json`, import.meta.url), "utf8"));
const CONH = { identidade: ler("identidade"), exemplos: ler("exemplos").exemplos, apelidos: ler("apelidos"),
               fatos: ler("fatos").fatos };
const aero = (icao, municipio, uf, estado, nome = null) => ({ icao, nome, municipio, uf, estado, rotulo: municipio ?? icao });
const DIMS = {
  aerodromos: [
    aero("SBGR", "GUARULHOS", "SP", "São Paulo", "Guarulhos - Governador André Franco Montoro"),
    aero("SBSP", "SÃO PAULO", "SP", "São Paulo", "São Paulo/Congonhas - Deputado Freitas Nobre"),
    aero("SBKP", "CAMPINAS", "SP", "São Paulo", "Viracopos"),
    aero("SBCF", "CONFINS", "MG", "Minas Gerais", "Tancredo Neves"),
    aero("SBBE", "BELÉM", "PA", "Pará"),
    aero("SBPJ", "PALMAS", "TO", "Tocantins"),
    aero("SBAR", "ARACAJU", "SE", "Sergipe"),
    aero("SBRJ", "RIO DE JANEIRO", "RJ", "Rio de Janeiro", "Santos Dumont"),
    aero("SBGL", "RIO DE JANEIRO", "RJ", "Rio de Janeiro"),
    aero("SCEL", null, null, null),
  ],
  empresas: [
    { icao_empresa: "TAM", nome: "TAM LINHAS AÉREAS S.A.", marca: "LATAM" },
    { icao_empresa: "LAN", nome: "LATAM AIRLINES GROUP", marca: "LATAM" },
    { icao_empresa: "GLO", nome: "GOL LINHAS AÉREAS S.A.", marca: "GOL" },
    { icao_empresa: "AZU", nome: "AZUL LINHAS AÉREAS BRASILEIRAS S/A", marca: "AZUL" },
    { icao_empresa: "TAP", nome: "TAP - TRANSPORTES AÉREOS PORTUGUESES S/A", marca: null },
  ],
  meses: [
    { ano_mes: "2025-08", nome_mes: "ago/2025", dias_com_voo: 31 },
    { ano_mes: "2025-12", nome_mes: "dez/2025", dias_com_voo: 31 },
    { ano_mes: "2026-03", nome_mes: "mar/2026", dias_com_voo: 31 },
    { ano_mes: "2026-08", nome_mes: "ago/2026", dias_com_voo: 1 },
  ],
};
const rot = criarRoteador({ ...CONH }, DIMS);
const rota = (p, historico = []) => rot.rotear(p, { historico });

test("normaliza e reduz ao radical", () => {
  assert.equal(normalizar("Voos em SÃO PAULO, todos!"), "voos em sao paulo todos");
  assert.equal(normalizar("dez/2025 às 10:30"), "dez/2025 as 10:30");
  for (const [a, b] of [["cancelamentos", "cancelados"], ["movimentam", "movimentados"], ["nacionais", "nacional"], ["meses", "mes"]]) {
    assert.equal(radical(normalizar(a)), radical(normalizar(b)), `${a} ~ ${b}`);
  }
});

test("respostas fixas saem sem banco e sem IA", () => {
  const semBanco = criarRoteador({ ...CONH });
  for (const [p, intencao] of [["oi?", "saudacao"], ["Bom dia!", "saudacao"], ["quem é você?", "identidade"],
                               ["como você funciona?", "funcionamento"], ["o que eu posso perguntar?", "ajuda"],
                               ["obrigado!", "agradecimento"],
                               ["qual o motivo dos cancelamentos?", "fora_do_grao.motivo_cancelamento"],
                               ["o voo AD 4512 de ontem atrasou?", "fora_do_grao.voo_especifico"],
                               ["quantos voos teve no dia 25 de dezembro?", "fora_do_grao.por_dia"],
                               ["a que horas sai o primeiro voo de congonhas?", "fora_do_grao.horario"]]) {
    const r = semBanco.rotear(p);
    assert.equal(r.rota, "fixa", p);
    assert.equal(r.intencao, intencao, p);
    assert.doesNotMatch(r.texto, /\{[a-z_]+\}/, p);
  }
  assert.equal(semBanco.rotear("quantos voos a gol fez?").rota, "ia", "sem banco, o resto espera a IA");
});

test("pronta: a mesma pergunta dita de outro jeito, com as mesmas entidades", () => {
  assert.equal(rota("que empresa tem a maior taxa de cancelamentos?").rota, "pronta");
  assert.equal(rota("sair de sp é pior que chegar?").rota, "pronta");
  assert.equal(rota("quantos voos foram cancelados em março de 2026?").rota, "pronta");
});

test("pronta não aceita entidade, número ou restrição a mais", () => {
  const latam = rota("quantos voos a latam fez?");
  assert.equal(latam.rota, "template", "o exemplo é da Azul: parecido não é igual");
  assert.match(latam.plano.sql, /e\.marca = 'LATAM'/);
  assert.equal(rota("quantos voos teve em março de 2026?").rota, "template", "não é a pergunta dos cancelamentos");
  assert.equal(rota("qual empresa tem a maior taxa de cancelamento em 2026?").rota, "ia");
  assert.equal(rota("qual empresa tem a maior taxa de cancelamento internacional?").rota, "ia");
});

test("template: o caso do print, com o estado lido como estado", () => {
  const r = rota("voos em sao paulo, todos");
  assert.equal(r.rota, "template");
  assert.match(r.plano.sql, /a\.uf = 'SP'/);
  assert.match(r.plano.sql, /GROUP BY a\.icao, a\.rotulo/);
  assert.equal(r.plano.grafico, "barra_horizontal");
  assert.match(r.plano.aviso, /lido como o estado/);
  assert.match(r.plano.aviso, /partidas/);
});

test("template: pontualidade exclui os voos sem data e diz isso", () => {
  const r = rota("qual a pontualidade da gol?");
  assert.equal(r.rota, "template");
  assert.match(r.plano.sql, /f\.ano_mes IS NOT NULL/);
  assert.match(r.plano.aviso, /sem data de partida prevista/);
  assert.equal(rota("pontualidade da gol por mês").plano.grafico, "linha");
});

test("template só com casamento inequívoco", () => {
  for (const p of ["qual a rota com mais voos?", "quais aeroportos têm o maior atraso médio?",
                   "a pontualidade é melhor no fim de semana?", "voos na cidade de são paulo",
                   "quantos voos em agosto?", "quantos voos a tap fez?", "quantos voos saíram de gru e congonhas?",
                   "qual a pontualidade das chegadas em gru?"]) {
    assert.equal(rota(p).rota, "ia", p);
  }
});

test("nome que é palavra comum só vale com grafia de nome", () => {
  assert.doesNotMatch(rota("qual a pontualidade para a gol?").plano.sql, /'PA'/, "'para' é a preposição");
  assert.doesNotMatch(rota("Para a gol, qual a pontualidade?").plano.sql, /'PA'/, "inicial maiúscula não basta com acento");
  assert.match(rota("quantos voos saíram do Pará?").plano.sql, /a\.uf = 'PA'/);
  assert.match(rota("quantos voos do para?").plano.sql, /a\.uf = 'PA'/, "depois de 'do' só pode ser o estado");
  assert.match(rota("quantos voos saíram de Palmas?").plano.sql, /f\.icao_origem = 'SBPJ'/,
               "município de um aeroporto só é aquele aeroporto");
  assert.match(rota("voos de SE").plano?.sql ?? "", /a\.uf = 'SE'/, "sigla ambígua em maiúscula vale");
  assert.equal(rota("voos de se").rota === "template" && /'SE'/.test(rota("voos de se").plano.sql), false);
});

test("com conversa em andamento, continuação vai para a IA", () => {
  const h = [{ pergunta: "voos em sao paulo, todos", sql: "SELECT 1", amostra: [], total: 16 }];
  for (const p of ["e a gol?", "e em minas?", "o que isso significa?", "só as nacionais"]) {
    assert.equal(rota(p, h).rota, "ia", p);
  }
  assert.equal(rota("obrigado!", h).rota, "fixa");
  assert.equal(rota("quantos voos a gol fez?", h).rota, "template", "pergunta inteira não é continuação");
});

test("sugestões para quando a IA falha, e exemplos para o prompt", () => {
  const s = prontasParecidas("qual empresa cancela mais?", CONH.exemplos);
  assert.equal(s.length, 3);
  assert.equal(s[0].pergunta, "Qual empresa tem a maior taxa de cancelamento?");
  const e = exemplosParecidos("quantos voos a latam fez em dezembro?", CONH.exemplos, 4);
  assert.ok(e.length > 0 && e.length <= 4);
  assert.ok(e.some((x) => x.pergunta === "Quantos voos a Azul fez?"));
});
