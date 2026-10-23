"""
config.py — Lê as configurações do arquivo .env (local) ou das variáveis de ambiente (nuvem).

Tudo que muda de um ambiente para outro (endereço do tenant, credenciais, tempo
limite...) fica fora do código:
  - na máquina: backend/.env (copie de backend/.env.example);
  - no GitHub Actions: Secrets e Variables do repositório, com os MESMOS nomes.
Variáveis já definidas no ambiente têm prioridade sobre o .env.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

# Pasta raiz do back-end (onde fica o .env) e pasta de trabalho (logs, cache, descoberta)
RAIZ_PROJETO = Path(__file__).resolve().parent.parent
PASTA_SAIDA = RAIZ_PROJETO / "saida"
# Onde o gerador grava a API (pasta api/ na raiz do repositório; os arquivos ficam em api/v1/)
PASTA_DADOS_PADRAO = RAIZ_PROJETO.parent / "api"

# Caminho padrão da API de consumo do SAP Datasphere
CAMINHO_API_CONSUMO = "/api/v1/datasphere/consumption"


class ErroConfiguracao(Exception):
    """Falta (ou está errada) alguma informação no .env / variáveis de ambiente."""


@dataclass(frozen=True)
class Config:
    tenant_url: str
    token_url: str
    client_id: str
    client_secret: str
    timeout: int
    max_workers: int
    space_padrao: str | None
    space: str
    objeto: str
    pasta_dados: Path

    @property
    def url_consumo(self) -> str:
        """Ex.: https://tenant.../api/v1/datasphere/consumption"""
        return self.tenant_url + CAMINHO_API_CONSUMO

    @property
    def url_catalogo(self) -> str:
        """Serviço que lista spaces e objetos disponíveis para o usuário."""
        return self.url_consumo + "/catalog"


def _ler(nome: str, obrigatoria: bool = True) -> str | None:
    valor = (os.getenv(nome) or "").strip()
    if not valor and obrigatoria:
        raise ErroConfiguracao(
            f"A variável {nome} não está preenchida.\n"
            f"  Local: preencha backend/.env (modelo em backend/.env.example).\n"
            f"  Nuvem: cadastre-a em Settings > Secrets and variables > Actions (veja o README)."
        )
    return valor or None


def _ler_inteiro(nome: str, padrao: int) -> int:
    valor = _ler(nome, obrigatoria=False)
    if valor is None:
        return padrao
    try:
        return int(valor)
    except ValueError:
        raise ErroConfiguracao(
            f"A variável {nome} deve ser um número inteiro (valor atual: {valor!r})."
        ) from None


def _pasta(valor: str | None) -> Path:
    if not valor:
        return PASTA_DADOS_PADRAO
    caminho = Path(valor)
    return caminho if caminho.is_absolute() else (RAIZ_PROJETO / caminho).resolve()


@lru_cache(maxsize=1)
def carregar_config() -> Config:
    """Lê o .env (se existir) uma única vez e devolve as configurações prontas para uso."""
    arquivo_env = RAIZ_PROJETO / ".env"
    if not arquivo_env.exists() and not os.getenv("DATASPHERE_TENANT_URL"):
        raise ErroConfiguracao(
            f"Arquivo {arquivo_env} não encontrado e as variáveis DATASPHERE_* não estão definidas.\n"
            f"  Local: copie backend/.env.example para backend/.env e preencha.\n"
            f"  Nuvem: cadastre os Secrets/Variables no GitHub (veja o README)."
        )
    load_dotenv(arquivo_env, override=False)

    return Config(
        tenant_url=_ler("DATASPHERE_TENANT_URL").rstrip("/"),
        token_url=_ler("DATASPHERE_TOKEN_URL"),
        client_id=_ler("DATASPHERE_CLIENT_ID"),
        client_secret=_ler("DATASPHERE_CLIENT_SECRET"),
        timeout=_ler_inteiro("ODATA_TIMEOUT", 300),
        max_workers=max(1, _ler_inteiro("ODATA_MAX_WORKERS", 6)),
        space_padrao=_ler("SPACE_PADRAO", obrigatoria=False),
        space=_ler("DATASPHERE_SPACE", obrigatoria=False) or "DW_BND_COM_SAP",
        objeto=_ler("DATASPHERE_ASSET", obrigatoria=False) or "AM_FAT_BND_ANALISE_META",
        pasta_dados=_pasta(_ler("SAIDA_DIR", obrigatoria=False)),
    )
