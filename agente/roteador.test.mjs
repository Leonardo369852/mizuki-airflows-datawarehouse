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

/* O turno como a página guarda no histórico: com a receita da resposta montada aqui. */
const turno = (pergunta, r) => ({ pergunta, sql: r.plano.sql, amostra: [], total: 1, receita: r.receita });

test("seguimento: o caso do print, 'e de Minas?' depois da pronta de São Paulo", () => {
  const sp = rota("chegar de Sao Paulo é pior que sair?");
  assert.equal(sp.rota, "pronta");
  assert.equal(sp.receita?.tipo, "sentidos");
  const mg = rota("e de Minas?", [turno("chegar de Sao Paulo é pior que sair?", sp)]);
  assert.equal(mg.rota, "template");
  assert.equal(mg.motivo, "seguimento");
  assert.match(mg.plano.sql, /WITH lugar AS \(SELECT icao FROM dim_aerodromo WHERE uf = 'MG' AND icao IS NOT NULL\)/);
  assert.match(mg.plano.sql, /COUNT\(\*\) OVER \(PARTITION BY a\.rotulo\)/, "rótulo repetido ganha o ICAO");
  assert.match(mg.plano.sql, /f\.icao_destino NOT IN \(SELECT icao FROM lugar\)/, "voo de MG para MG fica de fora");
  assert.equal(mg.plano.grafico, "halteres");
  assert.match(mg.plano.frase, /saindo de MG/);
  assert.doesNotMatch(mg.plano.frase, /\d/, "número só por marcador");
  const rj = rota("e do Rio de Janeiro?", [turno("x", sp), turno("e de Minas?", mg)]);
  assert.match(rj.plano.sql, /uf = 'RJ'/, "o seguimento do seguimento");
  const gru = rota("e de Guarulhos?", [turno("e de Minas?", mg)]);
  assert.match(gru.plano.sql, /WITH lugar AS \(SELECT 'SBGR' AS icao\)/);
});

test("seguimento de template troca a entidade do mesmo tipo ou acrescenta outra", () => {
  const sp = rota("voos em sao paulo, todos");
  const h = [turno("voos em sao paulo, todos", sp)];
  const mg = rota("e em minas gerais?", h);
  assert.equal(mg.rota, "template");
  assert.match(mg.plano.sql, /a\.uf = 'MG'/);
  assert.doesNotMatch(mg.plano.sql, /'SP'/);
  const gol = rota("e da gol?", h);
  assert.match(gol.plano.sql, /a\.uf = 'SP'/);
  assert.match(gol.plano.sql, /e\.marca = 'GOL'/);
  const otp = rota("qual a pontualidade da gol?");
  const h2 = [turno("qual a pontualidade da gol?", otp)];
  assert.match(rota("e da azul?", h2).plano.sql, /e\.marca = 'AZUL'/);
  assert.match(rota("e em dezembro?", h2).plano.sql, /f\.ano_mes = '2025-12'/);
});

test("seguimento que pede outra coisa, ou sem receita, vai para a IA", () => {
  const sp = rota("chegar de Sao Paulo é pior que sair?");
  const h = [turno("chegar de Sao Paulo é pior que sair?", sp)];
  for (const p of ["e a pior?", "e por mês?", "e para Minas?", "e de Minas e do Rio?",
                   "e da gol?", "e em dezembro?"]) {   /* a pronta de São Paulo só troca o lugar */
    assert.equal(rota(p, h).rota, "ia", p);
  }
  const serie = rota("pontualidade da gol por mês");
  assert.equal(rota("e em dezembro?", [turno("pontualidade da gol por mês", serie)]).rota, "ia", "série e mês juntos");
  assert.equal(rota("e de Minas?", [{ pergunta: "x", sql: "SELECT 1", amostra: [], total: 1 }]).rota, "ia",
               "resposta da IA não deixa receita");
});

test("toda receita de seguimento das prontas monta um plano", () => {
  for (const ex of CONH.exemplos.filter((e) => e.seguimento)) {
    const r = rota("e de Minas?", [{ pergunta: ex.pergunta, sql: "SELECT 1", amostra: [], total: 1, receita: ex.seguimento }]);
    assert.equal(r.rota, "template", ex.pergunta);
    assert.match(r.plano.sql, /'MG'/, ex.pergunta);
  }
});

test("sugestões para quando a IA falha, e exemplos para o prompt", () => {
  const s = prontasParecidas("qual empresa cancela mais?", CONH.exemplos);
  assert.equal(s.length, 3);
  assert.equal(s[0].pergunta, "Qual empresa tem a maior taxa de cancelamento?");
  const e = exemplosParecidos("quantos voos a latam fez em dezembro?", CONH.exemplos, 4);
  assert.ok(e.length > 0 && e.length <= 4);
  assert.ok(e.some((x) => x.pergunta === "Quantos voos a Azul fez?"));
});
