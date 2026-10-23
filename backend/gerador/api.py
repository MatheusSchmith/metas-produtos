"""
api.py — Monta os arquivos da API a partir de tipos.Dados (sem rede).

    v1/index.json              data/hora da atualização, mês, calendário, produtos, gerências, endereços
    v1/resumo.json             empresa e cada gerência, por produto
    v1/gerencias/<GC>.json     a gerência, suas supervisões e suas rotas, por produto
    v1/rotas/<ROTA>.json       a rota e seus clientes, por produto
    v1/busca.json              lista compacta de clientes (pv, nome, rota, gerência) para busca

Só o index.json traz a data/hora: os demais arquivos só mudam quando o dado muda (commit pequeno).
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict

from . import mapeamento as M
from . import modelo
from .tipos import Cliente, Dados

VERSAO = "1"
UNIDADE = "volume padrão (FX_VOL_PADRAO_FAT)"


def _chave_natural(texto: str):
    return [int(p) if p.isdigit() else p for p in re.split(r"(\d+)", texto)]


def _mais_comum(valores: list[str]) -> str:
    valores = [v for v in valores if v]
    return Counter(valores).most_common(1)[0][0] if valores else ""


def _produtos(acumulados: dict[str, modelo.Acumulado | None], cal) -> dict:
    return {k: modelo.bloco(acumulados.get(k), cal) for k in M.IDS_PRODUTOS}


def montar(d: Dados) -> dict[str, dict]:
    cal = d.cal
    online = d.online or {}

    # ---------------------------------------------------------------- rotas
    por_rota: dict[str, list[Cliente]] = defaultdict(list)
    for c in d.clientes:
        por_rota[c.rota].append(c)
    rotas: dict[str, dict] = {}
    for r, cs in por_rota.items():
        rotas[r] = {"id": r, "tipo": M.tipo_rota(r), "gerencia": _mais_comum([c.gc for c in cs]),
                    "supervisao": _mais_comum([c.sv for c in cs]), "vendedor": _mais_comum([c.vendedor for c in cs])}
    for r, gc in d.eventuais.items():
        rotas[r] = {"id": r, "tipo": M.TIPO_EVENTUAL, "gerencia": gc, "supervisao": M.sv_eventuais(gc), "vendedor": ""}

    nome_sv: dict[str, str] = {}
    for c in d.clientes:
        nome_sv.setdefault(c.sv, c.nome_sv)

    def acum_rota(r: str) -> dict[str, modelo.Acumulado | None]:
        vols, on = d.volume.get(r, {}), online.get(r, {})
        return {k: modelo.acumulado_rota(vols.get(k), None if d.online is None else on.get(k, 0.0))
                for k in M.IDS_PRODUTOS}

    acum = {r: acum_rota(r) for r in rotas}

    def somar(lista_rotas: list[str]) -> dict[str, modelo.Acumulado | None]:
        out: dict[str, modelo.Acumulado | None] = {}
        for k in M.IDS_PRODUTOS:
            total = modelo.Acumulado()
            for r in lista_rotas:
                a = acum[r].get(k)
                if a is not None:
                    total.somar(a)
            out[k] = total if total.rotas_com_meta else None
        return out

    arquivos: dict[str, dict] = {}

    # ---------------------------------------------------------------- arquivos de rota (com clientes)
    for r, info in rotas.items():
        roster = {c.pv: c for c in por_rota.get(r, [])}
        vol_cli = d.volume_cliente.get(r, {})
        on_cli = d.online_cliente.get(r, {})
        clientes = []
        for pv in sorted(set(roster) | set(vol_cli), key=lambda p: (roster[p].nome if p in roster else "~", p)):
            c = roster.get(pv)
            vc, oc = vol_cli.get(pv, {}), on_cli.get(pv, {})
            clientes.append({
                "pv": pv, "nome": c.nome if c else "", "segmento": c.segmento if c else "", "na_base": c is not None,
                "produtos": {k: modelo.bloco_cliente(vc.get(k, (None, 0.0))[0], vc.get(k, (None, 0.0))[1],
                                                     oc.get(k, 0.0), cal) for k in M.IDS_PRODUTOS},
            })
        arquivos[f"v1/rotas/{r}.json"] = {
            "rota": {**info, "nome_supervisor": nome_sv.get(info["supervisao"], "")},
            "produtos": _produtos(acum[r], cal),
            "clientes": clientes,
        }

    # ---------------------------------------------------------------- gerências (com supervisões e rotas)
    rotas_da_gc: dict[str, list[str]] = defaultdict(list)
    for r, info in rotas.items():
        rotas_da_gc[info["gerencia"]].append(r)
    gcs = [g for g in M.GC_NOMES if g in rotas_da_gc] + sorted(g for g in rotas_da_gc if g not in M.GC_NOMES)

    resumo_gcs = []
    for gc in gcs:
        rs = sorted(rotas_da_gc[gc], key=_chave_natural)
        por_sv: dict[str, list[str]] = defaultdict(list)
        for r in rs:
            por_sv[rotas[r]["supervisao"]].append(r)
        produtos_gc = _produtos(somar(rs), cal)
        gerencia = {"id": gc, "nome": M.GC_NOMES.get(gc, gc)}
        arquivos[f"v1/gerencias/{gc}.json"] = {
            "gerencia": gerencia,
            "produtos": produtos_gc,
            "supervisoes": [{"id": sv, "nome": nome_sv.get(sv, ""), "rotas": por_sv[sv],
                             "produtos": _produtos(somar(por_sv[sv]), cal)}
                            for sv in sorted(por_sv, key=_chave_natural)],
            "rotas": [{**rotas[r], "produtos": _produtos(acum[r], cal)} for r in rs],
        }
        resumo_gcs.append({**gerencia, "produtos": produtos_gc})

    arquivos["v1/resumo.json"] = {
        "empresa": {"produtos": _produtos(somar(list(rotas)), cal)},
        "gerencias": resumo_gcs,
    }
    arquivos["v1/busca.json"] = {
        "campos": ["pv", "nome", "rota", "gerencia"],
        "clientes": [[c.pv, c.nome, c.rota, c.gc] for c in sorted(d.clientes, key=lambda c: (c.nome, c.pv))],
    }
    arquivos["v1/index.json"] = {
        "versao_api": VERSAO,
        "atualizado_em": d.agora.isoformat(timespec="seconds"),
        "fuso": "America/Sao_Paulo",
        "simulado": d.simulado,
        "mes_referencia": {"anomes": cal.anomes, "rotulo": cal.mes_label, "fechamento": cal.fechamento},
        "calendario": {
            "hoje": cal.hoje.isoformat(), "dias_uteis_mes": cal.total_dias_uteis, "dia_util_hoje": cal.dia_hoje,
            "dias_uteis_fechados": cal.dia_ontem, "dias_uteis_restantes": cal.total_dias_uteis - cal.dia_ontem,
            "ritmo_esperado_pct": cal.pace_ontem_pct,
        },
        "unidade": UNIDADE,
        "produtos": [{"id": p["id"], "nome": p["nome"]} for p in M.PRODUTOS],
        "status": {modelo.META_BATIDA: "Meta batida", modelo.NO_RITMO: "No ritmo",
                   modelo.ABAIXO: "Abaixo do ritmo", modelo.SEM_META: "Sem meta"},
        "gerencias": [{"id": g, "nome": M.GC_NOMES.get(g, g), "arquivo": f"gerencias/{g}.json"} for g in gcs],
        "arquivos": {"resumo": "resumo.json", "gerencia": "gerencias/{gerencia}.json", "rota": "rotas/{rota}.json",
                     "busca": "busca.json"},
        "avisos": d.avisos,
    }
    return arquivos
