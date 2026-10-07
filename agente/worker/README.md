# Worker do agente público

Proxy de LLM entre a página estática e a IA. Existe por um motivo: **guardar a chave da API e o
prompt fora do navegador.**

A página é servida pelo GitHub Pages, então qualquer chave que ela carregasse estaria em texto
puro no `view-source`. Existem bots varrendo o GitHub 24h procurando exatamente isso. E se o
prompt viesse da página, este endpoint seria um relay de LLM aberto: aceitando só a pergunta, o
pior uso possível continua sendo perguntar sobre voos brasileiros.

```
navegador                              Cloudflare Worker                 provedor de IA
─────────                              ─────────────────                 ──────────────
roteador.js responde sem IA o que dá
(texto pronto, pergunta pronta, template)
o resto ─────────────────────────────▶ POST /consulta ─────────────────▶ {tipo, sql, gráfico,
                                       prompt montado de                  aviso, frase}
                                       agente/conhecimento/, com os 4
                                       exemplos mais parecidos
DuckDB executa o SQL localmente
narrador.js preenche a frase com os números da consulta
```

O SQL **não roda no Worker**. Ele volta para a página e é executado pelo DuckDB-WASM no
navegador do visitante, em memória, sobre cinco Parquet estáticos. Não existe banco para atacar.

**Não existe `/narrar`.** O texto da resposta vem no próprio plano, como uma `frase` com marcadores
no lugar dos números (`"Os {n} aeroportos somam {total.voos} partidas"`), e a página a preenche com
o resultado. A rota antiga recebia as linhas e escrevia o texto numa segunda chamada à IA — e somou
16 linhas como 322.327 quando eram 317.327.

---

## O prompt

Montado no build por [`../conhecimento/montar.js`](../conhecimento/montar.js), a partir dos JSON de
[`../conhecimento/`](../conhecimento/): a semântica (tabelas, métricas, problemas da fonte, regras de
SQL), a identidade em duas linhas e os limites do grão, o roteamento e a regra da frase. Por pergunta
entram os exemplos mais parecidos (`EXEMPLOS_NO_PROMPT`) e a conversa. Número de dado não é digitado:
vem de `fatos.json`, gerado do manifest do export. Mudar o que o agente sabe é mudar esses arquivos,
não este.

---

## Instalar

Precisa de [Node](https://nodejs.org) e uma conta Cloudflare (grátis).

### 1. Chave da IA

**Gemini** (recomendado — free tier real, sem cartão): pegue em
[aistudio.google.com/apikey](https://aistudio.google.com/apikey).

**Claude** (pago): pegue em [console.anthropic.com](https://console.anthropic.com) e troque
`PROVEDOR` para `anthropic` no `wrangler.toml`.

### 2. Criar o KV

```bash
npx wrangler kv namespace create CONTADORES
```

Cole o `id` devolvido no `wrangler.toml`.

### 3. Guardar a chave como secret

```bash
npx wrangler secret put GEMINI_API_KEY
```

Cola a chave quando pedir. Ela vai criptografada para o Cloudflare — **não** fica no
`wrangler.toml` e **não** entra no repositório. Para Claude, o nome é `ANTHROPIC_API_KEY`.

### 4. Publicar

```bash
npx wrangler deploy
```

Devolve a URL, algo como `https://mizuki-agente.SEU-USUARIO.workers.dev`. Aponte a página para ela
na constante `WORKER` de [`../index.html`](../index.html).

---

## Conferir

```bash
curl https://mizuki-agente.SEU-USUARIO.workers.dev/saude
```

Não gasta chamada de modelo. Além da configuração, mostra o dia — um trecho:

```json
{ "ok": true, "modelo": "gemini-3.6-flash", "gasto_hoje": 12, "limite_diario": 150,
  "prazo_consulta_ms": 20000, "rodadas_consulta": 2, "exemplos_no_prompt": 4,
  "disjuntor": { "falhas_para_pausar": 3, "pausa_ms": 300000, "falhas_seguidas": 0, "pausado_ate": null },
  "hoje": { "perguntas": 12, "do_cache": 3,
            "chamadas": { "gemini-3.6-flash": { "200": 10, "503": 2 }, "gemini-3.1-flash-lite": { "200": 2, "perdeu": 1 } },
            "tokens": { "gemini-3.6-flash": { "n": 10, "entrada": 34000, "raciocinio": 0, "saida": 1900 } },
            "reserva": { "disparou": 1, "venceu": 1 } } }
```

`chamadas` é o que a cota do provedor gasta: uma pergunta pode custar mais de uma (a reserva
atrasada, a segunda rodada). `raciocinio` soma o `thoughtsTokenCount` de cada modelo e prova se o
`thinkingBudget: 0` está valendo. `/saude?testar=1` faz uma chamada mínima de verdade, e
`/modelos` lista os modelos que a chave aceita.

Uma pergunta de ponta a ponta:

```bash
curl -X POST https://mizuki-agente.SEU-USUARIO.workers.dev/consulta \
  -H 'content-type: application/json' \
  -d '{"pergunta":"qual a rota com mais voos?"}'
```

---

## Travas

Endpoint público é endpoint abusável, e o free tier é pequeno.

| Trava | Onde | Valor |
|---|---|---|
| Requisições por minuto por IP | `REQUISICOES_POR_MINUTO_POR_IP` | 6 |
| Perguntas à IA por dia (o cache não conta) | `LIMITE_DIARIO` (`wrangler.toml`) | 150 |
| Prazo do `/consulta` | `PRAZO_CONSULTA_MS`, `RODADAS_CONSULTA` | 20 s, 2 rodadas |
| Prazo de cada tentativa | `PRAZO_TENTATIVA_MS` | 12 s |
| Disjuntor | `DISJUNTOR_FALHAS`, `DISJUNTOR_PAUSA_MS` | 3 falhas seguidas → 5 min sem IA |
| Cache de plano | KV, 7 dias | pergunta sem conversa |
| Tamanho da pergunta | `MAX_CARACTERES_PERGUNTA` | 300 |
| Saída do modelo | `maxTokens` | 900 |
| Origem permitida | `ORIGENS_PERMITIDAS` | GitHub Pages + localhost |
| SQL | `sqlSuspeito()` | só um `SELECT`, com `LIMIT` |

Com o disjuntor aberto ou o teto do dia estourado, o Worker responde na hora, sem chamar o
provedor, e a página oferece as perguntas prontas — que nunca dependeram da IA.

### O que o KV guarda

| Chave | O quê | Vida |
|---|---|---|
| `ip:<ip>:<minuto>` | requisições daquele IP no minuto | 2 min |
| `dia:<AAAA-MM-DD>` | um JSON: perguntas, chamadas por modelo e desfecho, tokens, reserva, disjuntor | 2 dias |
| `plano:<hash>` | o plano de uma pergunta sem conversa; a chave muda com o export e com o prompt | 7 dias |

O plano gratuito do KV escreve pouco por dia e uma vez por segundo na mesma chave, por isso o dia
inteiro mora numa chave só e cada requisição grava uma vez, no fim (`waitUntil`). Plano que volta
vazio na página é apagado quando ela pede a revisão, e o "tentar de novo" pula o cache.

**Ressalva honesta:** o KV é eventualmente consistente, então numa rajada simultânea a contagem
pode subestimar por alguns segundos. Para um portfólio é irrelevante — o que importa é que ninguém
roda mil perguntas num laço. `ORIGENS_PERMITIDAS` restringe o navegador, não o `curl`; quem segura
abuso via linha de comando são os contadores.

---

## Trocar de IA depois

Mude `PROVEDOR` e `MODELO` no `wrangler.toml`, grave a secret nova, `wrangler deploy`. **A página não
muda uma linha** — ela só conhece o `/consulta`.

---

## Desenvolver e medir local

```bash
npx wrangler dev
```

Sobe em `http://localhost:8787`. O secret gravado no Cloudflare **não** chega ao `wrangler dev`
local: a chave tem de estar em `agente/worker/.dev.vars` (`GEMINI_API_KEY=...`), que o git ignora.
Sirva a página em `http://localhost:8000` (`python -m http.server 8000` a partir de `agente/`) —
essa origem já está liberada no CORS.

Para medir acerto, latência e chamadas ao provedor, use a [avaliação](../avaliacao/): ela sobe o
`wrangler dev` sozinha, com um medidor que anota cada chamada, e grava as respostas para corrigir
de novo sem gastar cota.
