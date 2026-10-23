"""
mapeamento.py — TODAS as tabelas fixas e nomes de colunas usados pelo gerador.

É o único arquivo a ajustar quando o modelo do Datasphere mudar ou quando entrar/sair um produto.
Colunas, filtros e regras especiais de rota foram copiados do projeto "Desempenho de Rotas"
(backend/gerador/mapeamento.py, conferido pela TI em 13/10/2026 e 20/10/2026).
"""
from __future__ import annotations

import re

from .texto import normalizar

# ---------------------------------------------------------------------------
# Objetos (views) do space DW_BND_COM_SAP
# ---------------------------------------------------------------------------
OBJ_META = "AM_FAT_BND_ANALISE_META"          # "Análise Metas v2" (vem de DATASPHERE_ASSET)
OBJ_BASE_CLIENTE = "AM_BND_BASE_CLIENTE"      # "Base Clientes": rota, GC/SV/vendedor
OBJ_CALENDARIO = "AM_BND_MTR_CALENDARIO_DATA_ATUAL"  # dias úteis do mês


# ---------------------------------------------------------------------------
# PRODUTOS DA API
# ---------------------------------------------------------------------------
# id (usado nos JSONs e nos endereços), nome exibido e os agrupadores do Datasphere (coluna
# DS_AGRUPADOR_Agrupador_Prod / AGRUPADOR_PRODU_Chave_Meta_SAP) que somam no produto.
# ATENÇÃO: escreva o agrupador EXATAMENTE como vem do Datasphere (maiúsculas e acentos): ele vai no $filter
# da consulta, que é exato. Depois, na leitura das linhas, a comparação é sem acento/caixa e pelo nome inteiro.
#
# Grafia conferida no Datasphere em 22/10/2026 (scripts/descobrir_produtos.py): são os agrupadores que têm
# META_VOLUME de rota. "Sabores Tt" e "Refrigerantes Retornavel" são os nomes reais de Sabores e Retornáveis.
# Se um produto for a soma de mais de um agrupador, liste todos (ex.: ["Retornavel 1l", "Retornavel 2l"]).
PRODUTOS: list[dict] = [
    {"id": "sucos", "nome": "Vol. Sucos", "agrupadores": ["Sucos"]},
    {"id": "powerade", "nome": "Vol. Powerade", "agrupadores": ["Powerade"]},
    {"id": "sabores", "nome": "Vol. Sabores", "agrupadores": ["Sabores Tt"]},
    {"id": "retornaveis", "nome": "Vol. Retornáveis", "agrupadores": ["Refrigerantes Retornavel"]},
]
IDS_PRODUTOS = [p["id"] for p in PRODUTOS]
NOME_PRODUTO = {p["id"]: p["nome"] for p in PRODUTOS}
AGRUPADORES_CONSULTA = sorted({a for p in PRODUTOS for a in p["agrupadores"]})
_INDICE_PRODUTO = {normalizar(a): p["id"] for p in PRODUTOS for a in p["agrupadores"]}


def produto_do_agrupador(agrupador: object) -> str | None:
    """'SUCOS' / 'Sucos' -> 'sucos'; agrupador fora da API -> None."""
    return _INDICE_PRODUTO.get(normalizar(agrupador))


class ColMeta:
    """Colunas do AM_FAT_BND_ANALISE_META (mesmos nomes do projeto da TI)."""
    ANOMES = "ANOMES_REF"
    ROTA = "CD_ROTA_Clien"                           # rota atual do cliente
    GC = "DS_GC_AGRUPADA_ATUAL_Clien"
    GC_COMERCIAL = "DS_GERENCIA_COMERCIAL_AT_Clien"  # gerência comercial do cliente (Real de rotas EV*)
    CLIENTE = "CD_CLIENTE"
    AGRUPADOR = "DS_AGRUPADOR_Agrupador_Prod"
    DATA = "DATA_MOVIMENTO"
    FONTE = "FONTE"                                  # 'Basis', 'WF Online', 'Meta NEG'
    SITUACAO_PEDIDO = "SITUACAO_Pedido"              # 'Inc. e Exp.', 'Cancelado', 'Reprovado', 'Meta NEG'
    VOL_MES = "FX_VOL_PADRAO_FAT"                    # volume padrão faturado no mês
    VOL_ONLINE = "FX_VOL_PADRAO_WF_ONLINE"           # volume padrão dos pedidos de hoje
    NF_STATUS = "NF_STATUS_Nota_Fiscal"              # Vol Real só com os status de STATUS_NF_REAL
    # lado "Chave_Meta_SAP" do modelo
    META_ANOMES = "ANOMES_REF_Chave_Meta_SAP"
    META_ROTA = "CD_ROTA_Chave_Meta_SAP"
    META_AGRUPADOR = "AGRUPADOR_PRODU_Chave_Meta_SAP"
    META_VOLUME = "META_VOLUME_Chave_Meta_SAP"       # meta de volume da rota no mês (denominador, como o SAC)
    META_NEG = "META_NEG"                            # meta distribuída por cliente e por dia (curva e meta do cliente)
    META_RECUPERAVEL = "META_RECUPERAVEL_ROTA"       # meta do dia (DATA_MOVIMENTO = hoje), pela rota da meta


class ColBase:
    """Colunas do AM_BND_BASE_CLIENTE."""
    ROTA = "CD_ROTA"
    CLIENTE = "CD_CLIENTE"
    NOME = "NM_NOME_FANTASIA"
    SEGMENTO = "DS_SEGMENTO"
    GC = "DS_GC_AGRUPADA_ATUAL"
    SUPERVISOR = "DS_SUPERVISOR_ATUAL"
    NOME_SUPERVISOR = "DS_NOME_SUPERVISOR_ATUAL"
    VENDEDOR = "DS_VENDEDOR_ATUAL"
    QUANTIDADE = "QUANTIDADE"   # medida (o modo analítico exige ao menos uma)


class ColCalendario:
    DATA = "DATA"
    DIAS_UTEIS_MES = "NO_DIAS_UTEIS_MES"
    DIA_UTIL = "NO_DIA_UTIL"
    DIAS_RESTANTES = "NO_DIAS_UTEIS_RESTANTES"


# ---------------------------------------------------------------------------
# Filtros (iguais aos do projeto da TI)
# ---------------------------------------------------------------------------
GC_ORIGEM = ["Gc. G1", "Gc. G2", "Gc. G3", "Gc. Ap", "Gc. It_Mo",
             "Gc. At", "Gc. An", "Gc. Sl", "Gc. Rv", "Gc. Pa_Di", "Gc. Ur_Ri", "Gc. Gu_Po"]
GC_SIGLAS_ORIGEM = {
    "G1": ["G1"], "G2": ["G2"], "G3": ["G3"], "AP": ["AP"], "IT_MO": ["IT", "MO"],
    "AT": ["AT"], "AN": ["AN"], "SL": ["SL"], "RV": ["RV"],
    "PA_DI": ["PA", "DI"], "UR_RI": ["UR", "RI"], "GU_PO": ["GU", "PO"],
}
FILTRO_BASE_CLIENTE = "FL_CORRENTE eq 'S' and STATUS_CLIENTE eq 'Ativo'"
SV_IGNORAR_PREFIXOS = ("SV.BL.",)        # balcão
ROTAS_IGNORAR_PREFIXOS = ("EV",)          # rotas eventuais
# Pedidos de hoje: só 'Inc. e Exp.' (as linhas Basis e Meta NEG passam sem filtro)
FILTRO_PEDIDOS_ONLINE = f"({ColMeta.FONTE} ne 'WF Online' or {ColMeta.SITUACAO_PEDIDO} eq 'Inc. e Exp.')"
# Vol Real (critério do SAC): FX_VOL_PADRAO_FAT só com estes NF_STATUS (comparados por normalizar())
STATUS_NF_REAL = ["Acertado", "Meta Neg", "Em Aberto"]

# As 16 gerências na ordem de exibição, com o nome da praça
GC_NOMES = {
    "AN": "Anápolis", "AP": "Aparecida", "AT": "Atacados", "G1": "Goiânia 01", "G2": "Goiânia 02",
    "G3": "Goiânia 03", "PA": "Palmas", "DI": "Dianópolis", "RV": "Rio Verde", "SL": "São Luís",
    "GU": "Gurupi", "PO": "Porangatu", "IT": "Itumbiara", "MO": "Morrinhos", "UR": "Uruaçu", "RI": "Rialma",
}

# Rotas com tratamento especial (listas do projeto da TI). Entram nos totais de supervisão e gerência,
# como no SAC; o campo "tipo" da rota permite ao front escondê-las ou destacá-las.
NEUTRALIZA_ROTAS = ["A41", "431", "251", "I31", "M31", "C31", "R31", "S31", "U31", "151", "O21", "551"]
VIRTUAIS_ROTAS = ["A42", "A43", "A44", "R32"]
TIPO_NORMAL, TIPO_NEUTRALIZA, TIPO_VIRTUAL, TIPO_EVENTUAL = "normal", "neutraliza", "virtual", "eventual"


def tipo_rota(rota: str) -> str:
    if rota in NEUTRALIZA_ROTAS:
        return TIPO_NEUTRALIZA
    if rota in VIRTUAIS_ROTAS:
        return TIPO_VIRTUAL
    return TIPO_NORMAL


def rota_eventual(rota: str) -> bool:
    """Rota eventual da base/vendas ('EV5', 'EVD')."""
    return bool(rota) and rota.upper().startswith(ROTAS_IGNORAR_PREFIXOS)


def rota_eventuais(gc: str) -> str:
    """Rota oculta com o Real dos clientes em rotas EV* da gerência ('AP' -> 'AP-EV')."""
    return f"{gc}-EV"


def sv_eventuais(gc: str) -> str:
    return f"SV.{gc}.EV"


# ---------------------------------------------------------------------------
# GC e supervisor: códigos curtos ('G1', 'SV.G1.1').
# Fonte: 'Gc. G1', 'Sv. G1.1', 'Sv. G3. 1' (com espaço), 'Sv. It. 1'.
# ---------------------------------------------------------------------------
_SV = re.compile(r"^SV\.([A-Z0-9]+)\.(\d+)$")


def codigo_sv(valor: object) -> str:
    """'Sv. G3. 1' -> 'SV.G3.1'."""
    return normalizar(valor).replace(" ", "")


def sv_valido(sv: str) -> bool:
    return bool(_SV.match(sv)) and not sv.startswith(SV_IGNORAR_PREFIXOS)


def gc_do_sv(sv: str) -> str:
    """'SV.IT.1' -> 'IT' (separa IT e MO, que vêm juntas na gerência de origem)."""
    m = _SV.match(sv)
    return m.group(1) if m else ""


def codigo_gc(valor: object) -> str:
    """'Gc. G1' -> 'G1'; 'Gc. It_Mo' -> 'IT_MO'."""
    chave = normalizar(valor).replace(" ", "")
    return chave[3:] if chave.startswith("GC.") else chave


def rota_valida(rota: str) -> bool:
    return bool(rota) and not rota_eventual(rota)


def status_nf_real(valor: object) -> bool:
    return normalizar(valor) in {normalizar(s) for s in STATUS_NF_REAL}


_ORIGEM_DA_SIGLA = {sigla: origem for origem, siglas in GC_SIGLAS_ORIGEM.items() for sigla in siglas}


def gc_origem(gc: str) -> str:
    """'IT'/'MO' -> 'IT_MO', 'PA' -> 'PA_DI', 'G1' -> 'G1'."""
    return _ORIGEM_DA_SIGLA.get(gc, gc)


def sigla_esperada(gc_original: object, sigla: str) -> bool:
    return sigla in GC_SIGLAS_ORIGEM.get(codigo_gc(gc_original), [codigo_gc(gc_original)])
