"""
falso.py — Datasphere de mentira para os testes (sem rede).

Guarda linhas "brutas" por objeto e responde como o modo analítico do OData: aplica o $filter
(eq, ne, ge, le, gt, lt, and, or, parênteses) e agrupa pelas dimensões do $select, somando as medidas.
"""
from __future__ import annotations

import re
from collections import defaultdict

MEDIDAS = {"FX_VOL_PADRAO_FAT", "FX_VOL_PADRAO_WF_ONLINE", "META_NEG", "META_RECUPERAVEL_ROTA",
           "META_VOLUME_Chave_Meta_SAP", "QUANTIDADE", "NO_DIAS_UTEIS_MES", "NO_DIA_UTIL", "NO_DIAS_UTEIS_RESTANTES"}
_TOKEN = re.compile(r"\s*(\(|\)|'(?:[^']|'')*'|[A-Za-z_][A-Za-z0-9_]*|[0-9][0-9:\-TZ.]*)")


def _tokens(texto: str) -> list[str]:
    out, pos = [], 0
    while pos < len(texto):
        m = _TOKEN.match(texto, pos)
        if not m:
            if texto[pos:].strip() == "":
                break
            raise ValueError(f"filtro não entendido: {texto[pos:]!r}")
        out.append(m.group(1))
        pos = m.end()
    return out


def _valor(tok: str) -> str:
    return tok[1:-1].replace("''", "'") if tok.startswith("'") else tok


class _Filtro:
    def __init__(self, texto: str | None):
        self.t = _tokens(texto) if texto else []
        self.i = 0

    def avaliar(self, linha: dict) -> bool:
        if not self.t:
            return True
        self.i = 0
        return self._ou(linha)

    def _ou(self, l):
        r = self._e(l)
        while self.i < len(self.t) and self.t[self.i] == "or":
            self.i += 1
            outro = self._e(l)   # sempre avalia (consome os tokens)
            r = r or outro
        return r

    def _e(self, l):
        r = self._atomo(l)
        while self.i < len(self.t) and self.t[self.i] == "and":
            self.i += 1
            outro = self._atomo(l)
            r = r and outro
        return r

    def _atomo(self, l):
        if self.t[self.i] == "(":
            self.i += 1
            r = self._ou(l)
            self.i += 1   # ")"
            return r
        col, op, val = self.t[self.i], self.t[self.i + 1], _valor(self.t[self.i + 2])
        self.i += 3
        v = l.get(col)
        v = "" if v is None else str(v)
        return {"eq": v == val, "ne": v != val, "ge": v >= val, "le": v <= val,
                "gt": v > val, "lt": v < val}[op]


class ConsultaFalsa:
    def __init__(self, dados: dict[str, list[dict]], tipos: dict[str, dict[str, str]] | None = None):
        self.dados = dados
        self.tipos = tipos or {}
        self.chamadas: list[tuple] = []

    def colunas(self, objeto: str) -> list[str]:
        cols: set[str] = set()
        for l in self.dados.get(objeto, []):
            cols |= set(l)
        return sorted(cols)

    def tipo(self, objeto: str, coluna: str) -> str | None:
        return self.tipos.get(objeto, {}).get(coluna)

    def linhas(self, objeto: str, select: list[str], filtro: str | None = None, top: int | None = None,
               orderby: str | None = None) -> list[dict]:
        self.chamadas.append((objeto, tuple(select), filtro))
        f = _Filtro(filtro)
        dims = [c for c in select if c not in MEDIDAS]
        meds = [c for c in select if c in MEDIDAS]
        grupos: dict = defaultdict(lambda: defaultdict(float))
        for l in self.dados.get(objeto, []):
            if not f.avaliar(l):
                continue
            chave = tuple(l.get(c) for c in dims)
            g = grupos[chave]
            for m in meds:
                if l.get(m) is not None:
                    g[m] += float(l[m])
        out = [{**dict(zip(dims, k)), **{m: v.get(m) for m in meds}} for k, v in grupos.items()]
        return out[:top] if top else out

    def em_paralelo(self, tarefas: dict[str, tuple]) -> dict[str, list[dict]]:
        return {nome: self.linhas(*args) for nome, args in tarefas.items()}
