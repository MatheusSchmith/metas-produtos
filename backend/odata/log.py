"""
log.py — Mensagens de progresso na tela e em arquivo (saida/logs/).

Tudo que aparece na tela também fica gravado em saida/logs/<script>_<data>.log,
útil para conferir depois o que aconteceu numa extração longa.
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime

from .config import PASTA_SAIDA


def configurar_log(nome_script: str, nivel: int = logging.INFO) -> logging.Logger:
    pasta_logs = PASTA_SAIDA / "logs"
    pasta_logs.mkdir(parents=True, exist_ok=True)

    # Evita erro ao mostrar acentos em terminais antigos do Windows
    for fluxo in (sys.stdout, sys.stderr):
        if hasattr(fluxo, "reconfigure"):
            fluxo.reconfigure(errors="replace")

    raiz = logging.getLogger()
    raiz.setLevel(nivel)
    for manipulador in list(raiz.handlers):
        raiz.removeHandler(manipulador)

    tela = logging.StreamHandler(sys.stdout)
    tela.setFormatter(logging.Formatter("%(asctime)s | %(message)s", datefmt="%H:%M:%S"))
    raiz.addHandler(tela)

    arquivo = logging.FileHandler(pasta_logs / f"{nome_script}_{datetime.now():%Y%m%d}.log", encoding="utf-8")
    arquivo.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s"))
    raiz.addHandler(arquivo)

    # Bibliotecas externas só falam se for algo importante
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    return logging.getLogger(nome_script)
