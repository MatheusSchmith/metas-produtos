"""
modelo.py — Contas de meta x realizado de volume (funções puras, sem rede).

Critério do SAC (o mesmo do projeto "Desempenho de Rotas" da TI), por rota x produto:
  Meta          = META_VOLUME da rota
  Realizado     = Vol Real: FX_VOL_PADRAO_FAT do mês com NF_STATUS em M.STATUS_NF_REAL
  Neg Restante  = META_NEG de hoje ao fim do mês (pela rota da META), direto quando a META_NEG do mês bate
                  com a META_VOLUME (1%); senão Meta x (restante / mês) (escalonado)
  Tendência     = Realizado + Neg Restante; % tendência = Tendência / Meta
  Meta do dia   = META_RECUPERAVEL_ROTA de hoje
Supervisão, gerência e empresa SOMAM as rotas e recalculam os percentuais.
Cliente: meta = soma da META_NEG do cliente no mês; status pelo ritmo esperado (dias úteis fechados).
Fechamento do mês: sem tendência, sem meta do dia e sem online; status pelo % realizado.
"""
from __future__ import annotations

from dataclasses import dataclass

from .tipos import Calendario, VolumeRota

DIRETO, CURVA, SEM_CURVA, SEM_META_ROTA = "direto", "curva", "sem_curva", "sem_meta_rota"
TOLERANCIA_DIRETO = 0.01

META_BATIDA, NO_RITMO, ABAIXO, SEM_META = "meta_batida", "no_ritmo", "abaixo_do_ritmo", "sem_meta"


def meta_e_restante(meta_rota: float | None, neg_mes: float | None, neg_restante: float | None,
                    dias_restantes: int, dias_mes: int,
                    direto: bool = False) -> tuple[float | None, float | None, str | None]:
    """(meta, Neg Restante, caso) de uma rota x produto (cópia da regra da TI).

    direto        META_NEG do mês (pela rota da meta) a até 1% da META_VOLUME: o próprio restante
    curva         META_VOLUME > 0 e META_NEG do mês > 0: Meta x restante / mês (escalonado)
    sem_curva     META_VOLUME > 0 e META_NEG do mês = 0: Meta x dias úteis restantes / dias úteis
    sem_meta_rota META_VOLUME ausente ou 0 e META_NEG > 0: meta e restante = somas de META_NEG
    None          as duas zeradas: sem meta
    """
    if meta_rota and meta_rota > 0:
        if neg_mes and neg_mes > 0:
            if direto and abs(neg_mes - meta_rota) <= TOLERANCIA_DIRETO * meta_rota:
                return meta_rota, neg_restante or 0.0, DIRETO
            return meta_rota, meta_rota * (neg_restante or 0.0) / neg_mes, CURVA
        return meta_rota, (meta_rota * dias_restantes / dias_mes if dias_mes else 0.0), SEM_CURVA
    if neg_mes and neg_mes > 0:
        return neg_mes, neg_restante or 0.0, SEM_META_ROTA
    return None, None, None


def r1(v: float | None) -> float | None:
    """1 casa decimal, sem '-0.0'."""
    if v is None:
        return None
    r = round(v, 1)
    return 0.0 if r == 0 else r


def pct(valor: float | None, meta: float | None) -> int | None:
    return round(valor / meta * 100) if meta and valor is not None else None


@dataclass
class Acumulado:
    """Soma de rotas (ou uma rota só). Campos None = ainda sem nenhuma parcela com valor."""
    meta: float = 0.0
    realizado: float = 0.0
    neg_restante: float | None = None
    meta_dia: float | None = None
    online: float | None = None
    rotas_com_meta: int = 0

    def somar(self, outro: "Acumulado") -> None:
        self.meta += outro.meta
        self.realizado += outro.realizado
        self.rotas_com_meta += outro.rotas_com_meta
        for campo in ("neg_restante", "meta_dia", "online"):
            v = getattr(outro, campo)
            if v is not None:
                setattr(self, campo, (getattr(self, campo) or 0.0) + v)


def acumulado_rota(v: VolumeRota | None, online: float | None) -> Acumulado | None:
    """Rota sem meta (META_VOLUME e META_NEG zeradas) não entra nas somas, como no SAC."""
    if v is None or v.meta is None:
        return None
    return Acumulado(meta=v.meta, realizado=v.real, neg_restante=v.neg_restante, meta_dia=v.meta_dia,
                     online=online, rotas_com_meta=1)


def sem_meta(realizado: float | None = None, online: float | None = None) -> dict:
    return {"meta": None, "realizado": r1(realizado), "atingimento_pct": None, "diferenca": None,
            "tendencia": None, "tendencia_pct": None, "meta_dia": None, "online_hoje": r1(online),
            "status": SEM_META}


def bloco(a: Acumulado | None, cal: Calendario) -> dict:
    """Indicador de rota, supervisão, gerência ou empresa (mesmo formato em todos os níveis)."""
    if a is None or a.rotas_com_meta == 0:
        return sem_meta()
    ating = pct(a.realizado, a.meta)
    if cal.fechamento:
        tend = tend_pct = None
    else:
        tend = a.realizado + (a.neg_restante or 0.0)
        tend_pct = pct(tend, a.meta)
    if not a.meta:
        status = SEM_META
    elif ating is not None and ating >= 100:
        status = META_BATIDA
    elif tend_pct is not None and tend_pct >= 100:
        status = NO_RITMO
    else:
        status = ABAIXO
    return {
        "meta": r1(a.meta), "realizado": r1(a.realizado), "atingimento_pct": ating,
        "diferenca": r1(a.realizado - a.meta), "tendencia": r1(tend), "tendencia_pct": tend_pct,
        "meta_dia": None if cal.fechamento else r1(a.meta_dia),
        "online_hoje": None if cal.fechamento else r1(a.online), "status": status,
    }


def bloco_cliente(meta: float | None, realizado: float, online: float | None, cal: Calendario) -> dict:
    """Cliente: meta = META_NEG do mês; no ritmo quando o % realizado alcança o ritmo esperado."""
    on = None if cal.fechamento else r1(online or 0.0)
    if not meta:   # sem META_NEG (ou zerada) no mês
        return {"meta": r1(meta), "realizado": r1(realizado), "atingimento_pct": None, "diferenca": None,
                "online_hoje": on, "status": SEM_META}
    ating = pct(realizado, meta)
    if ating >= 100:
        status = META_BATIDA
    elif ating >= (100 if cal.fechamento else cal.pace_ontem_pct):
        status = NO_RITMO
    else:
        status = ABAIXO
    return {"meta": r1(meta), "realizado": r1(realizado), "atingimento_pct": ating,
            "diferenca": r1(realizado - meta), "online_hoje": on, "status": status}
