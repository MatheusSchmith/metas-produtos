"""
Pacote "gerador": transforma os dados do SAP Datasphere (OData) na API de metas x realizado de volume.

Fluxo (scripts/gerar.py):
    fontes.py    : consulta o Datasphere e normaliza as linhas (tipos.Dados)
    simulado.py  : dados fictícios no mesmo formato (sem rede)
    modelo.py    : contas de meta, realizado, tendência e status
    api.py       : monta os JSONs (index, resumo, gerências, rotas, busca)
    validacao.py : confere antes de publicar
    saida.py     : grava de forma atômica e só quando o conteúdo mudou
"""
