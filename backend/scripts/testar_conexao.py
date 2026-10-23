"""
testar_conexao.py — Confere, passo a passo, se o back-end consegue falar com o SAP Datasphere.

Uso (na pasta backend/, com o .env preenchido):
    python scripts/testar_conexao.py

Etapas: 1) lê o .env; 2) pede o token OAuth; 3) lista os spaces; 4) acha os modelos usados pelo gerador
no space (DATASPHERE_SPACE) e confere as colunas de gerador/mapeamento.py; 5) lê o total faturado do mês.
Para na primeira que falhar e diz o que conferir.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gerador import calendario  # noqa: E402
from gerador import mapeamento as M  # noqa: E402
from gerador.consulta import Consulta, eq  # noqa: E402
from gerador.mapeamento import ColMeta as CM  # noqa: E402
from gerador.texto import numero  # noqa: E402
from odata.autenticacao import obter_token  # noqa: E402
from odata.config import carregar_config  # noqa: E402
from odata.log import configurar_log  # noqa: E402
from odata.spaces import listar_spaces  # noqa: E402


def _colunas(classe) -> set[str]:
    return {v for k, v in vars(classe).items() if k.isupper() and isinstance(v, str)}


def main() -> int:
    log = configurar_log("testar_conexao")
    passo = "ler o .env"
    try:
        cfg = carregar_config()
        log.info("1/5 Configuração OK: tenant %s, space %s, modelo %s", cfg.tenant_url, cfg.space, cfg.objeto)

        passo = "obter o token"
        t0 = time.time()
        obter_token()
        log.info("2/5 Token OK (%.1f s)", time.time() - t0)

        passo = "listar os spaces"
        spaces = listar_spaces()
        nomes = [s.nome for s in spaces]
        log.info("3/5 Catálogo OK: %d space(s) acessível(is): %s", len(nomes), ", ".join(nomes) or "nenhum")
        if cfg.space not in nomes:
            log.error("O space %s não aparece para este usuário. Confira DATASPHERE_SPACE ou peça acesso à TI.",
                      cfg.space)
            return 1

        passo = "encontrar os modelos"
        cons = Consulta(cfg)
        modelos = {cfg.objeto: M.ColMeta, M.OBJ_BASE_CLIENTE: M.ColBase, M.OBJ_CALENDARIO: M.ColCalendario}
        faltam = []
        for nome, classe in modelos.items():
            existentes = set(cons.colunas(nome))
            ausentes = sorted(_colunas(classe) - existentes)
            faltam += [f"{nome}.{c}" for c in ausentes]
            log.info("4/5 Modelo OK: %s (%d colunas)%s", nome, len(existentes),
                     f" — FALTAM: {', '.join(ausentes)}" if ausentes else "")
        if faltam:
            log.error("Colunas de gerador/mapeamento.py que não existem no Datasphere: %s", ", ".join(faltam))
            return 1

        passo = "ler o faturado do mês"
        anomes = calendario.agora().strftime("%Y%m")
        t0 = time.time()
        linhas = cons.linhas(cfg.objeto, [CM.ANOMES, CM.VOL_MES], eq(CM.ANOMES, anomes))
        total = sum(numero(l.get(CM.VOL_MES)) for l in linhas)
        log.info("5/5 Leitura OK (%.1f s): faturado de %s = %s (volume padrão)", time.time() - t0, anomes,
                 f"{total:,.1f}".replace(",", "X").replace(".", ",").replace("X", "."))
    except Exception as erro:  # noqa: BLE001 — a mensagem das exceções do projeto já diz o que conferir
        log.error("Falhou ao %s:\n%s", passo, erro)
        return 1

    log.info("Conexão com o Datasphere funcionando.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
