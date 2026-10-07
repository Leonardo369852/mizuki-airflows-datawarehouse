/**
 * Roteador da pergunta: decide, no navegador e antes do Worker, o que dá para responder sem IA.
 * Vai do mais barato para o mais caro:
 *
 *   1. fixa      saudação, "quem é você", ajuda, agradecimento e o que o grão não sustenta (voo
 *                específico, dia, horário, motivo de cancelamento). Texto de identidade.json.
 *                Não precisa nem do banco.
 *   2. pronta    a pergunta é uma pergunta pronta ou um exemplo dito de outro jeito — e fala das
 *                MESMAS entidades. "qual a pontualidade da gol?" parece "Qual a pontualidade da
 *                Azul?" palavra por palavra, e responder com o plano da Azul seria o pior erro
 *                possível: número certo da empresa errada.
 *   3. template  uma medida (voos, pontualidade, cancelamento, atraso) sobre entidades das
 *                dimensões (estado, município, aeroporto, marca, mês). Só com casamento
 *                inequívoco: se sobrar uma palavra que o template não explica ("maior", "rota",
 *                "fim de semana"), a pergunta é de outro tipo e vai para a IA.
 *   4. ia        o resto, pelo Worker.
 *
 * Sem dependência e sem DOM, para rodar igual no navegador, no Worker e no Node.
 */
import { preencher, planoDoExemplo } from "./conhecimento/montar.js";

// ─── Texto ────────────────────────────────────────────────────────────────────

/** Minúsculo, sem acento, sem pontuação — menos ":" e "/", que separam hora e mês. */
export function normalizar(texto) {
  return String(texto ?? "")
    .normalize("NFD").replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9:/ ]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

const palavras = (n) => n.split(/[ :/]+/).filter(Boolean);

/* Palavras que não distinguem uma pergunta de outra. */
const VAZIAS = new Set(("a o as os um uma uns umas de da do das dos em no na nos nas e ou que qual " +
  "quais quanto quantos quanta quantas como onde quando para pra pro por pelo pela pelos pelas com sem " +
  "se eu me mim voce vc isso isto esse essa esses essas este esta estes estas ser sao foi foram era " +
  "eram tem teve tiveram ha houve ao aos sobre entre ja ai la favor quero queria gostaria saber " +
  "mostre mostra mostrar diga dizer dados").split(" "));

/** Radical leve: plural e as terminações mais comuns. "cancelamentos", "cancelados" e
    "cancelou" viram "cancel"; "movimentam" e "movimentados", "moviment". */
export function radical(p) {
  if (p.startsWith("#") || p.length <= 3) return p;
  if (p.length > 4) {
    for (const [de, para] of [["oes", "ao"], ["aes", "ao"], ["ais", "al"], ["eis", "el"], ["ois", "ol"]]) {
      if (p.endsWith(de)) { p = p.slice(0, -de.length) + para; break; }
    }
    if (p.endsWith("s") && !/[su]s$/.test(p)) p = p.slice(0, -1);
  }
  for (const s of ["amento", "imento", "mente", "idade", "acao", "ados", "adas", "ado", "ada", "ido", "ida",
                   "ando", "endo", "indo", "aram", "eram", "iram", "avam", "ava", "ar", "er", "ir", "am",
                   "em", "ou", "eu", "iu", "a", "e", "o"]) {
    if (p.endsWith(s) && p.length - s.length >= 3) return p.slice(0, -s.length);
  }
  return p;
}

/** As palavras que contam para comparar duas perguntas. */
export function chaves(normalizado) {
  return new Set(palavras(normalizado).filter((p) => !VAZIAS.has(p)).map(radical));
}

/** Coeficiente de Dice entre dois conjuntos: 1 é igual, 0 não tem nada em comum. */
export function semelhanca(a, b) {
  if (!a.size || !b.size) return 0;
  let comum = 0;
  for (const x of a) if (b.has(x)) comum++;
  return (2 * comum) / (a.size + b.size);
}

// ─── 1. Respostas fixas ───────────────────────────────────────────────────────

const SAUDACAO_NO_INICIO = /^(oi+|ola|opa|eai|e ai|bom dia|boa tarde|boa noite|salve|fala)( (tudo bem|tudo bom|beleza|blz))? /;

function compilarGatilhos(identidade) {
  const g = identidade.gatilhos;
  return [
    ["saudacao", null, g.saudacao], ["agradecimento", null, g.agradecimento],
    ["identidade", null, g.identidade], ["funcionamento", null, g.funcionamento], ["ajuda", null, g.ajuda],
    ...Object.entries(g.fora_do_grao).map(([sub, re]) => ["fora_do_grao", sub, re]),
  ].map(([intencao, sub, re]) => ({ intencao, sub, re: new RegExp(re) }));
}

/** Saudação, identidade, ajuda, agradecimento e fora do grão. Não precisa do banco. */
export function respostaFixa(pergunta, conhecimento) {
  const n = normalizar(pergunta);
  const gatilhos = conhecimento._gatilhos ??= compilarGatilhos(conhecimento.identidade);
  for (const { intencao, sub, re } of gatilhos) {
    if (!re.test(n)) continue;
    const r = sub ? conhecimento.identidade.respostas[intencao][sub] : conhecimento.identidade.respostas[intencao];
    return { rota: "fixa", intencao: sub ? `${intencao}.${sub}` : intencao, texto: preencher(r, conhecimento.fatos) };
  }
  return null;
}

// ─── Entidades das dimensões ──────────────────────────────────────────────────

const MESES_EXTENSO = ["janeiro", "fevereiro", "marco", "abril", "maio", "junho", "julho", "agosto",
                       "setembro", "outubro", "novembro", "dezembro"];
const MESES_CURTOS = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];
/* Siglas que são também palavra comum ("se", "to", "pe"): só valem escritas em maiúscula. */
const SIGLAS_AMBIGUAS = new Set(["SE", "PA", "PE", "MA", "GO", "TO", "ES", "AL", "AM", "AP"]);
/* Nomes que, sem acento e em minúscula, são palavra comum: "Pará" vira "para", a preposição, e
   "qual a pontualidade para a gol?" responderia o Pará. Só valem com a grafia de nome próprio —
   acento ou inicial maiúscula — no texto digitado. */
const NOMES_COMUNS = new Set(["para", "patos", "breves", "sorriso", "franca", "palmas", "bonito", "una",
                              "salinas", "lencois", "pelotas", "borba", "cascavel", "guaira"]);

/**
 * O dicionário de entidades, montado das próprias dimensões na carga do banco, mais os
 * apelidos que elas não têm. `dims` = { aerodromos: [{icao, nome, municipio, uf, estado,
 * rotulo}], empresas: [{icao_empresa, nome, marca}], meses: [{ano_mes, nome_mes, dias_com_voo}] }.
 */
export function criarDicionario(dims, apelidos = {}) {
  const termos = [];
  const aero = new Map(dims.aerodromos.map((a) => [a.icao, a]));
  const estados = new Map();
  const municipios = new Map();
  for (const a of dims.aerodromos) {
    if (a.uf && a.estado) estados.set(a.uf, a.estado);
    if (a.municipio) municipios.set(a.municipio, [...(municipios.get(a.municipio) ?? []), a.icao]);
  }
  const nomesDeEstado = new Set([...estados.values()].map(normalizar));
  const nomesDeMunicipio = new Set([...municipios.keys()].map(normalizar));

  const grafia = (nome) => (NOMES_COMUNS.has(normalizar(nome)) ? nome : null);
  for (const [uf, nome] of estados) {
    termos.push({ texto: normalizar(nome), grafia: grafia(nome),
                  ent: { tipo: "uf", uf, nome, porNome: true, homonimo: nomesDeMunicipio.has(normalizar(nome)) } });
    termos.push({ texto: uf.toLowerCase(), ent: { tipo: "uf", uf, nome }, soMaiuscula: SIGLAS_AMBIGUAS.has(uf) });
  }
  /* "São Paulo" e "Rio de Janeiro" são estado e município: por convenção, sem qualificação é o
     estado (e o aviso diz isso). O município homônimo não entra como entidade. */
  for (const [m, icaos] of municipios) {
    if (!nomesDeEstado.has(normalizar(m))) {
      termos.push({ texto: normalizar(m), grafia: grafia(m), ent: { tipo: "municipio", municipio: m, icaos } });
    }
  }
  for (const a of dims.aerodromos) termos.push({ texto: a.icao.toLowerCase(), ent: { tipo: "aeroporto", icao: a.icao } });
  for (const g of apelidos.aerodromos ?? []) {
    if (aero.has(g.icao)) for (const ap of g.apelidos) termos.push({ texto: normalizar(ap), ent: { tipo: "aeroporto", icao: g.icao } });
  }
  for (const g of apelidos.estados ?? []) {
    if (estados.has(g.uf)) for (const ap of g.apelidos) termos.push({ texto: normalizar(ap), ent: { tipo: "uf", uf: g.uf, nome: estados.get(g.uf) } });
  }
  const operadoras = new Map();
  for (const e of dims.empresas) if (e.marca) operadoras.set(e.marca, [...(operadoras.get(e.marca) ?? []), e.nome ?? e.icao_empresa]);
  for (const marca of operadoras.keys()) termos.push({ texto: normalizar(marca), ent: { tipo: "marca", marca } });
  for (const g of apelidos.marcas ?? []) {
    if (operadoras.has(g.marca)) for (const ap of g.apelidos) termos.push({ texto: normalizar(ap), ent: { tipo: "marca", marca: g.marca } });
  }
  /* Mês com ano sempre vale; mês sem ano, só se ele aparece uma vez na base ("dezembro" sim,
     "agosto" não: há ago/2025 e o dia solto de ago/2026). */
  const porMes = new Map();
  for (const m of dims.meses) {
    const [ano, mm] = m.ano_mes.split("-");
    const i = Number(mm) - 1;
    const ent = { tipo: "mes", ano_mes: m.ano_mes, nome_mes: m.nome_mes, dias: m.dias_com_voo };
    for (const nome of [MESES_EXTENSO[i], MESES_CURTOS[i]]) {
      for (const t of [`${nome} de ${ano}`, `${nome} ${ano}`, `${nome}/${ano}`]) termos.push({ texto: t, ent });
    }
    porMes.set(i, [...(porMes.get(i) ?? []), ent]);
  }
  for (const [i, lista] of porMes) if (lista.length === 1) termos.push({ texto: MESES_EXTENSO[i], ent: lista[0] });

  termos.sort((a, b) => b.texto.length - a.texto.length);   /* "mato grosso do sul" antes de "mato grosso" */
  return { termos, aero, estados, municipios, operadoras };
}

const chaveDe = (e) => `${e.tipo}:${e.uf ?? e.municipio ?? e.icao ?? e.marca ?? e.ano_mes}`;

/** O nome aparece no texto com cara de nome próprio. Se ele tem acento ("Pará"), só com o acento
    — "Para que..." no começo da frase também tem maiúscula; se não tem ("Palmas"), com a inicial
    maiúscula. */
function escritoComoNome(original, nome) {
  const semAcento = normalizar(nome);
  const temAcento = semAcento !== nome.toLowerCase().normalize("NFC");
  for (const m of original.matchAll(/[\p{L}]+/gu)) {
    const palavra = m[0];
    if (normalizar(palavra) !== semAcento) continue;
    if (temAcento ? normalizar(palavra) !== palavra.toLowerCase() : palavra[0] === palavra[0].toUpperCase()) return true;
  }
  return false;
}
/* Depois destas, a palavra comum não caberia: "voos do para" só pode ser o Pará. */
const PREPOSICAO_DE_LUGAR = new Set(["do", "no", "da", "na", "de", "em"]);

/** Acha as entidades e devolve o texto com cada uma trocada pelo tipo ("#uf", "#marca").
    `original` é a pergunta como foi digitada: sigla ambígua só vale em maiúscula ali. */
export function entidades(texto, dic, original = texto) {
  let n = ` ${normalizar(texto)} `;
  const achadas = [];
  for (const t of dic.termos) {
    if (t.soMaiuscula && !new RegExp(`(^|[^A-Za-z])${t.ent.uf}([^A-Za-z]|$)`).test(String(original))) continue;
    const alvo = ` ${t.texto} `;
    let desde = 0;
    for (let i = n.indexOf(alvo); i >= 0; i = n.indexOf(alvo, desde)) {
      const antes = n.slice(0, i).trim().split(" ").slice(-2).join(" ");
      if (t.grafia && !escritoComoNome(String(original), t.grafia)
          && !PREPOSICAO_DE_LUGAR.has(antes.split(" ").pop())) {
        desde = i + 1;          /* aqui é a palavra comum: segue procurando */
        continue;
      }
      achadas.push({ ...t.ent, antes });
      n = `${n.slice(0, i)} #${t.ent.tipo} ${n.slice(i + alvo.length)}`;
      desde = i;
    }
  }
  const unicas = [...new Map(achadas.map((e) => [chaveDe(e), e])).values()];
  return { mascarado: n.replace(/\s+/g, " ").trim(), lista: unicas };
}

// ─── 3. Template ──────────────────────────────────────────────────────────────

const MEDIDAS = {
  voos: ["voo", "voos", "movimento", "movimentos"],
  origem: ["partida", "partidas", "partiram", "partiu", "decolaram", "decolou", "decolagem", "decolagens",
           "sairam", "saiu", "saem", "sai", "saindo", "partindo"],
  destino: ["chegada", "chegadas", "chegaram", "chegou", "pousaram", "pousou", "pouso", "pousos", "chegando"],
  otp: ["pontualidade", "pontual", "pontuais", "otp"],
  cancelamento: ["cancelamento", "cancelamentos", "cancelado", "cancelados", "cancelada", "canceladas",
                 "cancelou", "cancelaram"],
  atraso: ["atraso", "atrasos", "atrasam", "atrasou", "atrasaram", "atrasado", "atrasados"],
};
const TAXA = new Set(["taxa", "percentual", "porcentagem", "proporcao", "indice"]);
const SERIE = /\b(por mes|mes a mes|mes por mes|cada mes|por meses|ao longo|mensal|mensalmente|evolucao)\b/;
/* O que pode sobrar numa pergunta de template sem mudar o que ela pede. "mais", "maior",
   "melhor", "rota", "periodo" ficam de fora de propósito: pedem ranking ou corte que o
   template não faz. */
const CONECTORES = new Set([...VAZIAS, ..."quantidade numero total totais todos todas todo toda fez fizeram teve tem tiveram houve existem existiram saber quero queria gostaria diga mostre mostra mostrar ver medio media mes meses mensal mensalmente longo cada evolucao aeroporto aeroportos aerodromo aerodromos estado empresa companhia marca geral grupo".split(" ")]);
const PARA = new Set(["para", "pra", "pro", "destino", "ate"]);

/** Lê a pergunta mascarada como um template, ou devolve null com o motivo de não ser. */
export function interpretar(mascarado, lista) {
  const toks = mascarado.split(" ").filter(Boolean);
  const grupos = new Set();
  let direcao = null;
  let taxa = false;
  for (const p of toks) {
    if (p.startsWith("#")) continue;
    const grupo = Object.entries(MEDIDAS).find(([, ps]) => ps.includes(p))?.[0];
    if (grupo === "origem" || grupo === "destino") {
      if (direcao && direcao !== grupo) return { erro: "duas direções" };
      direcao = grupo;
      grupos.add("voos");
    } else if (grupo) {
      grupos.add(grupo);
    } else if (TAXA.has(p)) {
      taxa = true;
    } else if (!CONECTORES.has(p)) {
      return { erro: `sobrou "${p}"` };
    }
  }
  if (grupos.size > 1) grupos.delete("voos");            /* "pontualidade dos voos": voos é só o substantivo */
  if (grupos.size !== 1) return { erro: grupos.size ? "mais de uma medida" : "sem medida" };
  const medida = [...grupos][0];
  if (taxa && medida !== "cancelamento") return { erro: "taxa de quê" };

  const por = (tipo) => lista.filter((e) => e.tipo === tipo);
  const geos = [...por("uf"), ...por("municipio"), ...por("aeroporto")];
  if (geos.length > 1 || por("marca").length > 1 || por("mes").length > 1) return { erro: "entidade repetida" };
  const geo = geos[0] ?? null;
  const serie = SERIE.test(mascarado);
  if (serie && por("mes").length) return { erro: "série e mês juntos" };
  if (geo && PARA.has(geo.antes.split(" ").pop())) {
    if (direcao === "origem") return { erro: "duas direções" };
    direcao = "destino";
  }
  if (direcao === "destino" && medida !== "voos" && medida !== "cancelamento") return { erro: "medida de partida com destino" };
  return { medida, taxa, direcao, geo, marca: por("marca")[0] ?? null, mes: por("mes")[0] ?? null, serie };
}

const aspas = (s) => String(s).replace(/'/g, "''");

/** O plano de um template interpretado: SQL, gráfico, título e avisos. */
export function montarTemplate(t, dic, fatos) {
  const col = t.direcao === "destino" ? "f.icao_destino" : "f.icao_origem";
  const joins = [];
  const filtros = [];
  const avisos = [];
  let escopo = [];
  if (t.geo?.tipo === "aeroporto") {
    filtros.push(`${col} = '${t.geo.icao}'`);
    const a = dic.aero.get(t.geo.icao);
    escopo.push(a?.municipio ? `${a.municipio} (${t.geo.icao})` : t.geo.icao);
  } else if (t.geo) {
    joins.push(`JOIN dim_aerodromo a ON ${col} = a.icao`);
    if (t.geo.tipo === "uf") {
      filtros.push(`a.uf = '${t.geo.uf}'`);
      escopo.push(`estado de ${t.geo.uf}`);
      if (t.geo.porNome && t.geo.homonimo && !/\bestado\b/.test(t.geo.antes)) {
        avisos.push(`"${t.geo.nome}" foi lido como o estado (uf = '${t.geo.uf}'), não a cidade.`);
      }
    } else {
      filtros.push(`a.municipio = '${aspas(t.geo.municipio)}'`);
      escopo.push(t.geo.municipio);
    }
  }
  const operadoras = t.marca ? dic.operadoras.get(t.marca.marca)?.length ?? 1 : 0;
  if (t.marca) {
    joins.push("JOIN dim_empresa e ON f.icao_empresa = e.icao_empresa");
    filtros.push(`e.marca = '${t.marca.marca}'`);
    escopo.push(t.marca.marca);
  }
  if (t.mes) {
    filtros.push(`f.ano_mes = '${t.mes.ano_mes}'`);
    escopo.push(t.mes.nome_mes);
    if (t.mes.dias < 28) avisos.push(`${t.mes.nome_mes} tem só ${t.mes.dias} ${t.mes.dias === 1 ? "dia" : "dias"} na fonte: o mês está incompleto.`);
  }

  const M = {
    voos: { sel: ["SUM(f.voos) AS voos"], y: "voos", un: "voos", aditiva: true,
            nome: t.geo ? (t.direcao === "destino" ? "Chegadas" : "Partidas") : "Voos" },
    cancelamento: { sel: ["SUM(f.cancelados) AS cancelados", "100.0 * SUM(f.cancelados) / NULLIF(SUM(f.voos), 0) AS taxa"],
                    y: t.taxa ? "taxa" : "cancelados", un: t.taxa ? "%" : "voos", aditiva: !t.taxa,
                    nome: t.taxa ? "Taxa de cancelamento" : "Cancelamentos" },
    otp: { sel: ["100.0 * SUM(f.partidas_pontuais) / NULLIF(SUM(f.realizados), 0) AS otp", "SUM(f.realizados) AS realizados"],
           y: "otp", un: "%", nome: "OTP de partida" },
    atraso: { sel: ["SUM(f.soma_atraso_plausivel) / NULLIF(SUM(f.com_atraso_plausivel), 0) AS atraso", "SUM(f.realizados) AS realizados"],
              y: "atraso", un: "min", nome: "Atraso médio de partida" },
  }[t.medida];
  if (t.medida === "voos" && t.geo && !t.direcao) avisos.push("Conta as partidas: os voos que saíram de lá.");
  if (t.medida === "otp" && !t.mes && !t.serie) {
    filtros.push("f.ano_mes IS NOT NULL");
    avisos.push("Sem os {sem_data_voos} voos sem data de partida prevista, que não podem ser pontuais.");
  }
  if (t.medida === "atraso") avisos.push("Só atrasos entre {faixa_min} e {faixa_max} min: a fonte tem horários invertidos.");

  const de = ["FROM fato_voos f", ...joins];
  const onde = (extra = []) => {
    const todos = [...extra, ...filtros];
    return todos.length ? [`WHERE ${todos.join(" AND ")}`] : [];
  };
  const titulo = (forma) => [M.nome + forma, escopo.join(", ")].filter(Boolean).join(" — ");
  const porOperadora = t.marca && !t.geo && !t.serie && M.aditiva && operadoras > 1;
  if (operadoras > 1) {
    avisos.unshift(`A marca ${t.marca.marca} soma ${operadoras} operadoras do grupo`
                   + (porOperadora ? "; a tabela mostra cada uma." : "."));
  }

  if (t.serie) {
    avisos.push("Só meses completos.");
    const sql = ["SELECT t.nome_mes AS mes, " + M.sel.join(", "), ...de, "JOIN dim_tempo t ON f.ano_mes = t.ano_mes",
                 ...onde(["t.dias_com_voo >= 28"]), "GROUP BY t.nome_mes, t.ordem", "ORDER BY t.ordem", "LIMIT 20"];
    return plano(sql, "linha", "mes", M.y, M.un, titulo(" por mês"), avisos, fatos);
  }
  if (t.geo && t.geo.tipo !== "aeroporto" && M.aditiva) {
    const sql = ["SELECT a.rotulo AS aeroporto, " + M.sel.join(", "), ...de, ...onde(),
                 "GROUP BY a.icao, a.rotulo", `ORDER BY ${M.y} DESC`, "LIMIT 40"];
    return plano(sql, "barra_horizontal", M.y, "aeroporto", M.un, titulo(" por aeroporto"), avisos, fatos);
  }
  if (porOperadora) {
    const sql = ["SELECT e.nome AS empresa, " + M.sel.join(", "), ...de, ...onde(), "GROUP BY e.nome",
                 `ORDER BY ${M.y} DESC`, "LIMIT 10"];
    return plano(sql, "barra_horizontal", M.y, "empresa", M.un, titulo(", por operadora"), avisos, fatos);
  }
  const sql = ["SELECT " + M.sel.join(", "), ...de, ...onde(), "LIMIT 1"];
  const x = M.sel.length > 1 ? M.sel[1].split(" AS ").pop() : M.y;
  return plano(sql, "tabela", x, M.y, M.un, titulo(""), avisos, fatos);
}

function plano(sql, grafico, x, y, unidade, titulo, avisos, fatos) {
  return { tipo: "consulta", sql: sql.join("\n"), grafico, x, y, unidade, titulo,
           aviso: preencher(avisos.join(" "), fatos), serie: "", resposta: "" };
}

// ─── O roteador ───────────────────────────────────────────────────────────────

/* Semelhança não basta para chamar de "a mesma pergunta". "quantos voos teve em março de
   2026?" tem 0,80 com o exemplo "Quantos voos foram cancelados em março de 2026?" — mesmas
   entidades, e responderia cancelamentos. A regra é de conteúdo: toda palavra que conta no
   exemplo tem de estar na pergunta, e a pergunta só pode ter a mais palavras que não
   restringem nada. Um "internacional" a mais muda a resposta; um "ao longo" não. O limiar de
   semelhança fica só como trava extra. */
export const LIMIAR_PRONTA = 0.75;
const SOBRA_INOFENSIVA = new Set(["long", "empres", "companhi", "aere", "brasil", "geral", "tod", "total"]);

function mesmaPergunta(minhas, delas) {
  for (const k of delas) if (!minhas.has(k)) return false;
  for (const k of minhas) if (!delas.has(k) && !SOBRA_INOFENSIVA.has(k)) return false;
  return true;
}

const CONTINUACAO = /^(e|mas|agora|so|somente|apenas|tambem|entao|por|no|na|nos|nas|em|e no|e na|e em|e o|e a|e os|e as)\b/;
const REFERENCIA = new Set(["isso", "isto", "desses", "dessas", "deles", "delas", "nesse", "nessa", "nesses",
                            "nessas", "esse", "essa", "esses", "essas", "mesmo", "mesma", "anterior", "acima"]);

/** Com conversa em andamento, pergunta curta ou que aponta para trás continua a anterior: só a
    IA, que vê o histórico, sabe o que "e em minas?" quer dizer. */
function continuaAnterior(n) {
  const ps = palavras(n);
  return CONTINUACAO.test(n) && ps.length <= 6 || ps.some((p) => REFERENCIA.has(p));
}

/**
 * `conhecimento` = { identidade, exemplos, apelidos, fatos } (os JSON de conhecimento/).
 * `dims` pode chegar depois (o banco carrega em segundo plano): sem ele, só a rota fixa.
 */
export function criarRoteador(conhecimento, dims = null) {
  let dic = null;
  let candidatas = [];

  function comDimensoes(d) {
    dic = criarDicionario(d, conhecimento.apelidos);
    candidatas = conhecimento.exemplos
      .filter((ex) => ex.plano.tipo === "consulta")
      .map((ex) => {
        const { mascarado, lista } = entidades(ex.pergunta, dic);
        return { ex, chaves: chaves(mascarado), ents: lista.map(chaveDe).sort().join("|") };
      });
  }
  if (dims) comDimensoes(dims);

  function rotear(pergunta, { historico = [] } = {}) {
    const fixa = respostaFixa(pergunta, conhecimento);
    if (fixa) return fixa;
    const n = normalizar(pergunta).replace(SAUDACAO_NO_INICIO, "");
    if (!n) return { rota: "ia", motivo: "vazia" };
    if (historico.length && continuaAnterior(n)) return { rota: "ia", motivo: "continua a conversa" };
    if (!dic) return { rota: "ia", motivo: "banco ainda não carregou" };

    const { mascarado, lista } = entidades(n, dic, pergunta);
    const minhas = chaves(mascarado);
    const ents = lista.map(chaveDe).sort().join("|");
    /* Número solto que não virou entidade ("2026", "top 5") restringe a pergunta: não é pronta. */
    const temNumeroSolto = palavras(mascarado).some((p) => /\d/.test(p));
    let melhor = null;
    for (const c of temNumeroSolto ? [] : candidatas) {
      const s = semelhanca(minhas, c.chaves);
      if (c.ents === ents && s >= LIMIAR_PRONTA && mesmaPergunta(minhas, c.chaves) && (!melhor || s > melhor.s)) {
        melhor = { ...c, s };
      }
    }
    if (melhor) {
      return { rota: "pronta", plano: planoDoExemplo(melhor.ex, conhecimento.fatos),
               exemplo: melhor.ex.pergunta, semelhanca: Number(melhor.s.toFixed(2)) };
    }

    const t = interpretar(mascarado, lista);
    if (!t.erro) return { rota: "template", plano: montarTemplate(t, dic, conhecimento.fatos), entendido: t };
    return { rota: "ia", motivo: t.erro };
  }

  return { rotear, comDimensoes, get pronto() { return !!dic; } };
}

/** As n perguntas prontas mais parecidas — o que a página oferece quando a IA falha. */
export function prontasParecidas(pergunta, exemplos, n = 3) {
  const minhas = chaves(normalizar(pergunta));
  return exemplos.filter((e) => e.chip)
    .map((e) => ({ e, s: semelhanca(minhas, chaves(normalizar(e.pergunta))) }))
    .sort((a, b) => b.s - a.s)
    .slice(0, n)
    .map(({ e }) => e);
}

/** Os n exemplos mais parecidos com a pergunta — os que o /consulta põe no prompt. Com menos
    de `minimo` parecidos, completa com as perguntas prontas (as primeiras do arquivo): mesmo
    sem parentesco, elas mostram o formato do plano. */
export function exemplosParecidos(pergunta, exemplos, n = 4, minimo = 3) {
  const minhas = chaves(normalizar(pergunta));
  const escolhidos = exemplos
    .map((e) => ({ e, s: semelhanca(minhas, chaves(normalizar(e.pergunta))) }))
    .filter(({ s }) => s > 0)
    .sort((a, b) => b.s - a.s)
    .slice(0, n)
    .map(({ e }) => e);
  for (const e of exemplos) {
    if (escolhidos.length >= minimo) break;
    if (!escolhidos.includes(e)) escolhidos.push(e);
  }
  return escolhidos;
}
