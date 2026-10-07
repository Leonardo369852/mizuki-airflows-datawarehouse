# Avaliação do agente

Mede o que o agente público responde, por onde cada pergunta passa, quanto tempo leva e quantas
chamadas ao provedor de IA ela custa. Roda sem a página: o `avaliar.py` refaz o caminho do `ask()` e
executa o SQL no DuckDB, sobre os mesmos Parquet de `agente/dados/`.

| Arquivo | O que é |
|---|---|
| `perguntas.json` | 31 perguntas com a rota esperada (`fixa`, `pronta`, `template`, `ia`) e o gabarito: um SQL por interpretação aceita e os valores-chave que ele devolve |
| `avaliar.py` | gabarito, modo seco, rodada ao vivo e relatório |
| `medidor.js` | embrulha o Worker no `wrangler dev` e anota cada chamada ao provedor: modelo, status, tempo e tokens (inclusive os de raciocínio) |
| `gravacoes/` | o que voltou em cada rodada ao vivo — o relatório se refaz daqui, sem gastar cota |
| `relatorios/` | um `.md` por rodada |

## Rodar

```bash
python agente/avaliacao/avaliar.py gabarito --conferir    # o gabarito ainda bate com os Parquet?
python agente/avaliacao/avaliar.py seco                   # o avaliador reprova o que tem de reprovar?
python agente/avaliacao/avaliar.py ao-vivo NOME --worker atual    # gasta cota
python agente/avaliacao/avaliar.py relatorio NOME          # corrige de novo uma gravação
```

A rodada ao vivo sobe o `wrangler dev` sozinha e precisa da chave em `agente/worker/.dev.vars`
(`GEMINI_API_KEY=...`, ignorado pelo git): o secret gravado no Cloudflare não chega ao `wrangler dev`
local. Só as perguntas marcadas `ao_vivo` vão à IA. `--chave-falsa` testa o encanamento sem gastar cota
(o Google recusa a chave na hora). `--worker <commit>` mede uma versão antiga do Worker com as variáveis
do `wrangler.toml` daquela versão — é assim que a linha de base continua mensurável depois das mudanças.

O avaliador respeita a trava do Worker de 6 requisições por minuto: uma rodada de 10 perguntas leva
uns 5 minutos.

## Como corrige

- **Dado.** Os valores-chave de pelo menos uma alternativa do gabarito aparecem no resultado — numa
  célula ou como soma de uma coluna; rótulo, numa célula. Mais de uma alternativa existe quando a
  pergunta admite mais de uma leitura honesta (a LATAM do grupo ou só a brasileira; pontualidade com
  ou sem os voos sem data).
- **Conversa.** Saudação, identidade e pergunta fora do grão não podem virar consulta. Fora do grão,
  a resposta tem de dizer que o dado não existe.
- **Texto.** Todo número escrito na resposta tem de existir no resultado, na soma de uma coluna, na
  pergunta ou no conhecimento que o agente recebe, com a tolerância da última casa escrita ("73,8"
  cobre 73,75 a 73,85; "317 mil" cobre 316.500 a 317.500). Contagens até 31 passam. É a régua que
  pega o 322.327: uma soma errada não está em lugar nenhum.

`avaliar.py seco` planta esses defeitos de propósito e falha se algum passar.
