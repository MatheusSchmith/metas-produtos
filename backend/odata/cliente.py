"""
cliente.py — Faz as chamadas HTTP (GET) para a API OData.

Cuida de tudo que é repetitivo em qualquer chamada:
  - coloca o token no cabeçalho;
  - respeita o tempo limite (ODATA_TIMEOUT);
  - tenta de novo em falhas temporárias (servidor ocupado, queda de rede);
  - pede um token novo se o atual expirar;
  - segue a paginação do servidor (@odata.nextLink) até o último registro.
"""
from __future__ import annotations

import threading
import time
from typing import Iterator
from urllib.parse import quote, urljoin

import requests

from .autenticacao import obter_token
from .config import carregar_config

TENTATIVAS = 4
STATUS_TEMPORARIOS = {429, 502, 503, 504}
# Um erro 500 que volta rápido costuma ser sobrecarga momentânea (vale tentar de novo);
# um que demora é consulta pesada demais (repetir só desperdiçaria tempo).
SEGUNDOS_ERRO_500_RAPIDO = 30
# Caracteres que não precisam ser codificados nos valores da consulta OData
CARACTERES_SEGUROS_NA_URL = "$,()/:'"

DICAS_POR_STATUS = {
    400: "Consulta recusada. Confira o --filtro, os nomes em --colunas e os valores de --param; "
         "se nada disso foi usado, o problema está no próprio objeto no Datasphere (veja a resposta abaixo).",
    401: "Token recusado. Confira as credenciais no .env.",
    403: "Sem permissão. O usuário técnico não tem acesso a este space/objeto: peça ao administrador do Datasphere.",
    404: "Não encontrado. Confira o nome do space/objeto (maiúsculas e minúsculas importam).",
    500: "Erro interno do Datasphere. Em objetos ANALÍTICOS isso costuma acontecer quando a consulta tem "
         "colunas demais: escolha só as necessárias com --colunas (ex.: 5 a 30) ou use --modo relacional "
         "se o objeto tiver. Também pode ser um problema na própria view/parâmetro no Datasphere.",
}


class ErroOData(Exception):
    """Erro ao conversar com a API OData. Guarda o status HTTP e a URL chamada."""

    def __init__(self, mensagem: str, status: int | None = None, url: str | None = None):
        super().__init__(mensagem)
        self.status = status
        self.url = url


# Uma sessão HTTP por thread (reaproveita a conexão e é seguro em paralelo)
_local = threading.local()


def _sessao() -> requests.Session:
    if not hasattr(_local, "sessao"):
        _local.sessao = requests.Session()
    return _local.sessao


def montar_url(url: str, consulta: dict | None = None) -> str:
    """Junta a URL com as opções de consulta ($top, $filter...), mantendo o "$" legível.

    Opções com valor vazio (None ou "") são ignoradas.
    """
    partes = [
        f"{chave}={quote(str(valor), safe=CARACTERES_SEGUROS_NA_URL)}"
        for chave, valor in (consulta or {}).items()
        if valor not in (None, "")
    ]
    if not partes:
        return url
    return url + ("&" if "?" in url else "?") + "&".join(partes)


def _mensagem_de_erro(resposta: requests.Response) -> str:
    try:
        corpo = resposta.json()
        erro = corpo.get("error", corpo) if isinstance(corpo, dict) else corpo
        detalhe = erro.get("message", erro) if isinstance(erro, dict) else erro
        if isinstance(detalhe, dict):
            detalhe = detalhe.get("value", detalhe)
    except ValueError:
        detalhe = resposta.text[:500]

    dica = DICAS_POR_STATUS.get(resposta.status_code, "Veja o detalhe abaixo.")
    url = resposta.url if len(resposta.url) <= 300 else resposta.url[:300] + "…"
    return (
        f"HTTP {resposta.status_code} ao chamar {url}\n"
        f"  Dica: {dica}\n"
        f"  Resposta do servidor: {detalhe}"
    )


def requisitar(url: str, consulta: dict | None = None, aceitar: str = "application/json") -> requests.Response:
    """Faz um GET autenticado, com novas tentativas em falhas temporárias."""
    cfg = carregar_config()
    url_final = montar_url(url, consulta)

    for tentativa in range(1, TENTATIVAS + 1):
        cabecalhos = {"Authorization": f"Bearer {obter_token()}", "Accept": aceitar}
        try:
            resposta = _sessao().get(url_final, headers=cabecalhos, timeout=cfg.timeout)
        except requests.Timeout as erro:
            raise ErroOData(
                f"O servidor demorou mais de {cfg.timeout}s para responder.\n"
                f"  URL: {url_final}\n"
                f"  Aumente ODATA_TIMEOUT no .env ou reduza a consulta (--filtro, --colunas, --limite).",
                url=url_final,
            ) from erro
        except requests.ConnectionError as erro:
            if tentativa == TENTATIVAS:
                raise ErroOData(
                    f"Falha de conexão com {url_final}. Verifique sua internet/VPN.\n  Detalhe: {erro}",
                    url=url_final,
                ) from erro
            time.sleep(2 ** tentativa)
            continue

        if resposta.status_code == 401 and tentativa == 1:
            obter_token(forcar_novo=True)
            continue
        erro_500_rapido = (resposta.status_code == 500
                           and resposta.elapsed.total_seconds() < SEGUNDOS_ERRO_500_RAPIDO)
        if (resposta.status_code in STATUS_TEMPORARIOS or erro_500_rapido) and tentativa < TENTATIVAS:
            try:
                espera = int(resposta.headers.get("Retry-After", ""))
            except ValueError:
                espera = 2 ** tentativa
            time.sleep(min(espera, 60))
            continue
        if resposta.ok:
            return resposta
        raise ErroOData(_mensagem_de_erro(resposta), status=resposta.status_code, url=url_final)

    raise ErroOData(f"Não foi possível obter resposta de {url_final} após {TENTATIVAS} tentativas.", url=url_final)


def get_json(url: str, consulta: dict | None = None) -> dict:
    """GET que devolve a resposta já convertida de JSON para dicionário Python."""
    resposta = requisitar(url, consulta)
    try:
        return resposta.json()
    except ValueError as erro:
        raise ErroOData(f"A resposta de {resposta.url} não é um JSON válido.", resposta.status_code, resposta.url) from erro


def get_xml(url: str) -> bytes:
    """GET para documentos XML (ex.: $metadata). Devolve os bytes para preservar acentos."""
    return requisitar(url, aceitar="application/xml").content


def iterar_paginas(url: str, consulta: dict | None = None) -> Iterator[list[dict]]:
    """Devolve os registros página por página, seguindo o @odata.nextLink até o fim.

    O servidor do Datasphere entrega os dados em blocos (ex.: 8 mil linhas). Quando há
    mais, ele manda um "nextLink" (relativo ao @odata.context) para o próximo bloco.
    """
    proxima = montar_url(url, consulta)
    while proxima:
        corpo = get_json(proxima)
        yield corpo.get("value", [])

        link = corpo.get("@odata.nextLink")
        seguinte = urljoin(corpo.get("@odata.context") or proxima, link) if link else None
        proxima = seguinte if seguinte != proxima else None
