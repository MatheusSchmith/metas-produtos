"""
simulado.py — Dados FICTÍCIOS no mesmo formato dos reais (tipos.Dados), sem Datasphere.

Serve para os testes e para a pessoa do front trabalhar antes de as credenciais estarem configuradas:
    python scripts/gerar.py --simulado --forcar
Sempre gera o mesmo resultado para a mesma data (semente fixa). Nomes de clientes são inventados.
"""
from __future__ import annotations

import random
from datetime import datetime

from . import calendario as calmod
from . import mapeamento as M
from . import modelo
from .tipos import Cliente, Dados, VolumeRota

_NOMES = ["MERCEARIA", "BAR", "PADARIA", "LANCHONETE", "SUPERMERCADO", "CONVENIENCIA", "RESTAURANTE", "ADEGA"]
_SOBRENOMES = ["SAO JORGE", "BOA VISTA", "DO ZE", "CENTRAL", "DA PRACA", "PRIMAVERA", "AURORA", "DOIS IRMAOS",
               "BOM PRECO", "ESTRELA", "DO POVO", "NOVA ERA"]
_SEGMENTOS = ["Mercearia", "Boteco", "Padarias", "Lanchonete", "Super", "Lj. Conveniências", "Restaurante", "Adegas"]
# volume médio por cliente no mês, por produto (fictício)
_BASE = {"sucos": 6.0, "powerade": 3.0, "sabores": 14.0, "retornaveis": 9.0}


def gerar(agora: datetime, gerencias: tuple[str, ...] = ("G1", "G2", "AP")) -> Dados:
    rnd = random.Random(agora.date().toordinal())
    cal = calmod.calcular_local(agora.date())
    frac = cal.dia_ontem / cal.total_dias_uteis if cal.total_dias_uteis else 0.0
    clientes: list[Cliente] = []
    volume: dict = {}
    vol_cli: dict = {}
    online: dict = {}
    online_cli: dict = {}
    pv = 1_000_000
    for gc in gerencias:
        for n_sv in range(1, rnd.randint(2, 3) + 1):
            sv = f"SV.{gc}.{n_sv}"
            nome_sv = f"SUPERVISOR {gc} {n_sv}"
            for n_rota in range(1, rnd.randint(3, 4) + 1):
                rota = f"{gc}{n_sv}{n_rota}"
                vendedor = f"VENDEDOR {rota}"
                desempenho = rnd.uniform(0.85, 1.35)   # rota boa ou fraca
                metas_rota = {k: 0.0 for k in M.IDS_PRODUTOS}
                reais_rota = {k: 0.0 for k in M.IDS_PRODUTOS}
                vol_cli[rota], online_cli[rota], online[rota] = {}, {}, {k: 0.0 for k in M.IDS_PRODUTOS}
                for _ in range(rnd.randint(8, 14)):
                    pv += rnd.randint(1, 40)
                    nome = f"{rnd.choice(_NOMES)} {rnd.choice(_SOBRENOMES)}"
                    clientes.append(Cliente(pv=pv, nome=nome, rota=rota, gc=gc, sv=sv, nome_sv=nome_sv,
                                            vendedor=vendedor, segmento=rnd.choice(_SEGMENTOS)))
                    vol_cli[rota][pv] = {}
                    for k in M.IDS_PRODUTOS:
                        if rnd.random() < 0.2:      # cliente que não tem meta deste produto
                            continue
                        meta = round(_BASE[k] * rnd.uniform(0.5, 2.0), 1)
                        real = round(meta * frac * desempenho * rnd.uniform(0.4, 1.5), 1)
                        vol_cli[rota][pv][k] = (meta, real)
                        metas_rota[k] += meta
                        reais_rota[k] += real
                        if not cal.fechamento and rnd.random() < 0.15:
                            on = round(_BASE[k] * rnd.uniform(0.2, 1.0), 1)
                            online_cli[rota].setdefault(pv, {})[k] = on
                            online[rota][k] += on
                volume[rota] = {}
                for k in M.IDS_PRODUTOS:
                    meta = round(metas_rota[k] * rnd.uniform(0.98, 1.05), 1)   # META_VOLUME perto da soma dos clientes
                    _, rest, _ = modelo.meta_e_restante(meta, metas_rota[k], metas_rota[k] * (1 - frac),
                                                        cal.total_dias_uteis - cal.dia_ontem, cal.total_dias_uteis)
                    volume[rota][k] = VolumeRota(meta=meta, real=reais_rota[k],
                                                 neg_restante=None if cal.fechamento else rest,
                                                 meta_dia=None if cal.fechamento else round(meta / cal.total_dias_uteis, 1))
    return Dados(agora=agora, cal=cal, clientes=clientes, volume=volume, volume_cliente=vol_cli,
                 online=None if cal.fechamento else online, online_cliente=online_cli,
                 avisos=["Dados SIMULADOS (fictícios): não use para decisões."], simulado=True)
