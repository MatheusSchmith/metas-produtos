"""
gerar.py — Busca os dados no SAP Datasphere e grava a API (JSONs) em api/v1/.

Uso (na pasta backend/):
    python scripts/gerar.py                       # dados reais -> ../api/v1
    python scripts/gerar.py --simulado --forcar   # dados FICTÍCIOS (sem Datasphere), para o front
    python scripts/gerar.py --rota 111 --forcar   # testa uma rota, grava em saida/rota_111/
    python scripts/gerar.py --hoje 2026-11-03 --saida saida/sim --forcar   # simula a data

Fechamento do mês: detectado sozinho (até o fim do 1º dia útil e enquanto alguma gerência não tiver
META_VOLUME do mês). Nesse período a API mostra o mês anterior fechado.

Fora da janela de execução (JANELA_EXECUCAO, padrão 07:00-18:59 de Brasília) termina sem fazer nada,
a não ser com --forcar. Códigos de saída: 0 ok / nada a fazer, 1 erro de execução,
2 dados reprovados na validação (nada é gravado).
"""
from __future__ import annotations

import argparse
import os
import sys
import time as relogio
from datetime import datetime, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gerador import api, calendario, saida, validacao  # noqa: E402
from odata.config import PASTA_DADOS_PADRAO, PASTA_SAIDA  # noqa: E402
from odata.log import configurar_log  # noqa: E402


def _janela(texto: str) -> tuple[time, time]:
    ini, fim = texto.split("-")
    return time.fromisoformat(ini.strip()), time.fromisoformat(fim.strip())


def _github_output(**valores: str) -> None:
    destino = os.getenv("GITHUB_OUTPUT")
    if destino:
        with open(destino, "a", encoding="utf-8") as f:
            for k, v in valores.items():
                f.write(f"{k}={v}\n")


def _pasta(valor: str | None) -> Path:
    if not valor:
        return PASTA_DADOS_PADRAO
    caminho = Path(valor)
    return caminho if caminho.is_absolute() else (Path(__file__).resolve().parent.parent / caminho).resolve()


def _especies(cons, dados, destino: Path, log) -> dict[str, dict]:
    """Arquivos v1/especies/* (tela de filtros). Se a consulta falhar, mantém os que já estão gravados."""
    from gerador import especies
    ref = (dados.cal.ref or dados.cal.hoje).replace(day=1)
    try:
        return especies.montar(cons, ref, destino, dados.clientes, dados.cal.hoje)
    except Exception as erro:  # noqa: BLE001
        log.warning("Aviso: espécies não atualizadas (%s); mantidos os arquivos anteriores", erro)
        pasta = destino / "v1" / "especies"
        return {f"v1/{c.relative_to(destino / 'v1').as_posix()}": obj
                for c in pasta.rglob("*.json") if (obj := saida.ler(c))}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--saida", type=Path, help="pasta de destino (padrão: SAIDA_DIR ou ../api)")
    ap.add_argument("--simulado", action="store_true", help="dados fictícios, sem consultar o Datasphere")
    ap.add_argument("--rota", help="restringe a uma rota (teste); grava em saida/rota_<ROTA>/")
    ap.add_argument("--hoje", help="simula a data (AAAA-MM-DD); o agendamento não usa")
    ap.add_argument("--forcar", action="store_true", help="ignora a janela de horário")
    ap.add_argument("--gravar-cache", type=Path, help="salva as respostas do Datasphere nesta pasta")
    ap.add_argument("--replay", type=Path, help="usa respostas salvas (sem rede)")
    args = ap.parse_args()

    log = configurar_log("gerar")
    inicio = relogio.monotonic()
    agora = calendario.agora()
    if args.hoje:
        agora = datetime.combine(datetime.fromisoformat(args.hoje).date(), agora.time())

    ini, fim = _janela(os.getenv("JANELA_EXECUCAO", "07:00-18:59"))
    if not args.forcar and not (ini <= agora.time() <= fim):
        log.info("Fora da janela %s-%s (agora %s). Nada a fazer.", ini, fim, agora.time())
        _github_output(mudou="false")
        return 0

    destino = args.saida or (PASTA_SAIDA / f"rota_{args.rota}" if args.rota else _pasta(os.getenv("SAIDA_DIR")))
    try:
        if args.simulado:
            from gerador import simulado
            log.warning("Gerando dados SIMULADOS (fictícios) -> %s", destino)
            dados = simulado.gerar(agora)
        else:
            from gerador import fontes, mapeamento
            from gerador.consulta import Consulta
            from odata.config import carregar_config
            cfg = carregar_config()
            mapeamento.OBJ_META = cfg.objeto
            cons = Consulta(cfg, pasta_cache=args.replay or args.gravar_cache,
                            gravar=bool(args.gravar_cache), replay=bool(args.replay))
            log.info("Gerando dados de %s (space %s, modelo %s) -> %s", agora, cfg.space, cfg.objeto, destino)
            dados = fontes.carregar(cons, agora, rota=args.rota)
    except Exception as erro:  # noqa: BLE001
        log.error("Falha ao montar os dados: %s", erro)
        _github_output(mudou="false")
        return 1

    arquivos = api.montar(dados)
    if not args.simulado and not args.rota:
        arquivos.update(_especies(cons, dados, destino, log))
    anterior = (None, None) if args.rota else (saida.ler(destino / "v1/resumo.json"), saida.ler(destino / "v1/index.json"))
    erros, avisos = validacao.validar(arquivos, *anterior)
    for a in avisos + dados.avisos:
        log.warning("Aviso: %s", a)
    if erros:
        for e in erros:
            log.error("Reprovado: %s", e)
        log.error("Nada foi gravado; o site continua com a versão anterior.")
        _github_output(mudou="false")
        return 2

    total = sum(len(saida.serializar(o)) for o in arquivos.values())
    log.info("%d arquivos, %.2f MB no total", len(arquivos), total / 1e6)
    gravados, apagados = saida.gravar_api(destino, arquivos)
    log.info("Gravados: %d; apagados: %d (%.0f s no total)", len(gravados), len(apagados), relogio.monotonic() - inicio)
    mudou = bool(gravados or apagados)
    _github_output(mudou="true" if mudou else "false")
    return 0


if __name__ == "__main__":
    sys.exit(main())
