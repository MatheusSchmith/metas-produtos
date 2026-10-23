"""
metadados.py — Lê a "ficha técnica" ($metadata) de um objeto.

O $metadata é um XML que descreve o objeto: nome do conjunto de dados (entity set),
colunas, tipos, descrições, quais colunas são dimensões/medidas e quais PARÂMETROS
o objeto exige. É com ele que o projeto monta as consultas sozinho, sem você
precisar digitar nomes de colunas.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass

from .cliente import ErroOData, get_xml
from .objetos import Objeto

EDM = "http://docs.oasis-open.org/odata/ns/edm"
NS = {"edm": EDM}

DIMENSAO = "Dimensão"
MEDIDA = "Medida"


@dataclass(frozen=True)
class Coluna:
    nome: str
    tipo: str             # tipo OData, ex.: Edm.String, Edm.Decimal, Edm.Date
    rotulo: str           # descrição amigável (quando o Datasphere fornece)
    papel: str            # "Dimensão", "Medida" ou "" (em objetos relacionais costuma vir vazio)
    chave: bool
    anulavel: bool
    tamanho: str | None
    precisao: str | None
    escala: str | None


@dataclass(frozen=True)
class Parametro:
    nome: str
    tipo: str
    rotulo: str
    padrao: str | None    # valor padrão definido no Datasphere (None = obrigatório informar)

    @property
    def obrigatorio(self) -> bool:
        return self.padrao is None


@dataclass(frozen=True)
class Metadados:
    objeto: Objeto
    modo: str
    entity_set: str
    colunas: list[Coluna]
    parametros: list[Parametro]

    @property
    def nomes_colunas(self) -> list[str]:
        return [c.nome for c in self.colunas]

    @property
    def tipos_colunas(self) -> dict[str, str]:
        return {c.nome: c.tipo for c in self.colunas}

    @property
    def dimensoes_e_medidas(self) -> list[str]:
        return [c.nome for c in self.colunas if c.papel in (DIMENSAO, MEDIDA)]

    def para_dict(self) -> dict:
        return {
            "space": self.objeto.space,
            "objeto": self.objeto.nome,
            "descricao": self.objeto.rotulo,
            "modo": self.modo,
            "entity_set": self.entity_set,
            "colunas": [asdict(c) for c in self.colunas],
            "parametros": [asdict(p) for p in self.parametros],
        }


def ler_metadados(objeto: Objeto, modo: str | None = None) -> Metadados:
    """Baixa e interpreta o $metadata do objeto (no modo relacional por padrão)."""
    modo = modo or objeto.modo_padrao
    xml = get_xml(objeto.url_metadados(modo))
    return interpretar_metadados(xml, objeto, modo)


# --------------------------------------------------------------------------
# A partir daqui: leitura do XML. Não é preciso entender para usar o projeto.
# --------------------------------------------------------------------------

def _termo_curto(termo: str) -> str:
    """'Common.Label' ou 'com.sap.vocabularies.Common.v1.Label' -> 'Label'."""
    return (termo or "").rsplit(".", 1)[-1]


def _valor_anotacao(anotacao: ET.Element) -> str:
    for atributo in ("String", "Bool", "EnumMember", "Int", "Decimal", "Path"):
        if anotacao.get(atributo) is not None:
            return anotacao.get(atributo)
    filho = next(iter(anotacao), None)
    if filho is not None and filho.text:
        return filho.text.strip()
    return "true"  # anotação booleana sem valor explícito significa "verdadeiro"


def _anotacoes_inline(elemento: ET.Element) -> dict[str, str]:
    return {_termo_curto(a.get("Term")): _valor_anotacao(a) for a in elemento.findall("edm:Annotation", NS)}


def interpretar_metadados(xml: bytes, objeto: Objeto, modo: str) -> Metadados:
    try:
        raiz = ET.fromstring(xml)
    except ET.ParseError as erro:
        raise ErroOData(f"O $metadata de {objeto.space}/{objeto.nome} não é um XML válido: {erro}") from erro

    tipos: dict[str, ET.Element] = {}            # "Namespace.NomeDoTipo" -> <EntityType>
    nomes_qualificados: dict[int, list[str]] = {}  # id(<EntityType>) -> nomes com namespace e alias
    anotacoes: dict[str, dict[str, str]] = {}    # "Namespace.Tipo/Coluna" -> {"Label": "...", ...}
    conjuntos: list[tuple[str, str]] = []        # (nome do entity set, tipo)

    for schema in raiz.iter(f"{{{EDM}}}Schema"):
        prefixos = [p for p in (schema.get("Namespace"), schema.get("Alias")) if p]
        for tipo in schema.findall("edm:EntityType", NS):
            nomes = [f"{p}.{tipo.get('Name')}" for p in prefixos]
            nomes_qualificados[id(tipo)] = nomes
            for nome in nomes:
                tipos[nome] = tipo
        for conjunto in schema.iterfind("edm:EntityContainer/edm:EntitySet", NS):
            conjuntos.append((conjunto.get("Name"), conjunto.get("EntityType")))
        for grupo in schema.findall("edm:Annotations", NS):
            anotacoes.setdefault(grupo.get("Target"), {}).update(_anotacoes_inline(grupo))

    if not conjuntos:
        raise ErroOData(f"O $metadata de {objeto.space}/{objeto.nome} não tem nenhum EntitySet.")

    # Normalmente o entity set tem o mesmo nome do objeto
    nome_conjunto, nome_tipo = next(
        (c for c in conjuntos if c[0].upper() == objeto.nome.upper()), conjuntos[0]
    )
    tipo_conjunto = tipos.get(nome_tipo)
    if tipo_conjunto is None:
        raise ErroOData(f"Tipo {nome_tipo} não encontrado no $metadata de {objeto.space}/{objeto.nome}.")

    def anotacoes_da_propriedade(tipo: ET.Element, propriedade: ET.Element) -> dict[str, str]:
        resultado: dict[str, str] = {}
        for nome_tipo_q in nomes_qualificados[id(tipo)]:
            resultado.update(anotacoes.get(f"{nome_tipo_q}/{propriedade.get('Name')}", {}))
        resultado.update(_anotacoes_inline(propriedade))
        return resultado

    # Objetos com parâmetros: o entity set aponta para um tipo "...Parameters" que tem
    # uma navegação "Set" levando ao tipo com as colunas de verdade.
    parametros: list[Parametro] = []
    tipo_dados = tipo_conjunto
    navegacao_set = tipo_conjunto.find("edm:NavigationProperty[@Name='Set']", NS)
    if navegacao_set is not None:
        nome_tipo_dados = navegacao_set.get("Type", "").removeprefix("Collection(").removesuffix(")")
        tipo_dados = tipos.get(nome_tipo_dados)
        if tipo_dados is None:
            raise ErroOData(f"Tipo {nome_tipo_dados} não encontrado no $metadata de {objeto.space}/{objeto.nome}.")
        for prop in tipo_conjunto.findall("edm:Property", NS):
            anot = anotacoes_da_propriedade(tipo_conjunto, prop)
            parametros.append(Parametro(
                nome=prop.get("Name"),
                tipo=prop.get("Type", ""),
                rotulo=anot.get("Label", ""),
                padrao=prop.get("DefaultValue"),
            ))

    chaves = {ref.get("Name") for ref in tipo_dados.iterfind("edm:Key/edm:PropertyRef", NS)}
    colunas = []
    for prop in tipo_dados.findall("edm:Property", NS):
        anot = anotacoes_da_propriedade(tipo_dados, prop)
        if anot.get("Measure", "false").lower() == "true":
            papel = MEDIDA
        elif anot.get("Dimension", "false").lower() == "true":
            papel = DIMENSAO
        else:
            papel = ""
        colunas.append(Coluna(
            nome=prop.get("Name"),
            tipo=prop.get("Type", ""),
            rotulo=anot.get("Label", ""),
            papel=papel,
            chave=prop.get("Name") in chaves,
            anulavel=prop.get("Nullable", "true").lower() != "false",
            tamanho=prop.get("MaxLength"),
            precisao=prop.get("Precision"),
            escala=prop.get("Scale"),
        ))

    return Metadados(objeto=objeto, modo=modo, entity_set=nome_conjunto, colunas=colunas, parametros=parametros)
