"""
saida.py — Serialização estável e gravação atômica dos JSONs.

  - JSON compacto (separators sem espaço): ~25% menor que o arquivo antigo.
  - Mesma entrada => mesmos bytes (a ordem das chaves é montada de forma determinística),
    então o GitHub Actions só faz commit quando o dado mudou de verdade.
  - Grava em arquivo temporário e troca de uma vez (os.replace): o site nunca
    serve um JSON pela metade.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path


def serializar(obj: dict) -> bytes:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def gravar(caminho: Path, obj: dict) -> bool:
    """Grava `obj` em `caminho` se o conteúdo mudou. Devolve True quando gravou."""
    dados = serializar(obj)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    if caminho.exists() and caminho.read_bytes() == dados:
        return False
    temporario = caminho.with_suffix(caminho.suffix + ".tmp")
    temporario.write_bytes(dados)
    for tentativa in range(10):
        try:
            os.replace(temporario, caminho)
            return True
        except PermissionError:   # Windows: o arquivo está aberto (navegador/servidor local lendo) — espera e repete
            if tentativa == 9:
                raise
            time.sleep(0.5)
    return True


def ler(caminho: Path) -> dict | None:
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def gravar_api(pasta: Path, arquivos: dict[str, dict], subpasta: str = "v1") -> tuple[list[str], list[str]]:
    """Grava todos os arquivos da API (só os que mudaram) e apaga os .json de `subpasta` que não existem mais
    (ex.: rota extinta). Devolve (gravados, apagados), com caminhos relativos a `pasta`."""
    gravados = [rel for rel, obj in sorted(arquivos.items()) if gravar(pasta / rel, obj)]
    apagados = []
    raiz = pasta / subpasta
    if raiz.exists():
        for caminho in sorted(raiz.rglob("*.json")):
            rel = caminho.relative_to(pasta).as_posix()
            if rel not in arquivos:
                caminho.unlink()
                apagados.append(rel)
    return gravados, apagados
