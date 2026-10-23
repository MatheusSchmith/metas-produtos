"""
Pacote "odata": acesso à API OData de consumo do SAP Datasphere.

Copiado do kit Teste_ODATA (mesmos nomes e comportamento), sem os módulos que
dependem de pandas/openpyxl, que o gerador não usa.

    config.py       -> lê o .env / variáveis de ambiente
    autenticacao.py -> obtém o token OAuth (client credentials)
    cliente.py      -> GET com novas tentativas e paginação (@odata.nextLink)
    spaces.py       -> lista os spaces
    objetos.py      -> lista os objetos de cada space
    metadados.py    -> lê colunas e parâmetros ($metadata)
"""
from .autenticacao import ErroAutenticacao, obter_token
from .cliente import ErroOData, get_json, iterar_paginas, montar_url
from .config import PASTA_SAIDA, ErroConfiguracao, carregar_config

__all__ = [
    "PASTA_SAIDA", "ErroAutenticacao", "ErroConfiguracao", "ErroOData",
    "carregar_config", "get_json", "iterar_paginas", "montar_url", "obter_token",
]
