"""
descobrir_produtos.py — Confere no Datasphere a grafia exata dos agrupadores dos produtos da API.

Uso (na pasta backend/, com o .env preenchido):
    python scripts/descobrir_produtos.py                      # mês de hoje
    python scripts/descobrir_produtos.py --anomes 202609      # outro mês
    python scripts/descobrir_produtos.py --termos suco sabor  # outros pedaços de nome

Lista os agrupadores do mês cujo nome contém algum dos termos (sem acento e sem caixa), com a soma do
faturado (FX_VOL_PADRAO_FAT) e da META_VOLUME (a META_NEG do mês inteiro passa do limite de registros do
Datasphere, por isso fica de fora), e diz se cada agrupador de
mapeamento.PRODUTOS existe com essa grafia. Relatório em saida/descoberta/produtos.md.
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gerador import calendario  # noqa: E402
from gerador import mapeamento as M  # noqa: E402
from gerador.consulta import Consulta, eq  # noqa: E402
from gerador.mapeamento import ColMeta as CM  # noqa: E402
from gerador.texto import limpar, normalizar, numero  # noqa: E402
from odata.config import PASTA_SAIDA, carregar_config  # noqa: E402
from odata.log import configurar_log  # noqa: E402

TERMOS_PADRAO = ["SUCO", "POWERADE", "SABOR", "RETORN"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--anomes", help="AAAAMM (padrão: mês de hoje)")
    ap.add_argument("--termos", nargs="+", help="pedaços de nome a procurar")
    args = ap.parse_args()
    log = configurar_log("descobrir_produtos")
    anomes = args.anomes or calendario.agora().strftime("%Y%m")
    termos = [normalizar(t) for t in (args.termos or TERMOS_PADRAO)]
    termos += [normalizar(a) for p in M.PRODUTOS for a in p["agrupadores"]]

    cfg = carregar_config()
    cons = Consulta(cfg)
    obj = cfg.objeto
    log.info("Agrupadores de %s em %s/%s (pode levar alguns minutos)...", anomes, cfg.space, obj)
    fatos = cons.linhas(obj, [CM.AGRUPADOR, CM.VOL_MES], eq(CM.ANOMES, anomes))
    metas = cons.linhas(obj, [CM.META_AGRUPADOR, CM.META_VOLUME], eq(CM.META_ANOMES, anomes))

    tabela: dict = defaultdict(lambda: [0.0, 0.0])
    for l in fatos:
        ag = limpar(l.get(CM.AGRUPADOR))
        tabela[ag][0] += numero(l.get(CM.VOL_MES))
    for l in metas:
        tabela[limpar(l.get(CM.META_AGRUPADOR))][1] += numero(l.get(CM.META_VOLUME))
    achados = sorted(ag for ag in tabela if ag and any(t in normalizar(ag) for t in termos))

    linhas = [f"# Agrupadores para os produtos da API ({anomes})", "",
              f"{len(tabela)} agrupadores no mês; {len(achados)} com os termos {', '.join(sorted(set(termos)))}.", "",
              "| Agrupador (grafia exata) | Faturado | META_VOLUME |", "|---|---:|---:|"]
    linhas += [f"| `{ag}` | {tabela[ag][0]:,.1f} | {tabela[ag][1]:,.1f} |" for ag in achados]
    linhas += ["", "## Produtos configurados em gerador/mapeamento.py", ""]
    exatos = set(tabela)
    for p in M.PRODUTOS:
        for ag in p["agrupadores"]:
            ok = ag in exatos
            linhas.append(f"- {p['nome']}: `{ag}` " + ("encontrado com essa grafia" if ok else
                          "**NÃO encontrado com essa grafia**: troque pelo nome exato da tabela acima"))
    texto = "\n".join(linhas) + "\n"
    destino = PASTA_SAIDA / "descoberta" / "produtos.md"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(texto, encoding="utf-8")
    print(texto)
    log.info("Relatório: %s", destino)
    return 0


if __name__ == "__main__":
    sys.exit(main())
