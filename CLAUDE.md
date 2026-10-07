# CLAUDE.md

Data warehouse dos voos da ANAC no Databricks (Bronze → Silver → Gold) e um agente público que
responde perguntas sobre ele numa página estática. Visão geral e decisões no [README](README.md).

## Onde fica cada coisa

- **`agente/conhecimento/`** — a base de conhecimento: a única fonte do que o agente sabe. O Worker
  importa no build, a página carrega como arquivo estático. Detalhes no [README de lá](agente/conhecimento/README.md).
  - `semantica.json` — tabelas, colunas, métricas, problemas da fonte, regras de SQL
  - `identidade.json` — quem o agente é, o que não responde, gatilhos e respostas fixas, a regra da frase
  - `exemplos.json` — pergunta → plano (SQL e frase), conferidos; `chip: true` vira pergunta pronta
  - `apelidos.json` — GRU, Congonhas, Viracopos…; cada um com a fonte
  - `fatos.json` — **gerado** do `agente/dados/manifest.json` pelo `conferir.py`; não edite à mão
  - `montar.js` — transforma os JSON em prompt
- `agente/roteador.js` — o que responde sem IA, do mais barato ao mais caro: texto fixo → pergunta
  pronta → template; o resto vai ao Worker.
- `agente/narrador.js` — o texto da resposta, com os números da consulta, e o verificador de números.
- `agente/worker/` — Cloudflare Worker: guarda a chave e monta o prompt ([README](agente/worker/README.md)).
- `agente/avaliacao/` — 31 perguntas com gabarito no DuckDB; mede acerto, rota, latência e chamadas.
- `agente/dados/` — 5 Parquet + `manifest.json`, exportados da Gold por
  `databricks/Agents/Exportar Fato do Agente.py`.
- `agente/index.html` — a página: chat, DuckDB-WASM e gráficos.

## Regras do agente

- **Número de dado não se digita.** No prompt e nos textos fixos ele entra como `{chave}` e vem de
  `fatos.json`.
- **Número na resposta só sai da consulta.** O modelo devolve SQL e uma `frase` com marcadores
  (`{total.voos}`); o narrador preenche e descarta o texto com número que não está nas linhas, nas
  somas, no SQL, na pergunta ou nos fatos.
- **O que dá para responder sem IA não vai à IA.** Pergunta nova que se repete vira exemplo ou
  template, não prompt maior. Template só com entidade sem ambiguidade; na dúvida, vai à IA.
- **Preserve:** SQL rodando no navegador, nunca no Worker; o Worker recebendo só a pergunta e a
  conversa; `sqlSuspeito()`; as travas de custo (por IP, por dia, disjuntor, prazos); a resposta em
  JSON estruturado.
- Não troque provedor nem modelo sem pedir.
- O que não dá para conferir nos dados entra como **[A CONFIRMAR]**, não como fato.

## Como verificar

```bash
node --test "agente/**/*.test.mjs"                  # roteador, narrador, montagem do prompt
python agente/conhecimento/conferir.py              # fatos, colunas, exemplos executados, apelidos
python agente/avaliacao/avaliar.py seco             # o corretor reprova os defeitos plantados
python agente/avaliacao/avaliar.py offline NOME     # as 31 perguntas, sem rede nem cota
```

`avaliar.py ao-vivo` chama a IA de verdade e precisa de `agente/worker/.dev.vars`. O free tier é
pequeno: uma ou duas chamadas por mudança bastam.

## Convenções

- PT-BR em tudo: código, comentários, documentação e commits, com o tipo em português
  (`funcionalidade:`, `correção:`, `documentação:`, `desempenho:`, `refatoração:`, `teste:`).
- Commits só com o autor do repositório, sem linhas de co-autoria.
- `git push` e `wrangler deploy` só a pedido, a cada vez.
- Repositório público: nenhuma chave, nenhum conteúdo de fora dele. A chave vai em
  `npx wrangler secret put` ou em `agente/worker/.dev.vars`, que o git ignora.
- Meça antes de mudar; mudanças pequenas.
