"""
validacao.py — Confere a API montada antes de gravar (mesma ideia do projeto da TI).

Erros (nada é gravado; o site continua com a última versão boa):
  - nenhuma rota ou nenhum cliente;
  - nenhum produto com meta no total da empresa;
  - mesmo mês do publicado e o realizado da empresa de algum produto caiu mais de QUEDA_MAX (consulta incompleta);
  - gerência que existia no publicado sumiu (no mesmo mês).
Avisos (grava, mas registra no log):
  - produto sem meta no total da empresa (agrupador com grafia errada em mapeamento.PRODUTOS?);
  - produto com meta e realizado zero depois do 3º dia útil.
"""
from __future__ import annotations

from . import mapeamento as M

QUEDA_MAX = 0.30


def validar(arquivos: dict[str, dict], anterior_resumo: dict | None = None,
            anterior_index: dict | None = None) -> tuple[list[str], list[str]]:
    erros: list[str] = []
    avisos: list[str] = []
    index, resumo = arquivos.get("v1/index.json"), arquivos.get("v1/resumo.json")
    if not index or not resumo:
        return ["index.json ou resumo.json não foi montado"], avisos
    rotas = [k for k in arquivos if k.startswith("v1/rotas/")]
    if not rotas:
        erros.append("nenhuma rota na API")
    if not arquivos.get("v1/busca.json", {}).get("clientes"):
        erros.append("nenhum cliente na API")

    empresa = resumo["empresa"]["produtos"]
    com_meta = [k for k, b in empresa.items() if b.get("meta")]
    if not com_meta:
        erros.append("nenhum produto com meta no total da empresa (confira os agrupadores em mapeamento.PRODUTOS)")
    for k, b in empresa.items():
        nome = M.NOME_PRODUTO.get(k, k)
        if not b.get("meta"):
            avisos.append(f"{nome}: sem meta no total da empresa (agrupador {M.PRODUTOS[M.IDS_PRODUTOS.index(k)]['agrupadores']} "
                          f"existe no Datasphere? rode scripts/descobrir_produtos.py)")
        elif not b.get("realizado") and index["calendario"]["dias_uteis_fechados"] >= 3:
            avisos.append(f"{nome}: com meta, mas realizado zero no mês")

    mesmo_mes = (anterior_index and anterior_resumo and not anterior_index.get("simulado") and not index.get("simulado")
                 and anterior_index.get("mes_referencia", {}).get("anomes") == index["mes_referencia"]["anomes"])
    if mesmo_mes:
        antes = anterior_resumo.get("empresa", {}).get("produtos", {})
        for k, b in empresa.items():
            r_antes, r_agora = (antes.get(k) or {}).get("realizado") or 0, b.get("realizado") or 0
            if r_antes > 0 and r_agora < r_antes * (1 - QUEDA_MAX):
                erros.append(f"{M.NOME_PRODUTO.get(k, k)}: realizado da empresa caiu de {r_antes} para {r_agora} "
                             f"(mais de {QUEDA_MAX:.0%}); consulta provavelmente incompleta")
        gcs_antes = {g["id"] for g in anterior_index.get("gerencias", [])}
        gcs_agora = {g["id"] for g in index.get("gerencias", [])}
        if gcs_antes - gcs_agora:
            erros.append(f"gerências sumiram em relação ao publicado: {', '.join(sorted(gcs_antes - gcs_agora))}")
    return erros, avisos
