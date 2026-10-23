"""
spaces.py — Lista os SPACES que o seu usuário pode acessar.

No SAP Datasphere, um "space" é como um schema/pasta de um banco de dados:
agrupa tabelas, views e modelos de uma área (ex.: Comercial, Financeiro).
"""
from __future__ import annotations

from dataclasses import dataclass

from .cliente import iterar_paginas
from .config import carregar_config


@dataclass(frozen=True)
class Space:
    nome: str     # nome técnico, usado nas URLs (ex.: DW_BND_COM_SAP)
    rotulo: str   # descrição amigável (ex.: Bandeirantes - IM/Comercial)

    def para_dict(self) -> dict:
        return {"space": self.nome, "descricao": self.rotulo}


def listar_spaces() -> list[Space]:
    """Consulta o catálogo e devolve todos os spaces acessíveis, em ordem alfabética."""
    url = f"{carregar_config().url_catalogo}/spaces"
    spaces = [
        Space(nome=item["name"], rotulo=item.get("label") or item["name"])
        for pagina in iterar_paginas(url)
        for item in pagina
    ]
    return sorted(spaces, key=lambda s: s.nome)
