"""Avaliação do agente público: o que ele responde, por onde, em quanto tempo e a que custo de cota.

    python agente/avaliacao/avaliar.py gabarito [--conferir]
    python agente/avaliacao/avaliar.py seco
    python agente/avaliacao/avaliar.py ao-vivo RODADA --worker REV [--chave-falsa] [--ids a,b]
    python agente/avaliacao/avaliar.py relatorio RODADA

gabarito   roda no DuckDB o SQL de cada alternativa e grava os valores-chave em perguntas.json.
           --conferir só compara com o que está gravado e sai com 1 se algo mudou.
seco       corrige respostas montadas aqui mesmo, sem rede e sem cota, e prova que o avaliador
           reprova o que tem de reprovar — inclusive o 322.327 do print.
ao-vivo    sobe o `wrangler dev` com o medidor, faz as perguntas marcadas "ao_vivo" do jeito que a
           página faz e grava tudo em gravacoes/RODADA.json. É a única parte que gasta cota.
           --worker escolhe a versão: um commit (a linha de base se mede no original, não numa
           imitação dele) ou "atual", a cópia de trabalho.
relatorio  corrige uma gravação e escreve relatorios/RODADA.md, sem rede.
"""
from __future__ import annotations

import argparse
import datetime as dt
import decimal
import io
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
import tomllib
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path

AQUI = Path(__file__).resolve().parent
AGENTE = AQUI.parent
RAIZ = AGENTE.parent
DADOS = AGENTE / "dados"
WORKER = AGENTE / "worker"
PERGUNTAS = AQUI / "perguntas.json"
GRAVACOES = AQUI / "gravacoes"
RELATORIOS = AQUI / "relatorios"
ALVO = AQUI / ".alvo"          # versão do Worker sob teste e estado do wrangler dev; fora do git

PORTA = 8787
BASE = f"http://127.0.0.1:{PORTA}"
ORIGEM = "http://127.0.0.1:8000"
TABELAS = ["fato_voos", "dim_empresa", "dim_aerodromo", "dim_rota", "dim_tempo"]
POSTS_POR_MINUTO = 6           # REQUISICOES_POR_MINUTO_POR_IP do Worker: o avaliador respeita
SEMPRE_CONHECIDOS = [2025.0, 2026.0]


class Falha(Exception):
    """O que a página mostraria como erro, no lugar da resposta."""


# ─── Dados ────────────────────────────────────────────────────────────────────

def carregar() -> dict:
    return json.loads(PERGUNTAS.read_text(encoding="utf-8"))


def abrir_banco():
    import duckdb
    con = duckdb.connect()
    for t in TABELAS:
        # Igual à página: a dimensão de aeródromos ganha o rótulo de reserva.
        sel = "SELECT *, COALESCE(municipio, nome, icao) AS rotulo" if t == "dim_aerodromo" else "SELECT *"
        con.execute(f"CREATE VIEW {t} AS {sel} FROM read_parquet('{(DADOS / f'{t}.parquet').as_posix()}')")
    return con


def normalizar(v):
    """Os tipos que a página enxerga: o rodar() dela converte BigInt e INT128 em number."""
    if isinstance(v, decimal.Decimal):
        return float(v)
    if isinstance(v, float) and not math.isfinite(v):
        return None
    if v is None or isinstance(v, (bool, int, float, str)):
        return v
    return str(v)


def rodar(con, sql: str) -> list[dict]:
    cur = con.execute(sql)
    cols = [d[0] for d in cur.description]
    return [{c: normalizar(v) for c, v in zip(cols, linha)} for linha in cur.fetchall()]


def eh_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def texto_normal(s) -> str:
    s = unicodedata.normalize("NFKD", str(s or ""))
    s = "".join(c for c in s if not unicodedata.combining(c)).upper()
    return re.sub(r"\s+", " ", s).strip()


def br(v, casas: int = 0) -> str:
    return f"{v:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")


# ─── Números no texto ─────────────────────────────────────────────────────────
# Formato brasileiro: ponto de milhar, vírgula decimal, "mil"/"milhões" por extenso. O que vem
# colado em letra (AD4512), depois de barra (ago/2025) ou de ponto/vírgula não é número solto.

NUMERO = re.compile(r"""
    (?<![\w/.,])
    (?P<n>\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:,\d+)?)
    (?:\s*(?P<escala>mil|milh(?:ão|ões|ao|oes)|bilh(?:ão|ões|ao|oes))(?!\w))?
    (?![\w/])
""", re.X | re.I)


def ler(m) -> tuple[float, float]:
    """(valor, tolerância). A tolerância é meia unidade da última casa escrita: "73,8" cobre
    73,75 a 73,85, e "317 mil" cobre 316.500 a 317.500."""
    inteiro, _, decimais = m.group("n").replace(".", "").partition(",")
    valor = float(f"{inteiro}.{decimais}" if decimais else inteiro)
    escala = (m.group("escala") or "").lower()
    fator = 1e3 if escala == "mil" else 1e6 if escala.startswith("milh") else 1e9 if escala else 1.0
    return valor * fator, 0.5 * 10 ** -len(decimais) * fator + 1e-9


def numeros_em(texto: str) -> list[float]:
    return [ler(m)[0] for m in NUMERO.finditer(texto or "")]


def fatos_da_fonte(js: str, conhecimento: list[str]) -> list[float]:
    """Números que a versão sob teste entrega ao modelo: os do prompt digitado no worker.js e
    os da base de conhecimento daquela versão. Citar um deles não é inventar — mesmo que o fato
    esteja errado, que é outro problema e é medido em outro lugar."""
    vals = set()
    for bloco in re.findall(r"const \w+ = `([\s\S]*?)`;", js):
        vals.update(round(v, 6) for v in numeros_em(bloco))
    for texto in conhecimento:
        vals.update(round(v, 6) for v in numeros_em(texto))
    return sorted(vals)


def conhecimento_da_versao(rev: str) -> list[str]:
    """Os JSON de agente/conhecimento/ como eram naquela versão (nenhum, antes de existirem)."""
    if rev == "atual":
        pasta = AGENTE / "conhecimento"
        return [a.read_text(encoding="utf-8") for a in sorted(pasta.glob("*.json"))] if pasta.is_dir() else []
    nomes = git("ls-tree", "--name-only", rev, "agente/conhecimento/").split()
    return [git("show", f"{rev}:{n}") for n in nomes if n.endswith(".json")]


def numeros_do_resultado(linhas: list[dict]) -> list[float]:
    """Toda célula numérica e a soma de cada coluna: um total certo é número da consulta,
    um total errado (o 322.327) não é."""
    vals = [float(v) for l in linhas for v in l.values() if eh_num(v)]
    if len(linhas) > 1:
        for c in linhas[0]:
            col = [float(l[c]) for l in linhas if eh_num(l.get(c))]
            if col:
                vals.append(sum(col))
    return vals


def desconhecidos(texto: str, conhecidos: list[float]) -> list[str]:
    fora = []
    for m in NUMERO.finditer(texto or ""):
        v, tol = ler(m)
        if tol < 0.51 and v.is_integer() and 0 <= v <= 31:
            continue          # contagem pequena, dia, posição: "os 3 maiores", "em 12 meses"
        if not any(abs(v - k) <= tol for k in conhecidos):
            fora.append(m.group(0).strip())
    return fora


# ─── Correção ─────────────────────────────────────────────────────────────────

def faltando(alt: dict, linhas: list[dict]) -> list[str]:
    numeros = numeros_do_resultado(linhas)
    textos = [texto_normal(v) for l in linhas for v in l.values() if isinstance(v, str)]
    falta = []
    for chave, esperado in alt["valores"].items():
        if esperado is None:
            continue
        if chave.startswith("rotulo"):
            if not any(texto_normal(esperado) in t for t in textos):
                falta.append(f"{chave} {esperado}")
            continue
        e = float(esperado)
        tol = 0.5 if e.is_integer() else max(0.051, abs(e) * 5e-4)
        if not any(abs(e - v) <= tol for v in numeros):
            falta.append(f"{chave} {br(e, 0 if e.is_integer() else 2)}")
    return falta


def corrigir(q: dict, r: dict, fatos: list[float]) -> dict:
    esp = q["esperado"]
    conhecidos = (numeros_do_resultado(r.get("linhas") or []) + fatos
                  + numeros_em(q["pergunta"]) + SEMPRE_CONHECIDOS)
    fora = desconhecidos(r.get("texto") or "", conhecidos)
    if r.get("erro"):
        ok, motivo = False, f"erro: {r['erro'][:90]}"
    elif esp.get("conversa"):
        if r.get("tipo") != "conversa":
            ok, motivo = False, "virou consulta"
        elif esp.get("diz_que_nao") and "NAO" not in re.findall(r"\w+", texto_normal(r.get("texto"))):
            ok, motivo = False, "não diz que o dado não existe"
        else:
            ok, motivo = True, ""
    elif r.get("tipo") != "consulta":
        ok, motivo = False, "respondeu em prosa"
    elif not r.get("linhas"):
        ok, motivo = False, "0 linhas"
    else:
        faltas = [faltando(a, r["linhas"]) for a in esp["alternativas"]]
        melhor = min(faltas, key=len)
        ok, motivo = (not melhor), ("" if not melhor else "falta " + "; ".join(melhor))
    return {"ok": ok, "motivo": motivo, "desconhecidos": fora}


# ─── gabarito ─────────────────────────────────────────────────────────────────

def cmd_gabarito(args) -> int:
    dados = carregar()
    con = abrir_banco()
    mudou = []
    for q in dados["perguntas"]:
        for alt in q["esperado"].get("alternativas", []):
            linhas = rodar(con, alt["sql"])
            if len(linhas) != 1:
                raise SystemExit(f"{q['id']}: o SQL do gabarito tem de devolver uma linha, devolveu {len(linhas)}")
            valores = {k: (round(v, 6) if isinstance(v, float) else v) for k, v in linhas[0].items()}
            if any(v is None for v in valores.values()):
                raise SystemExit(f"{q['id']}: valor NULL no gabarito ({alt['nota']})")
            if alt.get("valores") != valores:
                mudou.append(q["id"])
            print(f"  {q['id']:<15} {alt['nota']:<34} {valores}")
            if not args.conferir:
                alt["valores"] = valores
    if args.conferir:
        print("\nconferido: nada mudou" if not mudou else f"\nMUDOU: {sorted(set(mudou))}")
        return 1 if mudou else 0
    PERGUNTAS.write_text(json.dumps(dados, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n{PERGUNTAS.name} atualizado")
    return 0


# ─── seco ─────────────────────────────────────────────────────────────────────

def cmd_seco(args) -> int:
    """Respostas montadas aqui, cada uma com o veredito que o avaliador TEM de dar."""
    dados = carregar()
    pq = {q["id"]: q for q in dados["perguntas"]}
    con = abrir_banco()
    fatos = fatos_da_fonte((WORKER / "worker.js").read_text(encoding="utf-8"), conhecimento_da_versao("atual"))
    casos = []

    # Certas: o próprio gabarito como resultado, narrado com os valores dele.
    for q in dados["perguntas"]:
        if q["esperado"].get("conversa"):
            casos.append(("certa", q, {"tipo": "conversa", "linhas": [],
                                       "texto": "Não tenho esse dado na base. Pergunte sobre voos, empresas ou aeroportos."}, True))
            continue
        linhas = rodar(con, q["esperado"]["alternativas"][0]["sql"])
        nums = [v for v in linhas[0].values() if eh_num(v)]
        texto = "Resultado: " + ", ".join(br(v, 0 if float(v).is_integer() else 1) for v in nums) + "."
        casos.append(("certa", q, {"tipo": "consulta", "linhas": linhas, "texto": texto}, True))

    # Erradas, cada uma com o defeito que já aconteceu ou que o prompt tenta evitar.
    sql_sp = ("SELECT a.rotulo AS aeroporto, SUM(f.voos) AS voos FROM fato_voos f JOIN dim_aerodromo a "
              "ON f.icao_origem = a.icao WHERE a.uf = '{uf}' GROUP BY 1 ORDER BY voos DESC LIMIT 20")
    linhas_sp = rodar(con, sql_sp.format(uf="SP"))
    casos += [
        ("SP certo, total somado", pq["sp_todos"], {"tipo": "consulta", "linhas": linhas_sp,
         "texto": "Os 16 aeroportos do estado somam 317.327 partidas; Guarulhos lidera com 147.976 (cerca de 317 mil no total)."}, True),
        ("SP com o 322.327 do print", pq["sp_todos"], {"tipo": "consulta", "linhas": linhas_sp,
         "texto": "Os 16 aeroportos do estado somam 322.327 partidas; Guarulhos lidera com 147.976."}, False),
        ("uf por extenso: 0 linhas", pq["sp_todos"], {"tipo": "consulta", "texto": "",
         "linhas": rodar(con, sql_sp.format(uf="São Paulo"))}, False),
        ("LATAM pela razão social", pq["latam_voos"], {"tipo": "consulta", "texto": "",
         "linhas": rodar(con, "SELECT SUM(f.voos) AS voos FROM fato_voos f JOIN dim_empresa e "
                              "ON f.icao_empresa = e.icao_empresa WHERE e.nome ILIKE '%LATAM%'")}, False),
        ("motivo inventado em SQL", pq["motivo"], {"tipo": "consulta", "texto": "",
         "linhas": [{"motivo": "N/A", "cancelados": 29145}]}, False),
        ("número inventado na conversa", pq["oi"], {"tipo": "conversa", "linhas": [],
         "texto": "Olá! Já respondi 1.234 perguntas hoje."}, False),
        ("fora do grão sem dizer que não", pq["por_dia"], {"tipo": "conversa", "linhas": [],
         "texto": "Em dezembro foram 85.452 voos."}, False),
        ("erro da página", pq["gru_voos"], {"tipo": None, "linhas": [], "texto": "",
         "erro": "A IA gratuita não respondeu"}, False),
    ]

    errados = 0
    for nome, q, r, deve in casos:
        c = corrigir(q, r, fatos)
        aprovou = c["ok"] and not c["desconhecidos"]
        if aprovou != deve or nome != "certa":
            marca = "ok " if aprovou == deve else "XX "
            print(f"  {marca}{nome:<32} {q['id']:<15} aprovou={aprovou!s:<5} {c['motivo']} {c['desconhecidos'] or ''}")
        errados += aprovou != deve
    certas = sum(1 for n, *_ in casos if n == "certa")
    print(f"\n{len(casos) - errados} de {len(casos)} vereditos certos "
          f"({certas} respostas certas aprovadas e {len(casos) - certas} defeitos plantados)")
    return 1 if errados else 0


# ─── ao vivo ──────────────────────────────────────────────────────────────────

def git(*args) -> str:
    return subprocess.run(["git", "-C", str(RAIZ), *args], check=True, capture_output=True,
                          text=True, encoding="utf-8").stdout


def preparar_alvo(rev: str) -> tuple[str, Path, dict]:
    """Monta .alvo/entrada.js: a versão escolhida do Worker, embrulhada pelo medidor. As
    variáveis do wrangler.toml daquela versão vão por --var, para os prazos serem os dela."""
    ALVO.mkdir(exist_ok=True)
    if rev == "atual":
        fonte = (WORKER / "worker.js").read_text(encoding="utf-8")
        importar = "../../worker/worker.js"
        toml = (WORKER / "wrangler.toml").read_text(encoding="utf-8")
    else:
        fonte = git("show", f"{rev}:agente/worker/worker.js")
        (ALVO / "worker.js").write_text(fonte, encoding="utf-8")
        importar = "./worker.js"
        toml = git("show", f"{rev}:agente/worker/wrangler.toml")
    entrada = ALVO / "entrada.js"
    entrada.write_text(f'import worker from "{importar}";\nimport {{ medir }} from "../medidor.js";\n'
                       "export default medir(worker);\n", encoding="utf-8")
    return fonte, entrada, tomllib.loads(toml).get("vars", {})


class Servidor:
    """`wrangler dev` local com o medidor. O KV é simulado e começa zerado a cada rodada."""

    def __init__(self, entrada: Path, variaveis: dict, chave_falsa: bool):
        self.entrada, self.variaveis, self.chave_falsa = entrada, variaveis, chave_falsa

    def __enter__(self):
        estado = ALVO / "estado"
        shutil.rmtree(estado, ignore_errors=True)
        cmd = [shutil.which("npx") or "npx", "--yes", "wrangler@4", "dev", str(self.entrada),
               "--config", str(WORKER / "wrangler.toml"), "--ip", "127.0.0.1", "--port", str(PORTA),
               "--persist-to", str(estado), "--log-level", "warn"]
        for k, v in self.variaveis.items():
            cmd += ["--var", f"{k}:{v}"]
        if self.chave_falsa:
            cmd += ["--var", "GEMINI_API_KEY:chave-falsa-da-avaliacao"]
        self.log = open(ALVO / "wrangler.log", "w", encoding="utf-8")
        self.proc = subprocess.Popen(cmd, cwd=WORKER, stdout=self.log, stderr=subprocess.STDOUT,
                                     stdin=subprocess.DEVNULL)
        limite = time.time() + 240
        while time.time() < limite:
            if self.proc.poll() is not None:
                raise SystemExit(f"o wrangler dev saiu; veja {ALVO / 'wrangler.log'}")
            try:
                urllib.request.urlopen(BASE + "/saude", timeout=5)
                return self
            except urllib.error.HTTPError:
                return self            # respondeu: 500 é só configuração, o servidor está de pé
            except Exception:
                time.sleep(1)
        self.__exit__()
        raise SystemExit("o wrangler dev não respondeu em 4 minutos")

    def __exit__(self, *_):
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(self.proc.pid), "/T", "/F"], capture_output=True)
        else:
            self.proc.terminate()
        self.log.close()


class Cliente:
    def __init__(self):
        self.posts: list[float] = []

    def _ritmo(self):
        """O Worker conta POSTs por minuto do relógio. Acima de 6 ele responde 429 — e a
        avaliação mediria a trava, não o agente."""
        while True:
            agora = time.time()
            minuto = int(agora // 60)
            if sum(1 for t in self.posts if int(t // 60) == minuto) < POSTS_POR_MINUTO:
                break
            time.sleep((minuto + 1) * 60 - agora + 0.5)
        self.posts.append(time.time())

    def _pedido(self, rota: str, corpo: dict):
        return urllib.request.Request(
            BASE + rota, method="POST", data=json.dumps(corpo, ensure_ascii=False).encode("utf-8"),
            headers={"content-type": "application/json", "Origin": ORIGEM})

    def consulta(self, corpo: dict) -> tuple[int, dict, float]:
        self._ritmo()
        t0 = time.time()
        try:
            with urllib.request.urlopen(self._pedido("/consulta", corpo), timeout=150) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8")), time.time() - t0
        except urllib.error.HTTPError as e:
            bruto = e.read().decode("utf-8", "replace")
            try:
                j = json.loads(bruto)
            except ValueError:
                j = {"erro": bruto[:300]}
            return e.code, j, time.time() - t0

    def narrar(self, corpo: dict) -> dict:
        self._ritmo()
        t0 = time.time()
        r = {"status": None, "texto": "", "segundos": None, "primeiro_pedaco": None, "erro": None, "modelo": None}
        try:
            with urllib.request.urlopen(self._pedido("/narrar", corpo), timeout=150) as resp:
                r["status"], r["modelo"] = resp.status, resp.headers.get("x-modelo")
                for bruta in resp:
                    linha = bruta.decode("utf-8").strip()
                    if not linha.startswith("data:"):
                        continue
                    ev = json.loads(linha[5:])
                    if ev.get("t"):
                        r["texto"] += ev["t"]
                        r["primeiro_pedaco"] = r["primeiro_pedaco"] or round(time.time() - t0, 2)
                    if ev.get("erro"):
                        r["erro"] = ev["erro"]
                    if ev.get("fim"):
                        break
        except urllib.error.HTTPError as e:
            r["status"] = e.code
            try:
                r["erro"] = json.loads(e.read().decode("utf-8", "replace")).get("erro")
            except ValueError:
                r["erro"] = f"HTTP {e.code}"
        except Exception as e:  # noqa: BLE001 — a página também trata qualquer falha igual
            r["erro"] = str(e)
        r["segundos"] = round(time.time() - t0, 2)
        return r

    def medidas(self) -> list[dict]:
        with urllib.request.urlopen(BASE + "/__medidas", timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def saude(self) -> dict:
        try:
            with urllib.request.urlopen(BASE + "/saude", timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return json.loads(e.read().decode("utf-8", "replace"))


def executar(con, sql: str) -> list[dict]:
    try:
        return rodar(con, sql)
    except Exception as e:  # noqa: BLE001 — erro do DuckDB vira a mensagem que a página mostraria
        raise Falha(f"SQL: {str(e).splitlines()[0][:160]}") from None


def perguntar_como_a_pagina(cli: Cliente, con, q: dict) -> dict:
    """O ask() da página na linha de base, passo a passo: todo texto digitado vai ao Worker."""
    hist = q.get("historico", [])
    r = {"id": q["id"], "pergunta": q["pergunta"], "rota": "ia", "passos": [], "planos": [],
         "tipo": None, "texto": "", "sql": None, "linhas": [], "erro": None, "revisada": False}
    t0 = time.time()

    def pedir_plano(historico, revisao=False) -> dict:
        # pedirPlano(): repete uma vez, depois de 2,5 s, só o 503 que falhou rápido (< 10 s).
        for tentativa in (1, 2):
            st, corpo, seg = cli.consulta({"pergunta": q["pergunta"], "historico": historico})
            r["passos"].append({"rota": "/consulta", "revisao": revisao, "tentativa": tentativa,
                                "status": st, "segundos": round(seg, 2), "provedor": cli.medidas(),
                                "erro": None if st == 200 else corpo.get("erro"),
                                "detalhe": None if st == 200 else corpo.get("detalhe")})
            if st == 200:
                r["planos"].append(corpo)
                return corpo
            if st == 503 and tentativa == 1 and seg < 10:
                time.sleep(2.5)
                continue
            raise Falha(corpo.get("erro") or f"HTTP {st}")
        raise Falha("sem plano")

    try:
        plano = pedir_plano(hist)
        if plano.get("tipo") == "conversa":
            r["tipo"], r["texto"] = "conversa", plano.get("resposta", "")
        else:
            r["tipo"] = "consulta"
            linhas = executar(con, plano["sql"])
            if not linhas:
                # A revisão de consulta vazia: uma chamada a mais, com a tentativa no histórico.
                r["revisada"] = True
                novo = pedir_plano(hist + [{"pergunta": q["pergunta"], "sql": plano["sql"],
                                            "amostra": [], "total": 0}], revisao=True)
                if novo.get("tipo") == "conversa":
                    r["tipo"], r["texto"], plano = "conversa", novo.get("resposta", ""), None
                elif novo.get("sql") and novo["sql"] != plano["sql"]:
                    plano = novo
                    linhas = executar(con, plano["sql"])
            if plano is not None:
                r["sql"], r["linhas"] = plano["sql"], linhas[:100]
                if not linhas:
                    r["texto"] = "A consulta não encontrou nenhuma linha. O SQL está abaixo para conferir."
                else:
                    n = cli.narrar({"pergunta": q["pergunta"], "sql": plano["sql"], "linhas": linhas[:40],
                                    "aviso": plano.get("aviso") or "", "historico": hist})
                    n["provedor"] = cli.medidas()
                    r["passos"].append({"rota": "/narrar", **{k: v for k, v in n.items() if k != "texto"}})
                    if n["status"] == 200 and not n["erro"] and n["texto"]:
                        r["texto"] = n["texto"]
                    else:
                        r["narracao_falhou"] = True      # a página mostraria frase(), que só usa a tabela
    except Falha as e:
        r["erro"] = str(e)
    r["segundos"] = round(time.time() - t0, 2)
    return r


def cmd_ao_vivo(args) -> int:
    dados = carregar()
    ids = set(args.ids.split(",")) if args.ids else None
    alvo = [q for q in dados["perguntas"] if (q["id"] in ids if ids else q.get("ao_vivo"))]
    fonte, entrada, variaveis = preparar_alvo(args.worker)
    con = abrir_banco()
    print(f"worker {args.worker} · {len(alvo)} perguntas · subindo o wrangler dev…", flush=True)
    with Servidor(entrada, variaveis, args.chave_falsa):
        cli = Cliente()
        saude = cli.saude()
        cli.medidas()
        resultados = []
        for q in alvo:
            r = perguntar_como_a_pagina(cli, con, q)
            chamadas = sum(len(p.get("provedor") or []) for p in r["passos"])
            print(f"  {q['id']:<15} {r['segundos']:6.1f} s · {r['tipo'] or '-':<9} · {chamadas} chamada(s)"
                  f"{' · ' + r['erro'][:70] if r['erro'] else ''}", flush=True)
            resultados.append(r)
    gravacao = {
        "rodada": args.rodada,
        "quando": dt.datetime.now().isoformat(timespec="seconds"),
        "worker": args.worker if args.worker == "atual" else git("rev-parse", "--short", args.worker).strip(),
        "chave_falsa": args.chave_falsa,
        "saude": saude,
        "fatos_do_prompt": fatos_da_fonte(fonte, conhecimento_da_versao(args.worker)),
        # Linha de base: a página não tem roteador, então TODO texto digitado vai à IA.
        "rotas_de_todas": {q["id"]: "ia" for q in dados["perguntas"]},
        "resultados": resultados,
    }
    GRAVACOES.mkdir(exist_ok=True)
    (GRAVACOES / f"{args.rodada}.json").write_text(json.dumps(gravacao, ensure_ascii=False, indent=1) + "\n",
                                                  encoding="utf-8")
    return relatorio(args.rodada)


# ─── relatório ────────────────────────────────────────────────────────────────

def percentil(vals: list[float], p: float):
    if not vals:
        return None
    v = sorted(vals)
    return v[max(0, math.ceil(p * len(v)) - 1)]


def seg(v) -> str:
    return "-" if v is None else br(v, 1) + " s"


def cmd_relatorio(args) -> int:
    return relatorio(args.rodada)


def relatorio(rodada: str) -> int:
    grav = json.loads((GRAVACOES / f"{rodada}.json").read_text(encoding="utf-8"))
    pq = {q["id"]: q for q in carregar()["perguntas"]}
    fatos = grav["fatos_do_prompt"]
    linhas, respostas, por_modelo = [], [], {}
    acertos = textos_ok = 0
    tempos, chamadas_q, posts_q, pensou = [], [], [], []
    reservas = rodadas_extras = 0
    for r in grav["resultados"]:
        q = pq[r["id"]]
        c = corrigir(q, r, fatos)
        acertos += c["ok"]
        textos_ok += not c["desconhecidos"]
        provedor = [ch for p in r["passos"] for ch in (p.get("provedor") or [])]
        chamadas_q.append(len(provedor))
        posts_q.append(len(r["passos"]))
        tempos.append(r["segundos"])
        for pl in r.get("planos", []):
            reservas += bool(pl.get("reserva"))
            rodadas_extras += (pl.get("rodadas") or 1) > 1
        for ch in provedor:
            m = por_modelo.setdefault(ch["modelo"], {"n": 0, "ok": 0, "503": 0, "429": 0, "abortada": 0,
                                                     "outro": 0, "entrada": [], "pensou": 0})
            m["n"] += 1
            chave = ("ok" if ch["desfecho"] == "ok" else "abortada" if ch["desfecho"] == "abortada"
                     else str(ch["status"]) if str(ch["status"]) in ("503", "429") else "outro")
            m[chave] += 1
            uso = ch.get("uso") or {}
            if uso.get("promptTokenCount"):
                m["entrada"].append(uso["promptTokenCount"])
            if uso.get("thoughtsTokenCount"):
                m["pensou"] += uso["thoughtsTokenCount"]
                pensou.append(ch["modelo"])
        entrada = [ (ch.get("uso") or {}).get("promptTokenCount") for p in r["passos"] if p["rota"] == "/consulta"
                    for ch in (p.get("provedor") or []) if (ch.get("uso") or {}).get("promptTokenCount")]
        linhas.append(f"| {r['id']} | {q['rota']} | {r.get('rota', 'ia')} | {'✓' if c['ok'] else '✗ ' + c['motivo']} "
                      f"| {seg(r['segundos'])} | {len(provedor)} | {len(r['passos'])} "
                      f"| {br(entrada[0]) if entrada else '-'} | {', '.join(c['desconhecidos']) or '-'} |")
        texto = (r.get("texto") or r.get("erro") or "").replace("\n", " ")
        respostas.append(f"- **{r['id']}** ({r['pergunta']}) — {texto[:260]}"
                         + (f"\n  `{r['sql'][:220]}`" if r.get("sql") else ""))

    n = len(grav["resultados"]) or 1
    rotas = grav.get("rotas_de_todas", {})
    sem_ia = sum(1 for v in rotas.values() if v != "ia")
    s = grav.get("saude") or {}
    md = [
        f"# Avaliação — {rodada}",
        "",
        f"Worker `{grav['worker']}` · {grav['quando']}"
        + (" · **chave falsa (teste de encanamento)**" if grav.get("chave_falsa") else ""),
        f"Modelo `{s.get('modelo')}`, reservas `{', '.join(s.get('reservas') or [])}`, narração "
        f"`{s.get('modelo_narracao')}` · prazo do /consulta {s.get('prazo_consulta_ms')} ms, reserva aos "
        f"{s.get('atraso_reserva_ms')} ms",
        "",
        "| Medida | Valor |",
        "|---|---|",
        f"| Acerto (o dado certo na tela) | {acertos} de {n} ({br(100 * acertos / n)}%) |",
        f"| Texto sem número inventado | {textos_ok} de {n} |",
        f"| Latência por pergunta | p50 {seg(percentil(tempos, .5))} · p95 {seg(percentil(tempos, .95))} · máx {seg(max(tempos) if tempos else None)} |",
        f"| Chamadas ao provedor por pergunta | média {br(sum(chamadas_q) / n, 1)} · máx {max(chamadas_q) if chamadas_q else 0} |",
        f"| Requisições que o KV conta, por pergunta | média {br(sum(posts_q) / n, 1)} |",
        f"| Respondidas sem IA, das {len(rotas)} perguntas | {sem_ia} ({br(100 * sem_ia / max(1, len(rotas)))}%) |",
        f"| Reserva atrasada disparou | {reservas} de {sum(len(r.get('planos', [])) for r in grav['resultados'])} planos |",
        f"| Planos que precisaram de mais de uma rodada | {rodadas_extras} |",
        f"| Chamadas com raciocínio (thoughtsTokenCount > 0) | {len(pensou)} de {sum(chamadas_q)} |",
        "",
        "## Por pergunta",
        "",
        "| id | rota esperada | rota | acerto | tempo | chamadas | POSTs | tokens de entrada | número fora |",
        "|---|---|---|---|---|---|---|---|---|",
        *linhas,
        "",
        "## Chamadas ao provedor, por modelo",
        "",
        "| modelo | chamadas | ok | 503 | 429 | abortadas | outras | entrada média (tokens) | tokens de raciocínio |",
        "|---|---|---|---|---|---|---|---|---|",
        *[f"| {m} | {v['n']} | {v['ok']} | {v['503']} | {v['429']} | {v['abortada']} | {v['outro']} "
          f"| {br(sum(v['entrada']) / len(v['entrada'])) if v['entrada'] else '-'} | {v['pensou']} |"
          for m, v in sorted(por_modelo.items())],
        "",
        "## Respostas",
        "",
        *respostas,
        "",
    ]
    RELATORIOS.mkdir(exist_ok=True)
    destino = RELATORIOS / f"{rodada}.md"
    destino.write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md[:18]))
    print(f"\nrelatório: {destino.relative_to(RAIZ)}")
    return 0


# ─────────────────────────────────────────────────────────────────────────────

def main() -> int:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("gabarito")
    g.add_argument("--conferir", action="store_true")
    sub.add_parser("seco")
    a = sub.add_parser("ao-vivo")
    a.add_argument("rodada")
    a.add_argument("--worker", required=True, help='commit (ex.: cbbeb33) ou "atual"')
    a.add_argument("--chave-falsa", action="store_true", help="testa o encanamento sem gastar cota")
    a.add_argument("--ids", help="só estas perguntas, separadas por vírgula")
    r = sub.add_parser("relatorio")
    r.add_argument("rodada")
    args = p.parse_args()
    return {"gabarito": cmd_gabarito, "seco": cmd_seco, "ao-vivo": cmd_ao_vivo,
            "relatorio": cmd_relatorio}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
