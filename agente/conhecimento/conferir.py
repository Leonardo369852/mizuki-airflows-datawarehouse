"""Confere a base de conhecimento do agente contra os dados, e gera fatos.json.

    python agente/conhecimento/conferir.py                       confere; sai com 1 se algo não bate
    python agente/conhecimento/conferir.py --atualizar-manifest  grava no manifest os fatos calculados
                                                                 aqui (para um export anterior a eles)

1. manifest.fatos — recalcula no DuckDB, sobre os Parquet, o que o notebook de export calcula sobre
                    as mesmas tabelas. Os dois têm de bater: são duas implementações da mesma conta.
2. fatos.json     — regenerado do manifest, sempre. Nunca à mão.
3. {chaves}       — todo número entre chaves em semantica, identidade e exemplos existe em fatos.
4. semantica.json — toda coluna e medida citada existe na tabela.
5. exemplos.json  — todo SQL roda, devolve linha, passa nas travas do Worker, e x/y existem.
6. apelidos.json  — todo ICAO, marca e UF existe; apelido de fonte "base" aparece na base.
"""
from __future__ import annotations

import argparse
import decimal
import io
import json
import math
import re
import sys
import unicodedata
from pathlib import Path

AQUI = Path(__file__).resolve().parent
AGENTE = AQUI.parent
DADOS = AGENTE / "dados"
MANIFEST = DADOS / "manifest.json"
TABELAS = ["fato_voos", "dim_empresa", "dim_aerodromo", "dim_rota", "dim_tempo"]
MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]

# As mesmas travas do sqlSuspeito() do Worker e da página.
PROIBIDAS = ["attach", "copy", "install", "load", "export", "import", "create", "insert", "update",
             "delete", "drop", "alter", "pragma", "set", "read_csv", "read_parquet", "read_json",
             "glob", "system", "shell"]
GRAFICOS = ["barra_horizontal", "barra_vertical", "linha", "dispersao", "halteres", "mapa", "tabela"]
UNIDADES = ["%", "min", "voos", "km", ""]
MEDIDA_EM = {"barra_horizontal": "x", "barra_vertical": "y", "linha": "y"}   # o desenhar() da página


def ler(nome: str) -> dict:
    return json.loads((AQUI / nome).read_text(encoding="utf-8"))


def abrir_banco():
    import duckdb
    con = duckdb.connect()
    for t in TABELAS:
        sel = "SELECT *, COALESCE(municipio, nome, icao) AS rotulo" if t == "dim_aerodromo" else "SELECT *"
        con.execute(f"CREATE VIEW {t} AS {sel} FROM read_parquet('{(DADOS / f'{t}.parquet').as_posix()}')")
    return con


def rodar(con, sql: str) -> list[dict]:
    cur = con.execute(sql)
    cols = [d[0] for d in cur.description]
    return [{c: (float(v) if isinstance(v, decimal.Decimal) else v) for c, v in zip(cols, linha)}
            for linha in cur.fetchall()]


def normal(s) -> str:
    s = unicodedata.normalize("NFKD", str(s or ""))
    return re.sub(r"\s+", " ", "".join(c for c in s if not unicodedata.combining(c)).upper()).strip()


def sql_de(plano: dict) -> str:
    sql = plano.get("sql") or ""
    return "\n".join(sql) if isinstance(sql, list) else sql


# ─── 1. fatos do manifest ─────────────────────────────────────────────────────

def calcular_fatos(con) -> dict:
    """A mesma conta do notebook de export (bloco "fatos" do manifest), feita sobre os Parquet."""
    meses = rodar(con, "SELECT ano_mes, nome_mes, dias_com_voo, voos FROM dim_tempo "
                       "WHERE ano_mes IS NOT NULL ORDER BY ordem")
    completos = [m for m in meses if m["dias_com_voo"] >= 28]
    nome_do_mes = {m["ano_mes"]: m["nome_mes"] for m in meses}

    def otp(p, r):
        return round(100.0 * float(p) / float(r), 1)

    lista = ", ".join(f"'{m['ano_mes']}'" for m in completos)
    otp_por_mes = {s["ano_mes"]: otp(s["p"], s["r"]) for s in rodar(con, f"""
        SELECT ano_mes, SUM(partidas_pontuais) AS p, SUM(realizados) AS r
        FROM fato_voos WHERE ano_mes IN ({lista}) GROUP BY ano_mes ORDER BY ano_mes""")}
    mes_min = min(otp_por_mes, key=otp_por_mes.get)
    mes_max = max(otp_por_mes, key=otp_por_mes.get)

    sem_cadastro = [r["icao"] for r in rodar(con, "SELECT icao FROM dim_aerodromo WHERE uf IS NULL ORDER BY icao")]
    brasileiros = sorted(i for i in sem_cadastro if re.match(r"^S[BDIJNSW]", i))
    na_dimensao = {r["icao"] for r in rodar(con, "SELECT icao FROM dim_aerodromo")}
    partidas = {r["o"]: r["v"] for r in rodar(con, "SELECT icao_origem AS o, SUM(voos) AS v FROM fato_voos "
                                                   "WHERE icao_origem IS NOT NULL GROUP BY 1")}
    na_dim = {o: v for o, v in partidas.items() if o in na_dimensao}
    fora = {o: v for o, v in partidas.items() if o not in na_dimensao}
    por_nacionalidade = {r["nacional"]: otp(r["p"], r["r"]) for r in rodar(con, """
        SELECT e.nacional, SUM(f.partidas_pontuais) AS p, SUM(f.realizados) AS r
        FROM fato_voos f JOIN dim_empresa e ON f.icao_empresa = e.icao_empresa GROUP BY 1""")}
    rotas = rodar(con, """SELECT COUNT(*) FILTER (WHERE distancia_km IS NULL) AS rotas,
                                 SUM(voos) FILTER (WHERE distancia_km IS NULL) AS voos,
                                 SUM(voos) AS total FROM dim_rota""")[0]
    municipios = rodar(con, """SELECT municipio, list(icao ORDER BY icao) AS icaos FROM dim_aerodromo
                               WHERE municipio IS NOT NULL GROUP BY municipio HAVING COUNT(*) > 1
                               ORDER BY municipio""")
    return {
        "periodo": {
            "inicio": meses[0]["ano_mes"],
            "fim": completos[-1]["ano_mes"],
            "meses_completos": len(completos),
            "parciais": [{"ano_mes": m["ano_mes"], "nome_mes": m["nome_mes"], "dias": int(m["dias_com_voo"]),
                          "voos": int(m["voos"])} for m in meses if m["dias_com_voo"] < 28],
        },
        "otp_mensal": {"min": otp_por_mes[mes_min], "mes_min": nome_do_mes[mes_min],
                       "max": otp_por_mes[mes_max], "mes_max": nome_do_mes[mes_max]},
        "aerodromos_sem_cadastro": {
            "total": len(sem_cadastro),
            "estrangeiros": len(sem_cadastro) - len(brasileiros),
            "brasileiros": len(brasileiros),
            "brasileiros_icao": brasileiros,
            "pct_partidas": round(100.0 * float(sum(v for o, v in na_dim.items() if o in set(sem_cadastro)))
                                  / float(sum(na_dim.values())), 1),
        },
        "fora_da_dim_aerodromo": {"origens": len(fora), "voos": int(sum(fora.values()))},
        "otp_empresas": {"nacionais": por_nacionalidade[True], "estrangeiras": por_nacionalidade[False]},
        "rotas_sem_distancia": {"rotas": int(rotas["rotas"]), "voos": int(rotas["voos"]),
                                "pct_voos": round(100.0 * float(rotas["voos"]) / float(rotas["total"]), 1)},
        "municipios_com_varios_aerodromos": {m["municipio"]: list(m["icaos"]) for m in municipios},
    }


# ─── 2. fatos.json ────────────────────────────────────────────────────────────

def br(v) -> str:
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, int) or (isinstance(v, float) and v.is_integer() and abs(v) >= 1000):
        return f"{int(v):,}".replace(",", ".")
    return f"{v:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")


def gerar_fatos(m: dict) -> dict:
    """Do manifest para o formato que os textos usam: cada fato com o valor e o texto pronto
    em português ({voos} vira "1.014.705")."""
    q, t, f, d = m["qualidade"], m["tabelas"], m["fatos"], m["definicoes"]
    per = f["periodo"]

    def mes(am):
        return f"{MESES[int(am[5:7]) - 1]}/{am[:4]}"

    def num(v):
        return {"valor": v, "texto": br(v)}

    def txt(s):
        return {"texto": s}

    parcial = ""
    if per["parciais"]:
        p = per["parciais"][-1]
        parcial = (f"O mês {p['nome_mes']} tem só {p['dias']} {'dia' if p['dias'] == 1 else 'dias'} na fonte "
                   f"({br(p['voos'])} voos): a série termina no começo dele.")
    sc, rs = f["aerodromos_sem_cadastro"], f["rotas_sem_distancia"]
    return {
        "periodo": txt(f"{mes(per['inicio'])} a {mes(per['fim'])}"),
        "meses_completos": num(per["meses_completos"]),
        "periodo_parcial": txt(parcial),
        "voos": num(q["total_voos"]),
        "linhas_fato": num(t["fato_voos"]["linhas"]),
        "empresas": num(t["dim_empresa"]["linhas"]),
        "aerodromos": num(t["dim_aerodromo"]["linhas"]),
        "rotas": num(t["dim_rota"]["linhas"]),
        "tamanho_mb": num(round(sum(x["bytes"] for x in t.values()) / 1e6, 1)),
        "sem_data_voos": num(q["sem_data_prevista"]),
        "sem_data_pct": num(round(100.0 * q["sem_data_prevista"] / q["total_voos"], 1)),
        "otp_global": num(q["otp_global"]),
        "otp_com_data": num(q["otp_com_data"]),
        "otp_mes_min": num(f["otp_mensal"]["min"]),
        "otp_mes_min_nome": txt(f["otp_mensal"]["mes_min"]),
        "otp_mes_max": num(f["otp_mensal"]["max"]),
        "otp_mes_max_nome": txt(f["otp_mensal"]["mes_max"]),
        "cancelados": num(q["cancelados"]),
        "atrasos_implausiveis": num(q["atrasos_implausiveis"]),
        "faixa_min": num(d["faixa_plausivel"][0]),
        "faixa_max": num(d["faixa_plausivel"][1]),
        "sem_cadastro": num(sc["total"]),
        "sem_cadastro_estrangeiros": num(sc["estrangeiros"]),
        "sem_cadastro_brasileiros": num(sc["brasileiros"]),
        "sem_cadastro_brasileiros_icao": txt(", ".join(sc["brasileiros_icao"])),
        "sem_cadastro_pct": num(sc["pct_partidas"]),
        "fora_da_dim_origens": num(f["fora_da_dim_aerodromo"]["origens"]),
        "fora_da_dim_voos": num(f["fora_da_dim_aerodromo"]["voos"]),
        "otp_nacionais": num(f["otp_empresas"]["nacionais"]),
        "otp_estrangeiras": num(f["otp_empresas"]["estrangeiras"]),
        "rotas_sem_distancia": num(rs["rotas"]),
        "rotas_sem_distancia_voos": num(rs["voos"]),
        "rotas_sem_distancia_pct": num(rs["pct_voos"]),
        "municipios_com_varios_aerodromos": txt("; ".join(
            f"{mun}: {', '.join(icaos)}" for mun, icaos in f["municipios_com_varios_aerodromos"].items())),
    }


# ─── 3 a 6. conferências ──────────────────────────────────────────────────────

def textos(no):
    """Todo texto onde pode haver {fato}. O campo "frase" fica de fora: as chaves dele são
    marcadores que a página preenche com o resultado da consulta, não fatos."""
    if isinstance(no, str):
        yield no
    elif isinstance(no, list):
        for x in no:
            yield from textos(x)
    elif isinstance(no, dict):
        for k, x in no.items():
            if k != "frase":
                yield from textos(x)


MARCADOR = re.compile(r"\{([a-z_0-9]+)(?:\.([a-z_0-9]+))?\}")
AGREGADOS = {"total", "maior", "menor", "primeiro", "ultimo"}


def problemas_da_frase(frase: str, linhas: list[dict]) -> list[str]:
    """A frase de um exemplo fecha com o resultado dele? É o que agente/narrador.js exige para
    usar a frase em vez da própria."""
    cols = linhas[0].keys()
    erros = []
    for a, b in MARCADOR.findall(frase):
        if a == "n" and not b:
            continue
        if a in AGREGADOS and b:
            if b == "rotulo" and a != "total":
                continue
            if b not in cols:
                erros.append(f"{{{a}.{b}}}: coluna inexistente")
            elif a == "total" and not all(v is None or (isinstance(v, int) and not isinstance(v, bool))
                                          for v in (l[b] for l in linhas)):
                erros.append(f"{{total.{b}}}: só se soma contagem")
        elif not b and a not in cols:
            erros.append(f"{{{a}}}: coluna inexistente")
        elif b:
            erros.append(f"{{{a}.{b}}}: agregado desconhecido")
    sem_marcas = re.sub(r"[a-z]{3}/\d{4}", "", MARCADOR.sub("", frase))
    if re.search(r"\d", sem_marcas):
        erros.append("número digitado fora de marcador")
    return erros


def sql_suspeito(sql: str):
    s = sql.lower()
    if not (s.lstrip().startswith("select") or s.lstrip().startswith("with")):
        return "não começa com SELECT"
    if ";" in sql[:-1]:
        return "mais de um comando"
    for p in PROIBIDAS:
        if re.search(rf"\b{p}\b", s):
            return f'usa "{p}"'
    limite = re.search(r"\blimit\s+(\d+)", s)
    if not limite or int(limite.group(1)) > 100:
        return "sem LIMIT de até 100"
    if re.search(r"\bavg\s*\(", s):
        return "AVG sobre medida"
    return None


def eh_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def conferir(con, sem, ide, exe, ape, fatos) -> list[str]:
    erros = []

    # 3. Toda {chave} existe em fatos.
    for nome, doc in (("semantica", sem), ("identidade", ide), ("exemplos", exe)):
        for s in textos(doc):
            for chave in re.findall(r"\{([a-z_]+)\}", s):
                if chave not in fatos:
                    erros.append(f"{nome}: {{{chave}}} não existe em fatos.json")

    # 4. Colunas e medidas da semântica existem.
    reais = {t: {r["column_name"] for r in rodar(con, f"SELECT column_name FROM (DESCRIBE {t})")} for t in TABELAS}
    for tab in sem["tabelas"]:
        nomes = {c[0] for c in tab["colunas"]} | set(tab.get("medidas", []))
        for faltando in sorted(nomes - reais[tab["nome"]]):
            erros.append(f"semantica: {tab['nome']}.{faltando} não existe")
        for sobrando in sorted(reais[tab["nome"]] - nomes):
            erros.append(f"semantica: {tab['nome']}.{sobrando} existe e não está descrita")

    # 5. Exemplos.
    perguntas = set()
    for ex in exe["exemplos"]:
        p, rot = ex["plano"], ex["pergunta"]
        if normal(rot) in perguntas:
            erros.append(f"exemplo repetido: {rot}")
        perguntas.add(normal(rot))
        if p["tipo"] == "conversa":
            if not p.get("resposta") or p.get("sql"):
                erros.append(f"exemplo '{rot}': conversa precisa de resposta e não tem SQL")
            continue
        sql = sql_de(p)
        if (motivo := sql_suspeito(sql)):
            erros.append(f"exemplo '{rot}': {motivo}")
            continue
        try:
            linhas = rodar(con, sql)
        except Exception as e:  # noqa: BLE001
            erros.append(f"exemplo '{rot}': SQL falhou: {str(e).splitlines()[0]}")
            continue
        if not linhas:
            erros.append(f"exemplo '{rot}': 0 linhas")
            continue
        cols = linhas[0].keys()
        for eixo in ("x", "y"):
            if p.get(eixo) not in cols:
                erros.append(f"exemplo '{rot}': {eixo}={p.get(eixo)!r} não é coluna do resultado")
        if p.get("grafico") not in GRAFICOS:
            erros.append(f"exemplo '{rot}': gráfico {p.get('grafico')!r}")
        if p.get("unidade") not in UNIDADES:
            erros.append(f"exemplo '{rot}': unidade {p.get('unidade')!r}")
        slot = MEDIDA_EM.get(p.get("grafico"))
        if slot and p.get(slot) in cols and not eh_num(linhas[0][p[slot]]):
            erros.append(f"exemplo '{rot}': {slot} tem de ser a medida em {p['grafico']}")
        if not p.get("frase"):
            erros.append(f"exemplo '{rot}': consulta sem frase")
        else:
            erros += [f"exemplo '{rot}': frase {e}" for e in problemas_da_frase(p["frase"], linhas)]

    # 6. Apelidos.
    aero = {r["icao"]: r for r in rodar(con, "SELECT icao, nome, municipio FROM dim_aerodromo")}
    marcas = {r["marca"] for r in rodar(con, "SELECT DISTINCT marca FROM dim_empresa WHERE marca IS NOT NULL")}
    ufs = {r["uf"]: r["estado"] for r in rodar(con, "SELECT DISTINCT uf, estado FROM dim_aerodromo WHERE uf IS NOT NULL")}
    vistos = {}
    for grupo, chave in (("aerodromos", "icao"), ("marcas", "marca"), ("estados", "uf")):
        for item in ape[grupo]:
            alvo = item[chave]
            existe = alvo in (aero if grupo == "aerodromos" else marcas if grupo == "marcas" else ufs)
            if not existe:
                erros.append(f"apelidos: {chave} {alvo} não existe na base")
                continue
            for a in item["apelidos"]:
                if a != a.lower() or normal(a).lower() != a:
                    erros.append(f"apelidos: '{a}' tem de estar minúsculo e sem acento")
                if vistos.setdefault(a, alvo) != alvo:
                    erros.append(f"apelidos: '{a}' aponta para {vistos[a]} e {alvo}")
                if item["fonte"] == "base":
                    onde = (f"{aero[alvo]['nome']} {aero[alvo]['municipio']}" if grupo == "aerodromos"
                            else ufs.get(alvo, "") if grupo == "estados" else alvo)
                    if normal(a) not in normal(onde):
                        erros.append(f"apelidos: '{a}' (fonte base) não aparece em {alvo}: {onde}")
    return erros


# ─────────────────────────────────────────────────────────────────────────────

def main() -> int:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--atualizar-manifest", action="store_true")
    args = p.parse_args()

    con = abrir_banco()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    calculados = calcular_fatos(con)
    if args.atualizar_manifest:
        manifest["fatos"] = calculados
        MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        print("manifest.json: fatos gravados")
    erros = []
    if manifest.get("fatos") != calculados:
        erros.append("manifest.fatos não bate com os Parquet (rode o export de novo, ou "
                     "--atualizar-manifest se o export é anterior ao bloco de fatos)")
    else:
        fatos = gerar_fatos(manifest)
        destino = AQUI / "fatos.json"
        novo = {"sobre": "Gerado por conferir.py a partir de agente/dados/manifest.json — não editar à mão.",
                "manifest_gerado_em": manifest["gerado_em"], "fatos": fatos}
        texto = json.dumps(novo, ensure_ascii=False, indent=2) + "\n"
        if not destino.exists() or destino.read_text(encoding="utf-8") != texto:
            destino.write_text(texto, encoding="utf-8")
            print("fatos.json: regenerado")
        erros += conferir(con, ler("semantica.json"), ler("identidade.json"), ler("exemplos.json"),
                          ler("apelidos.json"), fatos)
    exe = ler("exemplos.json")["exemplos"]
    print(f"{len(exe)} exemplos ({sum(1 for e in exe if e.get('chip'))} perguntas prontas), "
          f"{len(calculados)} grupos de fatos no manifest")
    for e in erros:
        print("  XX", e)
    print("tudo confere" if not erros else f"\n{len(erros)} problema(s)")
    return 1 if erros else 0


if __name__ == "__main__":
    sys.exit(main())
