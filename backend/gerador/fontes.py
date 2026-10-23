"""
fontes.py — Consulta o Datasphere e normaliza as linhas em tipos.Dados.

Mesmas consultas e regras de volume do projeto "Desempenho de Rotas" da TI, só com os agrupadores dos
produtos desta API (M.PRODUTOS). Todas analíticas (o $select de dimensões é o groupby), em paralelo:

  calendario  AM_BND_MTR_CALENDARIO_DATA_ATUAL  dias úteis do mês / dia útil de hoje
  base        AM_BND_BASE_CLIENTE               clientes ativos: rota, supervisor, vendedor, gerência
  vol_real    AM_FAT_BND_ANALISE_META           rota x cliente x agrupador x NF_STATUS (uma consulta por
                                                gerência): Vol Real = FX_VOL_PADRAO_FAT com status do SAC;
                                                clientes em rotas EV* também pela gerência comercial
  clientes    AM_FAT_BND_ANALISE_META           rota x cliente x agrupador: META_NEG do cliente no mês e
                                                volume dos pedidos de hoje (só 'Inc. e Exp.')
  metas       AM_FAT_BND_ANALISE_META           rota da meta x agrupador: META_VOLUME (meta da rota)
  meta_neg    AM_FAT_BND_ANALISE_META           rota x agrupador: META_NEG do mês e da parte restante
  meta_dia    AM_FAT_BND_ANALISE_META           rota da meta x agrupador: META_RECUPERAVEL_ROTA de hoje

DATA_MOVIMENTO só aparece no $filter, nunca no groupby (por dia a consulta fica lenta demais).
"""
from __future__ import annotations

import logging
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta

from . import calendario as calmod
from . import mapeamento as M
from . import modelo
from .consulta import Consulta, e, eq, ou
from .mapeamento import ColBase as B, ColCalendario as CC, ColMeta as CM
from .texto import inteiro, limpar, normalizar, numero
from .tipos import Calendario, Cliente, Dados, VolumeRota

log = logging.getLogger(__name__)


class ErroMapeamento(Exception):
    """Coluna esperada não existe no modelo do Datasphere (ajuste gerador/mapeamento.py)."""


def _colunas(cons: Consulta, objeto: str, obrigatorias: list[str], opcionais: list[str] = ()) -> list[str]:
    existentes = set(cons.colunas(objeto))
    faltando = [c for c in obrigatorias if c not in existentes]
    if faltando:
        raise ErroMapeamento(f"{objeto}: colunas não encontradas no $metadata: {', '.join(faltando)}. "
                             f"Ajuste gerador/mapeamento.py.")
    sem = [c for c in opcionais if c not in existentes]
    if sem:
        log.warning("%s: colunas opcionais ausentes (ignoradas): %s", objeto, ", ".join(sem))
    return list(dict.fromkeys(list(obrigatorias) + [c for c in opcionais if c in existentes]))


def _vazio(valor: object) -> bool:
    return normalizar(valor) in ("", "--", "#", "0", "NAO ATRIBUIDO", "NOT ASSIGNED", "INDETERMINADO")


def _rota(valor: object) -> str:
    return limpar(valor).upper()


def _somar(d: dict, chave, valor: float) -> None:
    d[chave] = d.get(chave, 0.0) + valor


def _por_gerencia(obj: str, sel: list[str], filtro: str | None, gcs_originais: list[str], rota: str | None) -> dict:
    """Uma consulta por gerência (rodam em paralelo; cada uma bem menor que a consulta inteira)."""
    if rota or not gcs_originais:
        return {"todas": (obj, sel, filtro)}
    return {g: (obj, sel, e(filtro, eq(CM.GC, g))) for g in gcs_originais}


# ------------------------------------------------------------------ calendário
def carregar_calendario(cons: Consulta, hoje: date) -> tuple[Calendario, list[dict]]:
    linhas: list[dict] = []
    try:
        linhas = cons.linhas(M.OBJ_CALENDARIO, [CC.DATA, CC.DIAS_UTEIS_MES, CC.DIA_UTIL, CC.DIAS_RESTANTES])
        cal = calmod.do_datasphere(linhas, hoje)
        if cal:
            return cal, linhas
        log.warning("Calendário do Datasphere sem linha para %s; usando cálculo local.", hoje)
    except Exception as erro:   # noqa: BLE001 - qualquer falha cai no plano B
        log.warning("Calendário do Datasphere indisponível (%s); usando cálculo local.", erro)
    return calmod.calcular_local(hoje), linhas


# ------------------------------------------------------------------ base de clientes
def carregar_clientes(cons: Consulta, rota: str | None = None) -> tuple[list[Cliente], list[str]]:
    """Clientes ativos + valores originais de GC presentes (dividem as consultas por gerência)."""
    sel = _colunas(cons, M.OBJ_BASE_CLIENTE,
                   [B.ROTA, B.CLIENTE, B.NOME, B.GC, B.SUPERVISOR, B.NOME_SUPERVISOR, B.VENDEDOR, B.QUANTIDADE],
                   [B.SEGMENTO])
    filtro = e(M.FILTRO_BASE_CLIENTE, ou(B.GC, M.GC_ORIGEM), eq(B.ROTA, rota) if rota else None)
    clientes, gcs, ignorados = [], set(), defaultdict(int)
    for l in cons.linhas(M.OBJ_BASE_CLIENTE, sel, filtro):
        pv, r, sv = inteiro(l.get(B.CLIENTE)), _rota(l.get(B.ROTA)), M.codigo_sv(l.get(B.SUPERVISOR))
        motivo = ("sem PV" if pv is None else "rota vazia ou eventual (EV*)" if not M.rota_valida(r)
                  else "supervisor de balcão ou fora do padrão" if not M.sv_valido(sv) else None)
        if motivo:
            ignorados[motivo] += 1
            continue
        gcs.add(str(l.get(B.GC) or ""))
        clientes.append(Cliente(
            pv=pv, nome=limpar(l.get(B.NOME)).upper(), rota=r, gc=M.gc_do_sv(sv), sv=sv,
            nome_sv=limpar(l.get(B.NOME_SUPERVISOR)).upper(), vendedor=limpar(l.get(B.VENDEDOR)).upper(),
            segmento="" if _vazio(l.get(B.SEGMENTO)) else limpar(l.get(B.SEGMENTO))))
    log.info("Base de clientes: %d clientes em %d rotas (ignoradas: %s)",
             len(clientes), len({c.rota for c in clientes}), dict(ignorados) or "nenhuma")
    return clientes, sorted(g for g in gcs if g)


# ------------------------------------------------------------------ Vol Real
def _sigla_gc(valor: object) -> str | None:
    g = M.codigo_gc(valor)
    return g if g in M.GC_NOMES else None


def carregar_volume_real(cons: Consulta, anomes: str, gcs_originais: list[str], rota: str | None):
    """(real {rota: {prod: v}}, real_cliente {rota: {pv: {prod: v}}}, eventuais {gc: {prod: v}})."""
    obj = M.OBJ_META
    sel = _colunas(cons, obj, [CM.ROTA, CM.CLIENTE, CM.AGRUPADOR, CM.NF_STATUS, CM.VOL_MES], [CM.GC_COMERCIAL])
    filtro = e(eq(CM.ANOMES, anomes), ou(CM.AGRUPADOR, M.AGRUPADORES_CONSULTA),
               M.FILTRO_PEDIDOS_ONLINE, eq(CM.ROTA, rota) if rota else None)
    linhas = [l for ls in cons.em_paralelo(_por_gerencia(obj, sel, filtro, gcs_originais, rota)).values() for l in ls]
    real: dict = defaultdict(dict)
    real_cli: dict = defaultdict(lambda: defaultdict(dict))
    eventuais: dict = defaultdict(dict)
    status_fora: dict = defaultdict(float)
    for l in linhas:
        r, pv, k = _rota(l.get(CM.ROTA)), inteiro(l.get(CM.CLIENTE)), M.produto_do_agrupador(l.get(CM.AGRUPADOR))
        vol, status = numero(l.get(CM.VOL_MES)), l.get(CM.NF_STATUS)
        if not r or not k:
            continue
        if not M.status_nf_real(status):
            status_fora[limpar(status)] += vol
            continue
        _somar(real[r], k, vol)
        if pv is not None:
            _somar(real_cli[r][pv], k, vol)
        if M.rota_eventual(r) and CM.GC_COMERCIAL in sel:
            gc = _sigla_gc(l.get(CM.GC_COMERCIAL))
            if gc:
                _somar(eventuais[gc], k, vol)
    log.info("Vol Real: %d linhas, %d rotas; status fora do Vol Real: %s", len(linhas), len(real),
             {s: round(v, 1) for s, v in status_fora.items()} or "nenhum")
    if linhas and not real:
        log.error("Nenhum NF_STATUS bateu com %s. Ajuste M.STATUS_NF_REAL.", M.STATUS_NF_REAL)
    return dict(real), {r: dict(v) for r, v in real_cli.items()}, dict(eventuais)


# ------------------------------------------------------------------ meta por cliente e pedidos de hoje
def carregar_clientes_meta_online(cons: Consulta, anomes: str, gcs_originais: list[str], rota: str | None,
                                  com_online: bool):
    """(meta_cli {rota: {pv: {prod: META_NEG}}}, online {rota: {prod: v}}, online_cli {rota: {pv: {prod: v}}})."""
    obj = M.OBJ_META
    sel = _colunas(cons, obj, [CM.ROTA, CM.CLIENTE, CM.AGRUPADOR, CM.META_NEG], [CM.VOL_ONLINE])
    _colunas(cons, obj, [CM.FONTE, CM.SITUACAO_PEDIDO])   # só confere: entram no $filter
    filtro = e(eq(CM.ANOMES, anomes), ou(CM.AGRUPADOR, M.AGRUPADORES_CONSULTA), M.FILTRO_PEDIDOS_ONLINE,
               eq(CM.ROTA, rota) if rota else None)
    linhas = [l for ls in cons.em_paralelo(_por_gerencia(obj, sel, filtro, gcs_originais, rota)).values() for l in ls]
    meta_cli: dict = defaultdict(lambda: defaultdict(dict))
    online: dict = defaultdict(dict)
    online_cli: dict = defaultdict(lambda: defaultdict(dict))
    for l in linhas:
        r, pv, k = _rota(l.get(CM.ROTA)), inteiro(l.get(CM.CLIENTE)), M.produto_do_agrupador(l.get(CM.AGRUPADOR))
        if not r or pv is None or not k:
            continue
        if l.get(CM.META_NEG) not in (None, ""):
            _somar(meta_cli[r][pv], k, numero(l.get(CM.META_NEG)))
        vol_on = numero(l.get(CM.VOL_ONLINE))
        if com_online and vol_on:
            _somar(online[r], k, vol_on)
            _somar(online_cli[r][pv], k, vol_on)
    log.info("Clientes: %d linhas; pedidos de hoje em %d rotas", len(linhas), len(online))
    return ({r: dict(v) for r, v in meta_cli.items()}, dict(online) if com_online else None,
            {r: dict(v) for r, v in online_cli.items()})


# ------------------------------------------------------------------ metas da rota e curva da META_NEG
def ultimo_dia(d: date) -> date:
    return (date(d.year, d.month, 28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)


def literal_data(cons: Consulta, d: date) -> str:
    """Literal OData de DATA_MOVIMENTO para `d`, pelo tipo do $metadata (mesma regra da TI)."""
    tipo = cons.tipo(M.OBJ_META, CM.DATA) if hasattr(cons, "tipo") else None
    if tipo and "String" not in tipo:
        return f"{d.isoformat()}T00:00:00Z" if "DateTime" in tipo else d.isoformat()
    formato = getattr(cons, "_formato_data", None)
    if formato is None:
        amostra = cons.linhas(M.OBJ_META, [CM.DATA, CM.VOL_MES],
                              e(eq(CM.ANOMES, d.strftime("%Y%m")), ou(CM.AGRUPADOR, M.AGRUPADORES_CONSULTA)), top=1)
        bruto = limpar(amostra[0].get(CM.DATA)) if amostra else ""
        formato = "%Y%m%d" if len(bruto) == 8 and bruto.isdigit() else "%Y-%m-%d"
        cons._formato_data = formato
    return "'" + d.strftime(formato) + "'"


def filtro_restante(cons: Consulta, hoje: date) -> str:
    return f"{CM.DATA} ge {literal_data(cons, hoje)} and {CM.DATA} le {literal_data(cons, ultimo_dia(hoje))}"


def filtro_hoje(cons: Consulta, hoje: date) -> str:
    return f"{CM.DATA} eq {literal_data(cons, hoje)}"


def _por_rota(cons: Consulta, medida: str, anomes: str, gcs_originais: list[str], rota: str | None,
              filtro_extra: str | None = None, col_rota: str = CM.ROTA) -> dict:
    """{rota: {prod: medida}} agregado no servidor por rota x agrupador; se falhar inteira, repete por gerência."""
    obj = M.OBJ_META
    sel = _colunas(cons, obj, [col_rota, CM.AGRUPADOR, medida])
    filtro = e(eq(CM.ANOMES, anomes), ou(CM.AGRUPADOR, M.AGRUPADORES_CONSULTA), filtro_extra,
               eq(col_rota, rota) if rota else None)
    try:
        linhas = cons.linhas(obj, sel, filtro)
    except Exception as erro:   # noqa: BLE001
        if rota or not gcs_originais:
            raise
        log.warning("%s: consulta inteira falhou (%s); repetindo por gerência.", medida, erro)
        linhas = [l for ls in cons.em_paralelo(_por_gerencia(obj, sel, filtro, gcs_originais, rota)).values()
                  for l in ls]
    out: dict = defaultdict(dict)
    for l in linhas:
        r, k = _rota(l.get(col_rota)), M.produto_do_agrupador(l.get(CM.AGRUPADOR))
        if r and k and l.get(medida) not in (None, ""):
            _somar(out[r], k, numero(l.get(medida)))
    return dict(out)


ROTA_META, ROTA_CLIENTE = "rota_meta", "rota_cliente"


def carregar_curva_neg(cons: Consulta, anomes: str, gcs_originais: list[str], rota: str | None, hoje: date,
                       com_restante: bool) -> tuple[dict, dict | None, str]:
    """META_NEG do mês e restante por rota, preferindo a rota da META (como o SAC)."""
    def pela(col: str):
        if not com_restante:
            return _por_rota(cons, CM.META_NEG, anomes, gcs_originais, rota, col_rota=col), None
        return (_por_rota(cons, CM.META_NEG, anomes, gcs_originais, rota, col_rota=col),
                _por_rota(cons, CM.META_NEG, anomes, gcs_originais, rota, filtro_restante(cons, hoje), col))

    try:
        mes, rest = pela(CM.META_ROTA)
        if any(v for ks in mes.values() for v in ks.values()):
            return mes, rest, ROTA_META
        log.warning("META_NEG por %s veio vazia: usando a rota do cliente.", CM.META_ROTA)
    except Exception as erro:   # noqa: BLE001
        log.warning("META_NEG por %s falhou (%s): usando a rota do cliente.", CM.META_ROTA, erro)
    mes, rest = pela(CM.ROTA)
    return mes, rest, ROTA_CLIENTE


def carregar_meta_dia(cons: Consulta, anomes: str, gcs_originais: list[str], rota: str | None, hoje: date) -> dict | None:
    """META_RECUPERAVEL_ROTA de hoje por rota da meta; None se a medida não existir ou falhar."""
    if CM.META_RECUPERAVEL not in set(cons.colunas(M.OBJ_META)):
        log.error("%s não existe no $metadata: meta do dia fica null.", CM.META_RECUPERAVEL)
        return None
    filtro = filtro_hoje(cons, hoje)
    for col in (CM.META_ROTA, CM.ROTA):
        try:
            dia = _por_rota(cons, CM.META_RECUPERAVEL, anomes, gcs_originais, rota, filtro, col_rota=col)
            if dia or col == CM.ROTA:
                return dia
        except Exception as erro:   # noqa: BLE001
            log.warning("%s por %s falhou (%s).", CM.META_RECUPERAVEL, col, erro)
    return None


def carregar_metas_volume(cons: Consulta, anomes: str, rota: str | None) -> dict:
    """META_VOLUME {rota: {prod: meta}}: o maior valor por rota x agrupador (linhas repetem), somado no produto."""
    obj = M.OBJ_META
    sel = _colunas(cons, obj, [CM.META_ROTA, CM.META_AGRUPADOR, CM.META_VOLUME])
    linhas = cons.linhas(obj, sel, e(eq(CM.META_ANOMES, anomes), ou(CM.META_AGRUPADOR, M.AGRUPADORES_CONSULTA),
                                     eq(CM.META_ROTA, rota) if rota else None))
    por_ag: dict = defaultdict(dict)
    for l in linhas:
        r, ag = _rota(l.get(CM.META_ROTA)), normalizar(l.get(CM.META_AGRUPADOR))
        if r and M.produto_do_agrupador(ag) and l.get(CM.META_VOLUME) not in (None, ""):
            por_ag[r][ag] = max(por_ag[r].get(ag, 0.0), numero(l.get(CM.META_VOLUME)))
    metas: dict = defaultdict(dict)
    for r, ags in por_ag.items():
        for ag, v in ags.items():
            _somar(metas[r], M.produto_do_agrupador(ag), v)
    log.info("META_VOLUME em %d rotas", len(metas))
    return dict(metas)


# ------------------------------------------------------------------ fechamento do mês
def decidir_fechamento(cons: Consulta, hoje: date, linhas_cal: list[dict], gc_da_rota: dict[str, str]) -> Calendario | None:
    """Mês anterior fechado até o fim do 1º dia útil e enquanto alguma gerência não tiver META_VOLUME do mês."""
    dia_util = calmod.dia_util_hoje(linhas_cal, hoje)
    if dia_util <= 1:
        metas_ok, motivo = False, f"dia útil {dia_util}"
    else:
        metas = carregar_metas_volume(cons, hoje.strftime("%Y%m"), None)
        por_gc: dict = defaultdict(float)
        for r, ks in metas.items():
            if r in gc_da_rota:
                por_gc[M.gc_origem(gc_da_rota[r])] += sum(ks.values())
        exigidas = sorted({M.gc_origem(g) for g in gc_da_rota.values()})
        faltam = [g for g in exigidas if por_gc.get(g, 0.0) <= 0]
        metas_ok, motivo = not faltam, f"gerências sem META_VOLUME de {hoje:%m/%Y}: {', '.join(faltam)}"
    if not calmod.em_fechamento(dia_util, metas_ok):
        return None
    ref = calmod.mes_anterior(hoje)
    cal = calmod.com_data_ontem(calmod.fechado(hoje, ref, calmod.total_dias_uteis(linhas_cal, ref)), linhas_cal)
    log.warning("Fechamento do mês: API em %s (%s).", cal.mes_label, motivo)
    return cal


# ------------------------------------------------------------------ tudo junto
def carregar(cons: Consulta, agora: datetime, rota: str | None = None) -> Dados:
    hoje = agora.date()
    cal, linhas_cal = carregar_calendario(cons, hoje)
    clientes, gcs = carregar_clientes(cons, rota)
    gc_da_rota = {c.rota: c.gc for c in clientes}
    if not rota:
        cal = decidir_fechamento(cons, hoje, linhas_cal, gc_da_rota) or cal
    anomes, fech = cal.anomes, cal.fechamento

    with ThreadPoolExecutor(max_workers=5) as ex:
        f_real = ex.submit(carregar_volume_real, cons, anomes, gcs, rota)
        f_cli = ex.submit(carregar_clientes_meta_online, cons, anomes, gcs, rota, not fech)
        f_metas = ex.submit(carregar_metas_volume, cons, anomes, rota)
        f_neg = ex.submit(carregar_curva_neg, cons, anomes, gcs, rota, hoje, not fech)
        f_dia = None if fech else ex.submit(carregar_meta_dia, cons, anomes, gcs, rota, hoje)
        real, real_cli, ev = f_real.result()
        meta_cli, online, online_cli = f_cli.result()
        metas = f_metas.result()
        neg_mes, neg_rest, fonte_neg = f_neg.result()
        meta_dia = f_dia.result() if f_dia else None

    rotas = sorted(gc_da_rota)
    dias_restantes = cal.total_dias_uteis - cal.dia_ontem
    volume: dict = defaultdict(dict)
    casos: dict = defaultdict(list)
    for r in rotas:
        for k in M.IDS_PRODUTOS:
            nm, rl = neg_mes.get(r, {}).get(k), real.get(r, {}).get(k)
            meta, rest, caso = modelo.meta_e_restante(metas.get(r, {}).get(k), nm, (neg_rest or {}).get(r, {}).get(k),
                                                      dias_restantes, cal.total_dias_uteis,
                                                      direto=fonte_neg == ROTA_META)
            if meta is None and rl is None:
                continue
            if caso in (modelo.SEM_CURVA, modelo.SEM_META_ROTA):
                casos[caso].append(f"{r}/{M.NOME_PRODUTO[k]}")
            volume[r][k] = VolumeRota(meta=meta, real=rl or 0.0, neg_restante=None if fech else rest,
                                      meta_dia=None if meta_dia is None else meta_dia.get(r, {}).get(k, 0.0))
    # clientes em rotas EV*: uma rota oculta por gerência com o Real deles (meta 0: só soma no total)
    eventuais = {}
    gcs_com_rota = set(gc_da_rota.values())
    for gc, ks in sorted(ev.items()):
        if gc not in gcs_com_rota:
            continue
        r = M.rota_eventuais(gc)
        eventuais[r] = gc
        for k, v in ks.items():
            volume[r][k] = VolumeRota(meta=0.0, real=v, neg_restante=None if fech else 0.0,
                                      meta_dia=None if meta_dia is None else 0.0)

    avisos = []
    if fonte_neg == ROTA_CLIENTE:
        avisos.append("META_NEG pela rota da meta indisponível: tendência pela curva da rota do cliente")
    if casos[modelo.SEM_CURVA]:
        avisos.append("Tendência por dias úteis (META_VOLUME sem curva de META_NEG) em: " + ", ".join(casos[modelo.SEM_CURVA]))
    if casos[modelo.SEM_META_ROTA]:
        avisos.append("Meta = soma de META_NEG (sem META_VOLUME) em: " + ", ".join(casos[modelo.SEM_META_ROTA]))

    # clientes: META_NEG do cliente x Vol Real do cliente (só rotas da base)
    vol_cli: dict = {}
    for r in rotas:
        pvs = set(meta_cli.get(r, {})) | set(real_cli.get(r, {}))
        if pvs:
            vol_cli[r] = {pv: {k: (meta_cli.get(r, {}).get(pv, {}).get(k), real_cli.get(r, {}).get(pv, {}).get(k, 0.0))
                               for k in M.IDS_PRODUTOS
                               if k in meta_cli.get(r, {}).get(pv, {}) or k in real_cli.get(r, {}).get(pv, {})}
                          for pv in pvs}
    return Dados(agora=agora, cal=cal, clientes=clientes, volume=dict(volume), volume_cliente=vol_cli,
                 online=None if online is None else {r: v for r, v in online.items() if r in gc_da_rota},
                 online_cliente={r: v for r, v in online_cli.items() if r in gc_da_rota},
                 eventuais=eventuais, avisos=avisos)
