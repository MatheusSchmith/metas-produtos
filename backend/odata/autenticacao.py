"""
autenticacao.py — Obtém o "crachá" (token de acesso) para conversar com a API.

Fluxo OAuth 2.0 "Client Credentials":
  1. Enviamos o Client ID + Secret para a Token URL.
  2. Recebemos um token (texto longo) válido por algumas horas.
  3. Esse token vai em todas as chamadas seguintes no cabeçalho "Authorization".

O token fica guardado em memória e é renovado sozinho quando está perto de expirar.
"""
from __future__ import annotations

import threading
import time

import requests

from .config import carregar_config

# Renova o token 5 minutos antes de ele expirar, para nunca usar um token vencido
MARGEM_RENOVACAO_SEGUNDOS = 300


class ErroAutenticacao(Exception):
    """Não foi possível obter o token (credencial errada, URL errada, sem internet...)."""


_trava = threading.Lock()
_token_atual: str | None = None
_expira_em: float = 0.0


def obter_token(forcar_novo: bool = False) -> str:
    """Devolve um token válido, pedindo um novo somente quando necessário."""
    global _token_atual, _expira_em

    with _trava:
        if not forcar_novo and _token_atual and time.time() < _expira_em - MARGEM_RENOVACAO_SEGUNDOS:
            return _token_atual

        cfg = carregar_config()
        try:
            resposta = requests.post(
                cfg.token_url,
                data={"grant_type": "client_credentials"},
                auth=(cfg.client_id, cfg.client_secret),
                headers={"Accept": "application/json"},
                timeout=60,
            )
        except requests.RequestException as erro:
            raise ErroAutenticacao(
                f"Não foi possível conectar na Token URL ({cfg.token_url}).\n"
                f"  Verifique sua internet/VPN e o valor de DATASPHERE_TOKEN_URL no .env.\n"
                f"  Detalhe técnico: {erro}"
            ) from erro

        if resposta.status_code in (400, 401):
            raise ErroAutenticacao(
                "As credenciais foram recusadas pelo servidor de autenticação.\n"
                "  Confira DATASPHERE_CLIENT_ID e DATASPHERE_CLIENT_SECRET no .env\n"
                "  (devem estar entre aspas simples) e se o OAuth Client ainda existe no Datasphere."
            )
        if not resposta.ok:
            raise ErroAutenticacao(
                f"A Token URL respondeu com erro HTTP {resposta.status_code}: {resposta.text[:300]}"
            )

        dados = resposta.json()
        _token_atual = dados["access_token"]
        _expira_em = time.time() + int(dados.get("expires_in", 3600))
        return _token_atual
