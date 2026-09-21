# Worker do agente público

Proxy de LLM entre a página estática e a IA. Existe por um motivo só: **guardar a chave da API
fora do navegador.**

A página é servida pelo GitHub Pages, então qualquer chave que ela carregasse estaria em texto
puro no `view-source`. Existem bots varrendo o GitHub 24h procurando exatamente isso.

```
navegador                    Cloudflare Worker              provedor de IA
─────────                    ─────────────────              ──────────────
pergunta ──────────────────▶ POST /consulta ──────────────▶ devolve {sql, grafico, ...}
                             (prompt + chave ficam aqui)
DuckDB executa o SQL
localmente, sem credencial

linhas ────────────────────▶ POST /narrar ────────────────▶ texto em streaming
                                                            (SSE reempacotado)
```

O SQL **não roda no Worker**. Ele volta para a página e é executado pelo DuckDB-WASM no
navegador do visitante, em memória, sobre cinco Parquet estáticos. Não existe banco para atacar.

---

## Instalar

Precisa de [Node](https://nodejs.org) e uma conta Cloudflare (grátis).

### 1. Chave da IA

**Gemini** (recomendado — free tier real, sem cartão): pegue em
[aistudio.google.com/apikey](https://aistudio.google.com/apikey).
Limites do free tier nos modelos Flash: ~10 requisições/min, ~1.500/dia.

**Claude** (pago, ~US$ 0,004 por pergunta neste desenho): pegue em
[console.anthropic.com](https://console.anthropic.com) e troque `PROVEDOR` para `anthropic`
no `wrangler.toml`.

### 2. Criar o KV dos contadores

```bash
npx wrangler kv namespace create CONTADORES
```

Cole o `id` devolvido no `wrangler.toml`, no lugar de `PREENCHER_COM_O_ID_DO_KV`.

### 3. Guardar a chave como secret

```bash
npx wrangler secret put GEMINI_API_KEY
```

Cola a chave quando pedir. Ela vai criptografada para o Cloudflare — **não** fica no
`wrangler.toml` e **não** entra no repositório.

Para Claude, o nome é `ANTHROPIC_API_KEY`.

### 4. Publicar

```bash
npx wrangler deploy
```

Devolve a URL, algo como `https://mizuki-agente.SEU-USUARIO.workers.dev`.

### 5. Apontar a página para ela

Em [`../index.html`](../index.html), na constante `WORKER`.

---

## Conferir

```bash
curl https://mizuki-agente.SEU-USUARIO.workers.dev/saude
```

```json
{ "ok": true, "provedor": "gemini", "modelo": "gemini-2.5-flash",
  "gasto_hoje": 12, "limite_diario": 400 }
```

Uma pergunta de ponta a ponta:

```bash
curl -X POST https://mizuki-agente.SEU-USUARIO.workers.dev/consulta \
  -H 'content-type: application/json' \
  -d '{"pergunta":"qual empresa tem a maior taxa de cancelamento?"}'
```

Se `ok: false`, o campo `erro` diz o que falta — quase sempre a secret não foi gravada.

---

## Travas contra fatura surpresa

Endpoint público é endpoint abusável. As proteções estão em `worker.js`:

| Trava | Onde | Valor |
|---|---|---|
| Requisições por minuto por IP | `REQUISICOES_POR_MINUTO_POR_IP` | 6 |
| Teto de chamadas por dia | `LIMITE_DIARIO` (`wrangler.toml`) | 400 |
| Tamanho da pergunta | `MAX_CARACTERES_PERGUNTA` | 300 |
| Saída do modelo | `maxTokens` por rota | 700 / 400 |
| Origem permitida | `ORIGENS_PERMITIDAS` | GitHub Pages + localhost |
| Prompt no servidor | `SCHEMA`, `REGRAS_*` | não vem do cliente |

Estourado o teto do dia, o Worker devolve 429 com mensagem amigável e a página mostra que os
gráficos continuam funcionando. Nenhuma chamada paga acontece depois disso.

**Ressalva honesta:** o KV do Cloudflare é eventualmente consistente, então numa rajada
simultânea a contagem pode subestimar por alguns segundos. Para um portfólio é irrelevante — o
que importa é que ninguém roda mil perguntas num laço. Se precisar de precisão, o binding
nativo de Rate Limiting do Cloudflare resolve.

`ORIGENS_PERMITIDAS` restringe o navegador, não o `curl` — CORS é uma proteção do browser, não
do servidor. Quem bloqueia abuso via linha de comando são os contadores.

---

## Trocar de IA depois

Mude `PROVEDOR` e `MODELO` no `wrangler.toml`, grave a secret nova, `wrangler deploy`.
**A página não muda uma linha** — ela só conhece as duas rotas.

Modelos Gemini disponíveis para a sua chave:

```bash
curl "https://generativelanguage.googleapis.com/v1beta/models?key=SUA_CHAVE" \
  | python -c "import json,sys; [print(m['name']) for m in json.load(sys.stdin)['models']]"
```

---

## Desenvolver local

```bash
npx wrangler dev
```

Sobe em `http://localhost:8787`. Sirva a página em `http://localhost:8000`
(`python -m http.server 8000` a partir de `agente/`) — essa origem já está liberada no CORS.
