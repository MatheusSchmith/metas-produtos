# Metas x Realizado de Volume · Comercial Bandeirantes

API de meta e realizado de volume de **Vol. Sucos, Vol. Powerade, Vol. Sabores e Vol. Retornáveis**, nos
níveis cliente, rota, supervisão e gerência, publicada no GitHub Pages e alimentada automaticamente pelo
**SAP Datasphere** via OData. Segue o mesmo modelo e as mesmas regras de volume (critério do SAC) do
projeto "Desempenho de Rotas" da TI, de onde vêm o cliente OData (`backend/odata/`) e as consultas.

O contrato da API (endereços e campos) para quem constrói o front está em **[API.md](API.md)**.

```
metas-produtos/
├── api/v1/                  ← a API (JSONs gerados; não edite à mão)
├── frontend/index.html      página provisória que lê a API (será substituída pelo painel)
├── backend/
│   ├── odata/               cliente OData (copiado do projeto da TI)
│   ├── gerador/
│   │   ├── mapeamento.py    produtos, colunas e filtros (o único arquivo a ajustar no dia a dia)
│   │   ├── fontes.py        consultas ao Datasphere
│   │   ├── modelo.py        contas de meta, realizado, tendência e status
│   │   ├── api.py           montagem dos JSONs
│   │   ├── validacao.py     conferência antes de publicar
│   │   └── simulado.py      dados fictícios no mesmo formato
│   ├── scripts/gerar.py     gera a API
│   ├── scripts/descobrir_produtos.py   confere a grafia dos agrupadores no Datasphere
│   └── tests/               testes sem rede (Datasphere falso)
└── .github/workflows/
    ├── atualizar-dados.yml  de hora em hora, seg-sex, 07h05-18h05 (Brasília)
    ├── deploy-pages.yml     publica frontend/ + api/ no Pages
    └── testes.yml           testes do back-end
```

## Como funciona

1. O workflow **Atualizar dados** roda de hora em hora em dias úteis.
2. `backend/scripts/gerar.py` pede um token OAuth, consulta o modelo `AM_FAT_BND_ANALISE_META`, a base
   de clientes e o calendário, calcula meta x realizado por rota e cliente, soma em supervisão, gerência
   e empresa, e **valida** o resultado.
3. Se algo mudou, o workflow faz commit em `api/` e publica o site. Se a validação reprovar, nada é
   gravado: o site continua com a última versão boa e a execução aparece como falha (log anexado).

Regras de volume (iguais às da TI): meta = META_VOLUME da rota; realizado = FX_VOL_PADRAO_FAT com
NF_STATUS em Acertado, Meta Neg ou Em Aberto; tendência = realizado + restante da curva de META_NEG;
meta do cliente = META_NEG do cliente; pedidos de hoje à parte (`online_hoje`). Detalhes em
`backend/gerador/modelo.py` e em [API.md](API.md).

## Antes de ligar: confirmar os agrupadores

Os nomes dos agrupadores ficam em `backend/gerador/mapeamento.py` → `PRODUTOS`. "Sucos" e "Powerade"
já aparecem no projeto da TI; **"Sabores" e "Retornaveis" são suposições** e precisam ser confirmados.
O nome vai no filtro da consulta, que é exato (maiúsculas e acentos contam). Com o `.env` preenchido:

```bash
cd backend
python scripts/descobrir_produtos.py
```

O relatório (`backend/saida/descoberta/produtos.md`) lista os agrupadores do mês com "suco", "powerade",
"sabor" ou "retorn" no nome, com faturado e metas, e diz quais nomes configurados não existem. Se um
produto for a soma de vários agrupadores, liste todos no mesmo produto.

## Configuração no GitHub (uma vez)

1. Crie o repositório **público** e envie este projeto (a TI e a diretoria autorizaram os dados públicos;
   no plano Free o Pages só funciona com repositório público).
2. **Settings > Secrets and variables > Actions > Secrets**: cadastre os mesmos nomes do projeto da TI:
   `DATASPHERE_CLIENT_ID`, `DATASPHERE_CLIENT_SECRET`, `DATASPHERE_TENANT_URL`, `DATASPHERE_TOKEN_URL`,
   `DATASPHERE_SPACE`, `DATASPHERE_ASSET`. Todos como Secrets, não Variables: o log da execução é
   público e só os Secrets aparecem como `***` nele.
3. **Settings > Pages**: Source = "GitHub Actions".
4. **Actions > Atualizar dados > Run workflow**: escolha `real` (ou `simulado` para publicar dados
   fictícios enquanto as credenciais não estão prontas).

Frequência: de hora em hora em dias úteis (~260 rodadas por mês, ~90 consultas ao Datasphere cada). O
repositório é público, então os minutos de Actions não têm limite; o que segura o intervalo é a carga no
Datasphere. Para mudar, ajuste o `cron` em `atualizar-dados.yml` (e `ATRASO_MAX_MIN` em `status.html`).
Se o repositório voltar a ser privado, o Free tem 2.000 min/mês: de hora em hora (~1.600 min) ainda cabe.

## Rodar localmente

```bash
cd backend
pip install -r requirements.txt
cp .env.example .env          # preencha (só para dados reais)

python scripts/gerar.py --simulado --forcar      # dados fictícios em ../api/v1
python scripts/gerar.py --forcar                 # dados reais em ../api/v1
python scripts/gerar.py --rota 111 --forcar      # uma rota só, em saida/rota_111/
python -m unittest discover -s tests -t . -v     # testes
```

Para ver a página com a API, monte a pasta como no deploy e abra `http://localhost:8000`:

```bash
mkdir -p _site && cp -r frontend/. _site/ && cp -r api _site/api
cd _site && python -m http.server 8000
```

## Manutenção

Entrou ou saiu um produto: edite `PRODUTOS` em `mapeamento.py` (o `id` vira chave nos JSONs; avise o
front), rode os testes e o `descobrir_produtos.py`. Mudou coluna no Datasphere ou regra de rota
(Neutraliza, virtuais, gerências): os mesmos nomes do projeto da TI estão em `mapeamento.py`; quando a
TI atualizar o projeto dela, replique aqui.

## Segurança

Nunca versione `backend/.env`: as credenciais ficam só nos Secrets do GitHub. Os JSONs têm nomes e
códigos de clientes, por isso o repositório e o Pages devem ser privados.
