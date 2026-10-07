# Base de conhecimento do agente

Tudo o que o agente sabe sobre os dados mora aqui, em JSON, e os dois lados leem os mesmos
arquivos: o Worker importa no build (o prompt do `/consulta` e do `/narrar`) e a página carrega como
arquivo estático (as perguntas prontas, as respostas fixas e, sem Worker, o prompt). Antes, o mesmo
conhecimento estava digitado em cinco lugares, e eles já discordavam — o período, por exemplo,
estava errado em dois deles.

| Arquivo | O que é | Quem escreve |
|---|---|---|
| `semantica.json` | tabelas, colunas, métricas, problemas da fonte e regras de SQL | à mão |
| `identidade.json` | quem o agente é, o que não responde, roteamento, narração e respostas fixas | à mão |
| `exemplos.json` | pares pergunta → plano; os marcados `chip` são as perguntas prontas da página | à mão, SQL conferido |
| `apelidos.json` | sinônimos que as dimensões não têm (GRU, Congonhas, Viracopos…) | à mão, conferido |
| `fatos.json` | período, volumes e ressalvas, com o texto pronto em português | gerado do manifest |
| `montar.js` | transforma os JSON em texto de prompt — sem dependência, roda no Worker, no navegador e no Node | — |
| `conferir.py` | gera `fatos.json` e prova tudo contra os Parquet | — |

## Regras

- **Número de dado não se digita.** Ele entra como `{chave}` e vem de `fatos.json`, que sai do
  `manifest.json` do export. Chave desconhecida é erro, nunca texto vazio.
- **Depois de mexer**, rode os dois:
  `python agente/conhecimento/conferir.py` (colunas, exemplos, apelidos e fatos contra os dados) e
  `node --test "agente/**/*.test.mjs"` (montagem e orçamento do prompt, com teto e piso).
- **Exemplo novo não repete pergunta de `agente/avaliacao/`**: a avaliação mede generalização, não
  decoreba.
- **Novo export dos Parquet:** o notebook `databricks/Agents/Exportar Fato do Agente.py` grava os fatos
  no manifest; `conferir.py` refaz a mesma conta no DuckDB, exige que as duas batam e regenera
  `fatos.json`.
