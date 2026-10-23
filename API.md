# API de Metas x Realizado de Volume

Guia para quem vai construir o front. A API é um conjunto de arquivos JSON estáticos, publicados no
mesmo site do GitHub Pages que a página. Do `frontend/index.html`, os endereços são relativos:

```js
const BASE = "./api/v1/";
const index = await fetch(BASE + "index.json", { cache: "no-cache" }).then(r => r.json());
```

Use sempre caminhos relativos (`./api/v1/...`). O site é restrito a funcionários, e o login do GitHub
vale para este site; uma página hospedada em outro endereço não consegue ler estes arquivos.

## Atualização

Os arquivos são regerados de hora em hora, de segunda a sexta, das 7h05 às 18h05 (Brasília). Só o
`index.json` muda em toda execução (traz `atualizado_em`); os outros só mudam quando o dado muda. Para
atualizar a tela sem recarregar a página, releia o `index.json` de tempos em tempos (5 a 15 minutos) e,
quando `atualizado_em` mudar, releia os arquivos que estiverem na tela.

## Arquivos

| Arquivo | Conteúdo |
|---|---|
| `index.json` | Data/hora, mês de referência, calendário, lista de produtos, gerências e nomes dos status. Leia primeiro. |
| `resumo.json` | Total da empresa e de cada gerência, por produto. Tela inicial. |
| `gerencias/{GC}.json` | Uma gerência: total, supervisões e rotas, por produto. `{GC}` vem de `index.json` → `gerencias[].id`. |
| `rotas/{ROTA}.json` | Uma rota: total e clientes, por produto. `{ROTA}` vem de `gerencias/{GC}.json` → `rotas[].id`. |
| `busca.json` | Todos os clientes em formato compacto, para busca por nome ou código. |

## Meta por Agrupador e por cliente (`especies/`)

Usado por `frontend/especies.html` (meta por Agrupador Produto (Meta SAP), até rota) e `frontend/clientes.html`
(Meta NEG por cliente). Meta, Meta NEG e Meta Dia pela dimensão Meta SAP (mês em `ANOMES_REF_Chave_Meta_SAP`,
agrupador em `AGRUPADOR_PRODU_Chave_Meta_SAP`); o realizado segue o Flash de Vendas. Os nomes dos agrupadores são
os mesmos nos dois lados.

| Arquivo | Conteúdo |
|---|---|
| `especies/index.json` | `meses[]`: `anomes`, `rotulo` e `arquivo` (mês de referência e os 2 anteriores). |
| `especies/{AAAAMM}.json` | `gerencias[]`, `supervisoes[]` (`id`, `gerencia`, `nome`), `rotas[]` (`id`, `gerencia`, `supervisao`, `vendedor`, `arquivo`), `busca` e `linhas` no formato de `campos`: `[agrupador, gerencia, supervisao, rota, meta, realizado, realizado_hoje, meta_dia]`. |
| `especies/{AAAAMM}/{ROTA}.json` | Clientes da rota: `clientes[]` (`pv`, `nome`) e `linhas` `[agrupador, cliente, realizado, realizado_hoje, meta_dia, meta_neg]`. Leia pelo `arquivo` de `rotas[]`. |
| `especies/{AAAAMM}/_busca.json` | Índice para procurar cliente: `clientes` `[pv, nome, rota]` do mês. |

| Campo | Medida no Datasphere |
|---|---|
| `meta` (até rota) | `META_VOLUME_Chave_Meta_SAP`, somada uma vez por chave da Meta SAP (rota, agrupador, segmento, gerência, supervisão). |
| `meta_neg` (cliente) | `META_NEG`. A soma dos clientes de uma rota fecha com a `meta` da rota. A chave da Meta SAP não tem cliente. |
| `realizado` | Regra do **Flash de Vendas** (relatório pai): `FX_VOL_PADRAO_FAT` do mês da venda (`ANOMES_REF`) com `DATA_MOVIMENTO` antes de hoje (mês inteiro em mês que não é o de hoje), pelo agrupador do produto (`DS_AGRUPADOR_Agrupador_Prod`), só `NF_STATUS` Acertado/Meta Neg/Em Aberto e sem clientes sem gerência (`DS_GC_AGRUPADA_ATUAL_Clien` = `--`). Rota, supervisão e gerência do cliente. |
| `realizado_hoje` | "Volume Hoje": `VL_PADRAO` com `DATA_MOVIMENTO` = hoje (faturado de hoje + pedidos de hoje no WF Online, só 'Inc. e Exp.'), com os mesmos filtros de cliente. |
| `meta_dia` | "Meta Dia" = "Meta Recuperável Rota": `META_RECUPERAVEL_ROTA` com `DATA_MOVIMENTO` = hoje (data em `meta_dia_em`; zerada em mês que não é o de hoje). |

Um produto pode estar em mais de um agrupador (ex.: Refrigerantes e Sabores Tt): some agrupadores só sabendo que
o volume se repete. A gerência é a da Meta SAP, de origem (`IT_MO`, `PA_DI`, `UR_RI`, `GU_PO` vêm juntas;
`--` = sem gerência). O realizado bate com o Flash de Vendas (conferido em 23/10/2026).

## O bloco de indicador (rota, supervisão, gerência e empresa)

Todo nível tem um objeto `produtos` com uma chave por produto (`sucos`, `powerade`, `sabores`,
`retornaveis`, na ordem de `index.json` → `produtos`). Cada produto traz sempre os mesmos campos:

```json
{
  "meta": 2180.7,
  "realizado": 1312.6,
  "atingimento_pct": 60,
  "diferenca": -868.1,
  "tendencia": 2039.5,
  "tendencia_pct": 94,
  "meta_dia": 103.8,
  "online_hoje": 162.8,
  "status": "abaixo_do_ritmo"
}
```

| Campo | Significado |
|---|---|
| `meta` | Meta de volume do mês (META_VOLUME da rota; nos níveis acima, a soma das rotas). |
| `realizado` | Volume faturado no mês (notas com status válido, critério do SAC). Não inclui os pedidos de hoje. |
| `atingimento_pct` | `realizado / meta`, inteiro. |
| `diferenca` | `realizado - meta` (negativo = quanto falta). |
| `tendencia` | Projeção de fechamento: realizado + parte da meta ainda prevista para os dias que faltam. |
| `tendencia_pct` | `tendencia / meta`, inteiro. |
| `meta_dia` | Meta de hoje (o que precisa vender hoje para recuperar o ritmo). |
| `online_hoje` | Volume dos pedidos de hoje ainda não faturados (WF Online, só pedidos válidos). |
| `status` | `meta_batida`, `no_ritmo`, `abaixo_do_ritmo` ou `sem_meta` (textos em `index.json` → `status`). |

Regras do `status` nos níveis rota, supervisão, gerência e empresa: `meta_batida` quando
`atingimento_pct >= 100`; senão `no_ritmo` quando `tendencia_pct >= 100`; senão `abaixo_do_ritmo`.
`sem_meta` quando não há meta (os campos numéricos vêm `null`).

Volume é sempre em volume padrão (`index.json` → `unidade`), com uma casa decimal.

## O bloco do cliente

Dentro de `rotas/{ROTA}.json` → `clientes[].produtos`:

```json
{ "meta": 27.1, "realizado": 6.6, "atingimento_pct": 24, "diferenca": -20.5, "online_hoje": 0.0,
  "status": "abaixo_do_ritmo" }
```

A meta do cliente é a META_NEG dele no mês. O cliente não tem tendência: ele fica `no_ritmo` quando o
`atingimento_pct` alcança o ritmo esperado (`index.json` → `calendario.ritmo_esperado_pct`, o % de dias
úteis já fechados). A soma das metas dos clientes pode diferir um pouco da meta da rota, porque a meta
oficial da rota é a META_VOLUME (como no SAC).

Clientes com `"na_base": false` tiveram venda ou meta na rota, mas não estão mais ativos na base
(vêm sem nome). O front pode mostrá-los separados ou escondê-los.

## Tipos de rota

Cada rota tem `tipo`: `normal`, `neutraliza`, `virtual` ou `eventual`. Todas entram nos totais de
supervisão e gerência, como no SAC. As `eventual` (ex.: `G1-EV`) juntam o realizado de clientes
atendidos por rotas eventuais (EV*): não têm meta nem clientes. Sugestão: listar só as `normal` e
`neutraliza`, e deixar as demais apenas nos totais.

## Fechamento do mês

Do 1º dia do mês até o fim do 1º dia útil (e enquanto alguma gerência ainda não tiver meta do mês
novo), a API mostra o mês anterior fechado: `index.json` → `mes_referencia.fechamento = true`, e
`tendencia`, `tendencia_pct`, `meta_dia` e `online_hoje` vêm `null`. Mostre o rótulo
`mes_referencia.rotulo` (ex.: "Setembro/26") para deixar claro qual mês está na tela.

## Exemplos de estrutura

`index.json` (resumido):

```json
{
  "versao_api": "1",
  "atualizado_em": "2026-10-22T16:38:57",
  "simulado": false,
  "mes_referencia": { "anomes": "202610", "rotulo": "Outubro/26", "fechamento": false },
  "calendario": { "hoje": "2026-10-22", "dias_uteis_mes": 21, "dia_util_hoje": 15,
                  "dias_uteis_fechados": 14, "dias_uteis_restantes": 7, "ritmo_esperado_pct": 67 },
  "produtos": [ { "id": "sucos", "nome": "Vol. Sucos" }, "..." ],
  "status": { "meta_batida": "Meta batida", "no_ritmo": "No ritmo", "abaixo_do_ritmo": "Abaixo do ritmo",
              "sem_meta": "Sem meta" },
  "gerencias": [ { "id": "G1", "nome": "Goiânia 01", "arquivo": "gerencias/G1.json" }, "..." ],
  "avisos": []
}
```

`gerencias/G1.json`:

```json
{
  "gerencia": { "id": "G1", "nome": "Goiânia 01" },
  "produtos": { "sucos": { "...": "bloco" } },
  "supervisoes": [ { "id": "SV.G1.1", "nome": "NOME DO SUPERVISOR", "rotas": ["111", "112"],
                     "produtos": { "...": "bloco" } } ],
  "rotas": [ { "id": "111", "tipo": "normal", "gerencia": "G1", "supervisao": "SV.G1.1",
               "vendedor": "NOME DO VENDEDOR", "produtos": { "...": "bloco" } } ]
}
```

`rotas/111.json`:

```json
{
  "rota": { "id": "111", "tipo": "normal", "gerencia": "G1", "supervisao": "SV.G1.1",
            "vendedor": "NOME DO VENDEDOR", "nome_supervisor": "NOME DO SUPERVISOR" },
  "produtos": { "...": "bloco" },
  "clientes": [ { "pv": 1007382, "nome": "NOME FANTASIA", "segmento": "Boteco", "na_base": true,
                  "produtos": { "sucos": { "...": "bloco do cliente" } } } ]
}
```

`busca.json`:

```json
{ "campos": ["pv", "nome", "rota", "gerencia"],
  "clientes": [ [1007382, "NOME FANTASIA", "111", "G1"] ] }
```

## Dados simulados

Enquanto as credenciais do Datasphere não estão configuradas, a API pode ser gerada com dados
fictícios (`"simulado": true` no `index.json`; aviso também em `avisos`). Mostre um aviso bem visível
quando `simulado` for `true`. Para gerar na sua máquina: `python scripts/gerar.py --simulado --forcar`
na pasta `backend/`, e abra o site com `python -m http.server` numa pasta com `frontend/` e `api/`
montados como no deploy (veja o README).
