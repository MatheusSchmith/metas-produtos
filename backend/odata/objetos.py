"""
objetos.py — Lista os OBJETOS (views, tabelas, modelos analíticos) expostos via OData.

Cada objeto do catálogo pode ser consumido de duas formas:
  - RELACIONAL: linha a linha, como uma tabela comum (o mais rápido e simples);
  - ANALÍTICO: dados agregados por dimensões e medidas (modelos analíticos).
Alguns objetos exigem PARÂMETROS (ex.: ano/mês) para devolver dados.
"""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote

from .cliente import ErroOData, iterar_paginas
from .config import carregar_config

RELACIONAL = "relacional"
ANALITICO = "analitico"


@dataclass(frozen=True)
class Objeto:
    nome: str
    rotulo: str
    space: str
    url_dados_relacional: str | None
    url_metadados_relacional: str | None
    url_dados_analitico: str | None
    url_metadados_analitico: str | None
    consulta_analitica: bool
    tem_parametros: bool

    @classmethod
    def do_catalogo(cls, item: dict) -> "Objeto":
        """Converte um item do catálogo (JSON da API) em um Objeto."""
        return cls(
            nome=item["name"],
            rotulo=item.get("label") or item["name"],
            space=item["spaceName"],
            url_dados_relacional=item.get("assetRelationalDataUrl"),
            url_metadados_relacional=item.get("assetRelationalMetadataUrl"),
            url_dados_analitico=item.get("assetAnalyticalDataUrl"),
            url_metadados_analitico=item.get("assetAnalyticalMetadataUrl"),
            consulta_analitica=bool(item.get("supportsAnalyticalQueries")),
            tem_parametros=bool(item.get("hasParameters")),
        )

    @property
    def modos_disponiveis(self) -> list[str]:
        modos = []
        if self.url_dados_relacional:
            modos.append(RELACIONAL)
        if self.url_dados_analitico:
            modos.append(ANALITICO)
        return modos

    @property
    def modo_padrao(self) -> str:
        """Relacional quando existir (mais rápido); senão analítico."""
        if not self.modos_disponiveis:
            raise ErroOData(f"O objeto {self.space}/{self.nome} não tem nenhuma URL de dados no catálogo.")
        return self.modos_disponiveis[0]

    @property
    def tipo(self) -> str:
        nomes = {RELACIONAL: "Relacional", ANALITICO: "Analítico"}
        return " + ".join(nomes[m] for m in self.modos_disponiveis) or "Sem dados"

    def _validar_modo(self, modo: str | None) -> str:
        modo = modo or self.modo_padrao
        if modo not in self.modos_disponiveis:
            raise ErroOData(
                f"O objeto {self.space}/{self.nome} não pode ser lido no modo '{modo}'. "
                f"Modos disponíveis: {', '.join(self.modos_disponiveis)}."
            )
        return modo

    def url_dados(self, modo: str | None = None) -> str:
        modo = self._validar_modo(modo)
        return self.url_dados_relacional if modo == RELACIONAL else self.url_dados_analitico

    def url_metadados(self, modo: str | None = None) -> str:
        modo = self._validar_modo(modo)
        return self.url_metadados_relacional if modo == RELACIONAL else self.url_metadados_analitico

    def para_dict(self) -> dict:
        return {
            "space": self.space,
            "objeto": self.nome,
            "descricao": self.rotulo,
            "tipo": self.tipo,
            "tem_parametros": "Sim" if self.tem_parametros else "Não",
            "url_dados_relacional": self.url_dados_relacional,
            "url_dados_analitico": self.url_dados_analitico,
            "url_metadados_relacional": self.url_metadados_relacional,
            "url_metadados_analitico": self.url_metadados_analitico,
        }


def listar_objetos(space: str | None = None) -> list[Objeto]:
    """Devolve os objetos acessíveis. Sem `space`, traz os de todos os spaces."""
    url_catalogo = carregar_config().url_catalogo
    if space:
        nome_escapado = quote(space.replace("'", "''"), safe="")
        url = f"{url_catalogo}/spaces('{nome_escapado}')/assets"
    else:
        url = f"{url_catalogo}/assets"

    objetos = [Objeto.do_catalogo(item) for pagina in iterar_paginas(url) for item in pagina]
    return sorted(objetos, key=lambda o: (o.space, o.nome))


def buscar_objeto(space: str, nome: str) -> Objeto:
    """Encontra um objeto pelo nome dentro de um space (ignora maiúsculas/minúsculas)."""
    try:
        objetos = listar_objetos(space)
    except ErroOData as erro:
        if erro.status == 404:
            raise ErroOData(
                f"Space '{space}' não encontrado. Rode scripts/02_listar_spaces.py para ver os nomes disponíveis.",
                status=404,
            ) from erro
        raise

    for objeto in objetos:
        if objeto.nome.upper() == nome.upper():
            return objeto
    raise ErroOData(
        f"Objeto '{nome}' não encontrado no space '{space}'.\n"
        f"  Rode scripts/03_listar_objetos.py para ver os nomes disponíveis.",
        status=404,
    )
