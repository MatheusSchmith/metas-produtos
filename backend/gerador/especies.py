"""
especies.py — Meta x realizado por Agrupador Produto (Meta SAP), até rota e cliente (telas de filtros do front).

    v1/especies/index.json                 meses disponíveis
    v1/especies/<AAAAMM>.json              linhas por agrupador, gerência, supervisão e rota (meta = Meta SAP),
                                           mais os nomes de supervisões e rotas
    v1/especies/<AAAAMM>/<ROTA>.json       linhas por agrupador e cliente da rota (meta = META_NEG)
    v1/especies/<AAAAMM>/_busca.json       [código, nome, rota] de cada cliente do mês (busca por cliente)

Tudo pela dimensão Meta SAP, como na história do SAC: linhas por AGRUPADOR_PRODU_Chave_Meta_SAP e filtro de mês
em ANOMES_REF_Chave_Meta_SAP. Conferido com o SAC em 23/10/2026 (rota A11: Powerade 424,56, Refrigerantes
Retornavel 4.173,29).

Até a rota a meta é META_VOLUME_Chave_Meta_SAP. No OData ela é atributo (dimensão): o servidor devolve uma linha
por combinação distinta, então somamos uma vez por chave da Meta SAP (rota, agrupador, segmento, gerência,
supervisão). Por agrupador não há sobreposição (antes, por marca do produto, a meta de vários agrupadores se
somava: a marca Powerade levava a meta de Still + Powerade).
No cliente a meta é a META_NEG (meta negociada; a soma dos clientes fecha com a meta da rota). A chave da Meta
SAP não tem cliente.

Realizado = regra do relatório Flash de Vendas (relatório pai; conferido em 23/10/2026, os 9 agrupadores batem):
FX_VOL_PADRAO_FAT com o mês da venda (ANOMES_REF), DATA_MOVIMENTO antes de hoje, pelo agrupador do PRODUTO
(DS_AGRUPADOR_Agrupador_Prod, mesmos nomes do agrupador da Meta SAP), só NF_STATUS em M.STATUS_NF_REAL e sem
clientes sem gerência (DS_GC_AGRUPADA_ATUAL_Clien = '--'; em out/26, o cliente 1224796 da rota EXT). A rota,
supervisão e gerência são as do cliente (CD_ROTA_Clien...), trocadas pelas da Meta SAP quando a rota tem meta.
"Volume Hoje" = VL_PADRAO com DATA_MOVIMENTO = hoje (faturado de hoje + pedidos de hoje no WF Online, só
'Inc. e Exp.'), com os mesmos filtros de cliente.
"Meta Dia" = "Meta Recuperável Rota" (META_RECUPERAVEL_ROTA) com DATA_MOVIMENTO = hoje, pela Meta SAP (bate com a
"Meta Recuperável Hoje" do Flash). Em mês que não é o de hoje a Meta Dia e o Volume Hoje ficam zerados e o
realizado é o mês inteiro. Cada medida vem numa consulta à parte: juntas, o Datasphere responde com erro interno.

O mês de referência é regerado a cada execução; os anteriores (MESES_HISTORICO) só quando ainda não existem
na pasta de destino (o realizado de mês fechado não muda).
"""
from __future__ import annotations

import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from collections import defaultdict
from datetime import date
from pathlib import Path

from gerador import calendario as calmod
from gerador import fontes
from gerador import mapeamento as M
from gerador import saida
from gerador.consulta import Consulta, e, eq, ou
from gerador.mapeamento import ColMeta as CM
from gerador.texto import inteiro, limpar, numero, titulo
from odata.cliente import ErroOData

log = logging.getLogger(__name__)

MESES_HISTORICO = 2   # além do mês de referência

AGRUPADOR = CM.META_AGRUPADOR   # "Agrupador Produto (Meta SAP)"
META_GC = "DS_GC_AGRUPADA__Chave_Meta_SAP"
META_SV = "DS_SUPERVISAO_Chave_Meta_SAP"
META_SEGMENTO = "AGRUPADOR_SEGME_Chave_Meta_SAP"
CHAVE_META = [CM.META_ROTA, AGRUPADOR, META_SEGMENTO, META_GC, META_SV]
VERSAO = 5   # muda quando o conteúdo dos arquivos muda: força refazer os meses anteriores já gravados
CLI_SV = "DS_SUPERVISOR_ATUAL_Clien"
COM_GERENCIA = f"{CM.GC} ne '--'"        # o Flash não conta cliente sem gerência
NOMES_MEDIDAS = ["realizado", "realizado_hoje", "meta_dia"]
CAMPOS = ["agrupador", "gerencia", "supervisao", "rota", "meta", *NOMES_MEDIDAS]
CAMPOS_CLIENTE = ["agrupador", "cliente", *NOMES_MEDIDAS, "meta_neg"]
SEM = "--"


def _gc(valor: object) -> str:
    """'Gc. G1' -> 'G1'; 'Gc. It_Mo' -> 'IT_MO'; vazio -> '--'."""
    return M.codigo_gc(valor) or SEM


def _sv(valor: object) -> str:
    """'Sv. G3. 1' -> 'SV.G3.1'; vazio -> '--'."""
    return M.codigo_sv(valor) or SEM


def _rota(valor: object) -> str:
    return limpar(valor).upper() or SEM


def arquivo_rota(rota: str) -> str:
    """Nome de arquivo seguro para o código da rota."""
    return re.sub(r"[^A-Za-z0-9_-]", "_", rota)


def _nome_gc(gc: str) -> str:
    if gc == SEM:
        return "Sem gerência"
    siglas = M.GC_SIGLAS_ORIGEM.get(gc, [gc])
    return " / ".join(M.GC_NOMES.get(s, s) for s in siglas)


def _chave_rota(l: dict) -> tuple:
    return (limpar(l.get(AGRUPADOR)), _gc(l.get(META_GC)), _sv(l.get(META_SV)), _rota(l.get(CM.META_ROTA)))


def _meta(cons: Consulta, anomes: str) -> dict[tuple, float]:
    sel = [*CHAVE_META, CM.META_VOLUME]
    vistos: set[tuple] = set()
    meta: dict[tuple, float] = defaultdict(float)
    for l in cons.linhas(M.OBJ_META, sel, eq(CM.META_ANOMES, anomes)):
        chave = tuple(l.get(c) for c in sel)
        if chave not in vistos:
            vistos.add(chave)
            meta[_chave_rota(l)] += numero(l.get(CM.META_VOLUME))
    return meta


def _linhas(cons: Consulta, *args) -> list[dict]:
    """cons.linhas com uma nova tentativa em erro 500: com várias consultas pesadas ao mesmo tempo, o Datasphere às
    vezes responde 500 depois de processar (o cliente OData só repete o 500 rápido)."""
    try:
        return cons.linhas(*args)
    except ErroOData as erro:
        if erro.status != 500:
            raise
        log.warning("Erro 500 do Datasphere em %s; nova tentativa em 15 s", args[1][-1])
        time.sleep(15)
        return cons.linhas(*args)


def _paralelo(cons: Consulta, tarefas: dict[str, tuple]) -> dict[str, list[dict]]:
    with ThreadPoolExecutor(max_workers=min(cons.cfg.max_workers, max(1, len(tarefas)))) as ex:
        futuros = {nome: ex.submit(_linhas, cons, *args) for nome, args in tarefas.items()}
        return {nome: fut.result() for nome, fut in futuros.items()}


def _hoje_no_mes(ref: date, hoje: date | None) -> bool:
    return hoje is not None and (hoje.year, hoje.month) == (ref.year, ref.month)


def _metas_meta_sap(cons: Consulta, ref: date, hoje: date | None, dims: list[str], medidas: list[str],
                    filtros: dict[str, str | None], chave) -> dict:
    """Medidas pela Meta SAP (mês da meta), uma consulta por medida e filtro: {chave(l): [soma de cada medida]}.
    META_RECUPERAVEL_ROTA (Meta Dia) só existe hoje: fora do mês de hoje não é consultada."""
    no_mes = _hoje_no_mes(ref, hoje)
    mes = eq(CM.META_ANOMES, ref.strftime("%Y%m"))
    tarefas = {}
    for n, f in filtros.items():
        for i, m in enumerate(medidas):
            if m == CM.META_RECUPERAVEL and not no_mes:
                continue
            dia = fontes.filtro_hoje(cons, hoje) if m == CM.META_RECUPERAVEL else None
            tarefas[f"{n}|{i}"] = (M.OBJ_META, [*dims, m], e(mes, f, dia))
    soma: dict = defaultdict(lambda: [0.0] * len(medidas))
    for nome, linhas in _paralelo(cons, tarefas).items():
        i = int(nome.rsplit("|", 1)[1])
        for l in linhas:
            k = chave(l)
            if k is not None:
                soma[k][i] += numero(l.get(medidas[i]))
    return soma


def _flash(cons: Consulta, ref: date, hoje: date | None, ags: list[str], dims: list[str],
           filtros: dict[str, str | None], chave) -> dict:
    """Realizado e Volume Hoje pela regra do Flash (ver o topo): {chave(l): [realizado, realizado_hoje]}. Só os
    agrupadores `ags` (os da Meta SAP do mês): o agrupador do produto tem centenas de outros ("Total", "Total Ko"...)
    que não entram no Flash e multiplicariam as linhas."""
    base = e(eq(CM.ANOMES, ref.strftime("%Y%m")), COM_GERENCIA, ou(CM.AGRUPADOR, ags))
    no_mes = _hoje_no_mes(ref, hoje)
    antes = f"{CM.DATA} lt {fontes.literal_data(cons, hoje)}" if no_mes else None
    tarefas = {}
    for n, f in filtros.items():
        tarefas[f"{n}|0"] = (M.OBJ_META, [*dims, CM.NF_STATUS, CM.VOL_MES], e(base, f, antes))
        if no_mes:
            tarefas[f"{n}|1"] = (M.OBJ_META, [*dims, "VL_PADRAO"],
                                 e(base, f, fontes.filtro_hoje(cons, hoje), M.FILTRO_PEDIDOS_ONLINE))
    soma: dict = defaultdict(lambda: [0.0, 0.0])
    for nome, linhas in _paralelo(cons, tarefas).items():
        i = int(nome.rsplit("|", 1)[1])
        for l in linhas:
            if i == 0 and not M.status_nf_real(l.get(CM.NF_STATUS)):
                continue
            k = chave(l)
            if k is not None:
                soma[k][i] += numero(l.get(CM.VOL_MES if i == 0 else "VL_PADRAO"))
    return soma


def _medidas(cons: Consulta, ref: date, hoje: date | None, ags: list[str], meta_rotas: dict) -> dict[tuple, list[float]]:
    """{(agrupador, gc, sv, rota): [realizado, realizado_hoje, meta_dia]}. Gerência/supervisão do realizado: as da
    Meta SAP quando a rota tem meta (`meta_rotas`), senão as do cliente."""
    def chave_cli(l):
        rota = _rota(l.get(CM.ROTA))
        gc, sv = meta_rotas.get(rota) or (_gc(l.get(CM.GC)), _sv(l.get(CLI_SV)))
        return (limpar(l.get(CM.AGRUPADOR)), gc, sv, rota)

    real = _flash(cons, ref, hoje, ags, [CM.AGRUPADOR, CM.GC, CLI_SV, CM.ROTA], {"mes": None}, chave_cli)
    dia = _metas_meta_sap(cons, ref, hoje, [AGRUPADOR, META_GC, META_SV, CM.META_ROTA], [CM.META_RECUPERAVEL],
                          {"mes": None}, _chave_rota)
    return {k: [*real.get(k, [0.0, 0.0]), dia.get(k, [0.0])[0]] for k in set(real) | set(dia)}


def _distintos(cons: Consulta, col: str, filtro: str) -> list[str]:
    linhas = cons.linhas(M.OBJ_META, [col, CM.VOL_MES], filtro)
    return sorted({limpar(l.get(col)) for l in linhas if limpar(l.get(col)) not in ("", SEM)})


def _medidas_cliente(cons: Consulta, ref: date, hoje: date | None, ags: list[str]) -> dict[str, dict[tuple, list[float]]]:
    """{rota: {(agrupador, pv): [realizado, realizado_hoje, meta_dia, meta_neg]}}, consultas por gerência (o mês
    inteiro por cliente passa do limite de registros do Datasphere). Realizado pela rota do cliente; Meta Dia e
    META_NEG pela rota da Meta SAP."""
    def chave(col_rota, col_ag):
        def f(l):
            pv = inteiro(l.get(CM.CLIENTE))
            return None if pv is None else (_rota(l.get(col_rota)), limpar(l.get(col_ag)), pv)
        return f

    anomes = ref.strftime("%Y%m")
    gcs_cli = _distintos(cons, CM.GC, e(eq(CM.ANOMES, anomes), COM_GERENCIA))
    gcs_meta = _distintos(cons, META_GC, eq(CM.META_ANOMES, anomes))
    real = _flash(cons, ref, hoje, ags, [CM.AGRUPADOR, CM.ROTA, CM.CLIENTE], {g: eq(CM.GC, g) for g in gcs_cli},
                  chave(CM.ROTA, CM.AGRUPADOR))
    metas = _metas_meta_sap(cons, ref, hoje, [AGRUPADOR, CM.META_ROTA, CM.CLIENTE], [CM.META_RECUPERAVEL, CM.META_NEG],
                            {g: eq(META_GC, g) for g in gcs_meta}, chave(CM.META_ROTA, AGRUPADOR))
    por_rota: dict[str, dict[tuple, list[float]]] = defaultdict(dict)
    for k in set(real) | set(metas):
        rota, ag, pv = k
        por_rota[rota][(ag, pv)] = [*real.get(k, [0.0, 0.0]), *metas.get(k, [0.0, 0.0])]
    return por_rota


def _arredondar(valores) -> list[float]:
    return [round(v, 4) for v in valores]   # 4 casas: a soma no front fecha com o SAC


def montar_mes(cons: Consulta, ref: date, nomes: dict, hoje: date | None = None) -> dict[str, dict]:
    """Arquivo do mês, os de clientes por rota e o índice de busca, com caminhos relativos a v1/especies/."""
    anomes = ref.strftime("%Y%m")
    meta = _meta(cons, anomes)
    meta_rotas = {rota: (gc, sv) for _, gc, sv, rota in meta}
    ags = sorted({ag for ag, *_ in meta if ag})
    medidas = _medidas(cons, ref, hoje, ags, meta_rotas)
    vazio = [0.0] * len(NOMES_MEDIDAS)
    linhas = []
    for chave in sorted(set(meta) | set(medidas)):
        valores = _arredondar([meta.get(chave, 0.0), *medidas.get(chave, vazio)])
        if chave[0] and any(valores):
            linhas.append([*chave, *valores])

    rotas = {l[3]: (l[1], l[2]) for l in linhas}
    svs = {l[2]: l[1] for l in linhas}
    arquivos = {f"{anomes}.json": {
        "versao": VERSAO, "anomes": anomes, "rotulo": calmod.rotulo_mes(ref),
        "meta_dia_em": hoje.isoformat() if _hoje_no_mes(ref, hoje) else None,
        "gerencias": [{"id": g, "nome": _nome_gc(g)} for g in sorted({l[1] for l in linhas})],
        "supervisoes": [{"id": sv, "gerencia": gc, "nome": nomes["sv"].get(sv, "")} for sv, gc in sorted(svs.items())],
        "rotas": [{"id": r, "gerencia": gc, "supervisao": sv, "vendedor": nomes["vendedor"].get(r, ""),
                   "arquivo": f"especies/{anomes}/{arquivo_rota(r)}.json"} for r, (gc, sv) in sorted(rotas.items())],
        "busca": f"especies/{anomes}/_busca.json",
        "campos": CAMPOS, "linhas": linhas,
    }}

    clientes = _medidas_cliente(cons, ref, hoje, ags)
    busca, n_cli = [], 0
    for rota in rotas:
        lin = [[ag, pv, *_arredondar(v)] for (ag, pv), v in sorted(clientes.get(rota, {}).items())
               if ag and any(abs(x) > 1e-9 for x in v)]
        pvs = sorted({l[1] for l in lin})
        busca += [[pv, nomes["cliente"].get(pv, ""), rota] for pv in pvs]
        n_cli += len(lin)
        arquivos[f"{anomes}/{arquivo_rota(rota)}.json"] = {
            "anomes": anomes, "rota": rota,
            "clientes": [{"pv": pv, "nome": nomes["cliente"].get(pv, "")} for pv in pvs],
            "campos": CAMPOS_CLIENTE, "linhas": lin,
        }
    arquivos[f"{anomes}/_busca.json"] = {"campos": ["pv", "nome", "rota"], "clientes": sorted(busca)}
    log.info("Espécies %s: %d linhas, %d rotas, %d linhas de cliente; meta %.1f, realizado %.1f", anomes,
             len(linhas), len(rotas), n_cli, sum(l[4] for l in linhas), sum(l[5] for l in linhas))
    return arquivos


def _nomes(clientes) -> dict:
    """Nomes de supervisores, vendedores e clientes da base (Dados.clientes)."""
    nomes: dict = {"sv": {}, "vendedor": {}, "cliente": {}}
    for c in clientes or []:
        nomes["sv"].setdefault(c.sv, c.nome_sv)
        nomes["vendedor"].setdefault(c.rota, c.vendedor)
        nomes["cliente"][c.pv] = titulo(c.nome) if c.nome.isupper() else c.nome
    return nomes


def _existentes(destino: Path, anomes: str) -> dict[str, dict] | None:
    """Arquivos de um mês já gravados (mês fechado não muda); None se faltar algum ou se o formato for antigo."""
    base = destino / "v1" / "especies"
    mes = saida.ler(base / f"{anomes}.json")
    if not mes or mes.get("versao") != VERSAO:
        return None
    arquivos = {f"{anomes}.json": mes}
    for rel in [r["arquivo"] for r in mes["rotas"]] + [mes["busca"]]:
        rel = rel.removeprefix("especies/")
        obj = saida.ler(base / rel)
        if obj is None:
            return None
        arquivos[rel] = obj
    return arquivos


def montar(cons: Consulta, ref: date, destino: Path, clientes=None, hoje: date | None = None) -> dict[str, dict]:
    """Arquivos v1/especies/* do mês de referência `ref` e dos MESES_HISTORICO anteriores."""
    meses = [ref]
    for _ in range(MESES_HISTORICO):
        meses.append(calmod.mes_anterior(meses[-1]))
    nomes = _nomes(clientes)
    arquivos: dict[str, dict] = {}
    for i, mes in enumerate(meses):
        do_mes = (_existentes(destino, f"{mes:%Y%m}") if i else None) or montar_mes(cons, mes, nomes, hoje)
        arquivos.update({f"v1/especies/{rel}": obj for rel, obj in do_mes.items()})
    arquivos["v1/especies/index.json"] = {
        "meses": [{"anomes": f"{m:%Y%m}", "rotulo": calmod.rotulo_mes(m), "arquivo": f"especies/{m:%Y%m}.json"}
                  for m in meses],
    }
    return arquivos
