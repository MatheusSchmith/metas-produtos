"""
consulta.py — Acesso aos modelos ANALÍTICOS do space via OData.

    url: {tenant}/api/v1/datasphere/consumption/analytical/<SPACE>/<OBJETO>/<EntitySet>
    $select = dimensões + medidas (o servidor agrega pelas dimensões escolhidas)
    $filter = ex.: ANOMES_REF eq '202610'

O EntitySet é lido do $metadata (odata.metadados), como no kit Teste_ODATA.
A paginação (@odata.nextLink), o token e as novas tentativas ficam em odata.cliente.

Cache em disco (opcional):
    gravar=True  -> salva cada resposta em <pasta>/<hash>.json
    replay=True  -> lê do cache e NUNCA chama a rede (testes / reprocessar um dia)
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote

from odata.cliente import iterar_paginas
from odata.config import Config
from odata.metadados import ler_metadados
from odata.objetos import ANALITICO, buscar_objeto

log = logging.getLogger(__name__)


class Consulta:
    def __init__(self, cfg: Config, pasta_cache: Path | None = None, gravar: bool = False, replay: bool = False):
        self.cfg = cfg
        self.pasta_cache = pasta_cache
        self.gravar = gravar and pasta_cache is not None
        self.replay = replay and pasta_cache is not None
        self._urls: dict[str, str] = {}
        self._colunas: dict[str, list[str]] = {}
        self._tipos: dict[str, dict[str, str]] = {}

    # ------------------------------------------------------------ metadados
    def _resolver(self, objeto: str) -> None:
        if objeto in self._urls:
            return
        chave = self._arquivo_cache("__url__" + objeto)
        if self.replay and chave and chave.exists():
            salvo = json.loads(chave.read_text(encoding="utf-8"))
            self._urls[objeto], self._colunas[objeto] = salvo["url"], salvo["colunas"]
            self._tipos[objeto] = salvo.get("tipos", {})
            return
        obj = buscar_objeto(self.cfg.space, objeto)
        meta = ler_metadados(obj, ANALITICO)
        base = obj.url_dados(ANALITICO).rstrip("/")
        self._urls[objeto] = f"{base}/{quote(meta.entity_set, safe='')}"
        self._colunas[objeto] = meta.nomes_colunas
        self._tipos[objeto] = meta.tipos_colunas
        if self.gravar and chave:
            chave.parent.mkdir(parents=True, exist_ok=True)
            chave.write_text(json.dumps({"url": self._urls[objeto], "colunas": self._colunas[objeto],
                                         "tipos": self._tipos[objeto]}), encoding="utf-8")

    def colunas(self, objeto: str) -> list[str]:
        self._resolver(objeto)
        return self._colunas[objeto]

    def tipo(self, objeto: str, coluna: str) -> str | None:
        """Tipo OData da coluna (ex.: 'Edm.Date', 'Edm.String'); None se desconhecido."""
        self._resolver(objeto)
        return self._tipos.get(objeto, {}).get(coluna)

    def url(self, objeto: str) -> str:
        self._resolver(objeto)
        return self._urls[objeto]

    # ------------------------------------------------------------ dados
    def _arquivo_cache(self, chave: str) -> Path | None:
        if not self.pasta_cache:
            return None
        h = hashlib.sha1(chave.encode("utf-8")).hexdigest()[:16]
        return self.pasta_cache / f"{h}.json"

    def linhas(self, objeto: str, select: list[str], filtro: str | None = None,
               top: int | None = None, orderby: str | None = None) -> list[dict]:
        """Todas as linhas (todas as páginas) da consulta, sem as chaves '@odata...'."""
        consulta = {"$select": ",".join(dict.fromkeys(select)), "$filter": filtro, "$top": top, "$orderby": orderby}
        chave_txt = json.dumps([objeto, consulta], sort_keys=True)
        arquivo = self._arquivo_cache(chave_txt)
        if self.replay:
            if not arquivo or not arquivo.exists():
                raise FileNotFoundError(f"Sem cache para {objeto} {consulta} em {self.pasta_cache}")
            return json.loads(arquivo.read_text(encoding="utf-8"))

        inicio = time.monotonic()
        linhas: list[dict] = []
        for pagina in iterar_paginas(self.url(objeto), consulta):
            linhas.extend({k: v for k, v in item.items() if not k.startswith("@")} for item in pagina)
            if top and len(linhas) >= top:
                linhas = linhas[:top]
                break
        log.info("%s: %d linhas em %.1fs (%s)", objeto, len(linhas), time.monotonic() - inicio,
                 ", ".join(select[:4]) + ("…" if len(select) > 4 else ""))
        if self.gravar and arquivo:
            arquivo.parent.mkdir(parents=True, exist_ok=True)
            arquivo.write_text(json.dumps(linhas, ensure_ascii=False), encoding="utf-8")
        return linhas

    def em_paralelo(self, tarefas: dict[str, tuple]) -> dict[str, list[dict]]:
        """Roda várias consultas ao mesmo tempo: {nome: (objeto, select, filtro)} -> {nome: linhas}."""
        with ThreadPoolExecutor(max_workers=min(self.cfg.max_workers, max(1, len(tarefas)))) as ex:
            futuros = {nome: ex.submit(self.linhas, *args) for nome, args in tarefas.items()}
            return {nome: f.result() for nome, f in futuros.items()}


def eq(coluna: str, valor: str) -> str:
    """Filtro OData de igualdade de texto com aspas escapadas."""
    return f"{coluna} eq '{str(valor).replace(chr(39), chr(39) * 2)}'"


def e(*filtros: str | None) -> str | None:
    partes = [f for f in filtros if f]
    return " and ".join(f"({p})" if " or " in p and not p.startswith("(") else p for p in partes) or None


def ou(coluna: str, valores: list[str]) -> str | None:
    """(col eq 'a' or col eq 'b' ...) — vazio vira None (sem filtro)."""
    valores = list(dict.fromkeys(valores))
    if not valores:
        return None
    return "(" + " or ".join(eq(coluna, v) for v in valores) + ")"
