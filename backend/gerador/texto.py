"""Funções pequenas de texto usadas na normalização dos dados do Datasphere."""
from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, timezone

_ESPACOS = re.compile(r"\s+")
_DATA_MS = re.compile(r"/Date\((-?\d+)")


def normalizar(valor: object) -> str:
    """Chave de comparação: maiúsculas, sem acentos e com espaços simples.

    'Água  Mineral ' -> 'AGUA MINERAL'
    """
    if valor is None:
        return ""
    texto = unicodedata.normalize("NFKD", str(valor))
    texto = "".join(ch for ch in texto if not unicodedata.combining(ch))
    return _ESPACOS.sub(" ", texto).strip().upper()


def limpar(valor: object) -> str:
    """Texto para exibição: sem espaços sobrando (mantém maiúsculas/acentos)."""
    if valor is None:
        return ""
    return _ESPACOS.sub(" ", str(valor)).strip()


def titulo(valor: object) -> str:
    """'BAR E MERC DUTRA' -> 'Bar E Merc Dutra' (mesmo formato do payload atual)."""
    return " ".join(p[:1].upper() + p[1:].lower() for p in limpar(valor).split(" ") if p)


def inteiro(valor: object) -> int | None:
    """Converte códigos como '0001007382' ou 1007382.0 em 1007382; None se não for número."""
    if valor is None:
        return None
    texto = str(valor).strip()
    if not texto:
        return None
    try:
        return int(float(texto)) if "." in texto else int(texto)
    except ValueError:
        return None


def numero(valor: object) -> float:
    """Medida do OData (pode vir como string decimal) -> float; vazio vira 0."""
    if valor is None or valor == "":
        return 0.0
    try:
        return float(valor)
    except (TypeError, ValueError):
        return 0.0


def data(valor: object) -> date | None:
    """DATA_MOVIMENTO do OData -> date: '2026-10-17', '2026-10-17T00:00:00', '20261017' ou '/Date(ms)/'."""
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    texto = limpar(valor)
    m = _DATA_MS.match(texto)
    if m:
        return datetime.fromtimestamp(int(m.group(1)) / 1000, tz=timezone.utc).date()
    try:
        if len(texto) == 8 and texto.isdigit():
            return date(int(texto[:4]), int(texto[4:6]), int(texto[6:]))
        return date.fromisoformat(texto[:10])
    except ValueError:
        return None
