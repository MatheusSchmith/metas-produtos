"""
calendario.py — Escalares de calendário do payload (dia útil, ritmo, semana).

Fonte principal: AM_BND_MTR_CALENDARIO_DATA_ATUAL (NO_DIAS_UTEIS_MES, NO_DIA_UTIL).
Se a view falhar, calcula os dias úteis localmente (seg-sex menos feriados nacionais).

Regras (conferidas com o histórico do payload.json):
  - SEMANA_NUM conta a partir da 1ª segunda-feira do mês (5/10/26 = semana 1,
    13/10/26 = semana 2, 28/9/26 = semana 4). Dias antes dela pertencem à última
    semana do mês anterior.
  - SEMANA_TIPO = "par" quando SEMANA_NUM é par, senão "ímpar".
  - DIA_ONTEM = dias úteis já fechados; PACE_ONTEM_PCT = round(DIA_ONTEM / TOTAL * 100).
  - DATA_ONTEM = data do dia útil DIA_ONTEM (o último fechado) e DIA_ONTEM_NOME = o dia da semana dela
    ("sexta-feira"): pelo calendário do Datasphere (1º dia de semana com NO_DIA_UTIL = DIA_ONTEM); sem a linha,
    o último dia útil local (seg-sex menos feriados nacionais) antes de hoje. No fechamento, o do mês de referência.

Fechamento do mês (em_fechamento / fechado): do dia 1 do mês M até o fim do 1º dia útil de M, e
depois disso enquanto alguma gerência ainda não tiver as metas de M, o payload mostra o mês M-1
fechado (DIA_ONTEM = DIA_HOJE = TOTAL de M-1, PACE_ONTEM_PCT = 100, MES_LABEL de M-1).
"""
from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from .tipos import Calendario

FUSO = ZoneInfo("America/Sao_Paulo")
MESES = ["", "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho",
         "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]
DIAS_SEMANA = ["Segunda-feira", "Terça-feira", "Quarta-feira", "Quinta-feira",
               "Sexta-feira", "Sábado", "Domingo"]


def agora() -> datetime:
    """Data e hora de Brasília, sem fuso (é o formato do updatedAt do online.json)."""
    return datetime.now(FUSO).replace(tzinfo=None, microsecond=0)


def _pascoa(ano: int) -> date:
    a, b, c = ano % 19, ano // 100, ano % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mes = (h + l - 7 * m + 114) // 31
    dia = (h + l - 7 * m + 114) % 31 + 1
    return date(ano, mes, dia)


def feriados_nacionais(ano: int) -> set[date]:
    """Feriados nacionais (fixos + Carnaval, Sexta-feira Santa e Corpus Christi)."""
    p = _pascoa(ano)
    fixos = [(1, 1), (4, 21), (5, 1), (9, 7), (10, 12), (11, 2), (11, 15), (11, 20), (12, 25)]
    moveis = [p - timedelta(days=48), p - timedelta(days=47), p - timedelta(days=2), p + timedelta(days=60)]
    return {date(ano, m, d) for m, d in fixos} | set(moveis)


def eh_dia_util(d: date) -> bool:
    """Segunda a sexta, fora dos feriados nacionais."""
    return d.weekday() < 5 and d not in feriados_nacionais(d.year)


def dias_uteis_do_mes(ano: int, mes: int, feriados: set[date] | None = None) -> list[date]:
    feriados = feriados_nacionais(ano) if feriados is None else feriados
    d = date(ano, mes, 1)
    dias = []
    while d.month == mes:
        if d.weekday() < 5 and d not in feriados:
            dias.append(d)
        d += timedelta(days=1)
    return dias


def _primeira_segunda(ano: int, mes: int) -> date:
    d = date(ano, mes, 1)
    return d + timedelta(days=(7 - d.weekday()) % 7)


def semana_do_mes(d: date) -> int:
    seg = _primeira_segunda(d.year, d.month)
    if d < seg:
        anterior = date(d.year, d.month, 1) - timedelta(days=1)
        return semana_do_mes(anterior)
    return (d - seg).days // 7 + 1


def montar(hoje: date, total_dias_uteis: int, dia_util_hoje: int, eh_dia_util: bool = True) -> Calendario:
    """Monta o Calendario a partir do total de dias úteis e do nº do dia útil de hoje.

    Em dia não útil (sábado, domingo, feriado), NO_DIA_UTIL costuma repetir o último
    dia útil: nesse caso todos os dias até ele estão fechados.
    """
    dia_ontem = dia_util_hoje - 1 if eh_dia_util else dia_util_hoje
    dia_ontem = max(0, min(dia_ontem, total_dias_uteis))
    semana = semana_do_mes(hoje)
    anteriores = [d for d in dias_uteis_do_mes(hoje.year, hoje.month) if d < hoje]
    return Calendario(
        hoje=hoje,
        total_dias_uteis=total_dias_uteis,
        dia_hoje=max(1, min(dia_util_hoje, total_dias_uteis)),
        dia_ontem=dia_ontem,
        semana_num=semana,
        semana_tipo="par" if semana % 2 == 0 else "ímpar",
        dia_semana=DIAS_SEMANA[hoje.weekday()],
        mes_label=rotulo_mes(hoje),
        data_ontem=anteriores[-1] if dia_ontem and anteriores else None,
    )


def nome_dia(d: date | None) -> str | None:
    """date(2026, 10, 16) -> 'sexta-feira' (DIA_ONTEM_NOME); None -> None."""
    return DIAS_SEMANA[d.weekday()].lower() if d else None


def data_do_dia_util(linhas: list[dict], ano: int, mes: int, n: int, ate: date | None = None) -> date | None:
    """Data do n-ésimo dia útil do mês pelo calendário do Datasphere: o 1º dia de semana com NO_DIA_UTIL = n (fim de
    semana e feriado repetem o nº do último dia útil, por isso o mais antigo). Sem essa linha (ou n <= 0), None."""
    from .mapeamento import ColCalendario as C

    if n <= 0:
        return None
    achadas = []
    for l in linhas:
        try:
            d = date.fromisoformat(str(l.get(C.DATA) or "")[:10])
            dia = int(float(l.get(C.DIA_UTIL) or 0))
        except ValueError:
            continue
        if d.year == ano and d.month == mes and dia == n and d.weekday() < 5 and (ate is None or d < ate):
            achadas.append(d)
    return min(achadas) if achadas else None


def com_data_ontem(cal: Calendario, linhas: list[dict]) -> Calendario:
    """O calendário com a DATA_ONTEM do Datasphere (dia útil DIA_ONTEM do mês de referência), quando houver a linha;
    senão fica a do cálculo local (montar/fechado)."""
    ref = cal.ref or cal.hoje
    d = data_do_dia_util(linhas, ref.year, ref.month, cal.dia_ontem, cal.hoje)
    return replace(cal, data_ontem=d) if d else cal


def rotulo_mes(d: date) -> str:
    """date(2026, 10, 5) -> 'Outubro/26' (MES_LABEL e fechamentoMes)."""
    return f"{MESES[d.month]}/{d:%y}"


def mes_anterior(d: date) -> date:
    """1º dia do mês anterior ao de `d`."""
    return (date(d.year, d.month, 1) - timedelta(days=1)).replace(day=1)


def em_fechamento(dia_util_hoje: int, metas_ok: bool | None) -> bool:
    """Período de fechamento: até o fim do 1º dia útil do mês (dia_util_hoje <= 1, inclusive os dias
    corridos antes dele) e, a partir daí, enquanto alguma gerência não tiver as metas do mês."""
    return dia_util_hoje <= 1 or not metas_ok


def fechado(hoje: date, ref: date, total_dias_uteis: int) -> Calendario:
    """Calendário do mês `ref` já encerrado, visto em `hoje` (semana e dia da semana são os de hoje)."""
    semana = semana_do_mes(hoje)
    return Calendario(
        hoje=hoje, total_dias_uteis=total_dias_uteis, dia_hoje=total_dias_uteis, dia_ontem=total_dias_uteis,
        semana_num=semana, semana_tipo="par" if semana % 2 == 0 else "ímpar",
        dia_semana=DIAS_SEMANA[hoje.weekday()], mes_label=rotulo_mes(ref),
        fechamento=True, ref=date(ref.year, ref.month, 1),
        data_ontem=(dias_uteis_do_mes(ref.year, ref.month) or [None])[-1],
    )


def calcular_local(hoje: date) -> Calendario:
    """Plano B sem o Datasphere: seg-sex menos feriados nacionais."""
    uteis = dias_uteis_do_mes(hoje.year, hoje.month)
    feitos = [d for d in uteis if d <= hoje]
    if not feitos:   # antes do 1º dia útil do mês: nada fechado ainda
        return montar(hoje, len(uteis), 1, eh_dia_util=True)
    return montar(hoje, len(uteis), len(feitos), eh_dia_util=hoje in uteis)


def _ultima_linha(linhas: list[dict], ano: int, mes: int, ate: date | None = None) -> tuple[date, int, int] | None:
    """(data, NO_DIAS_UTEIS_MES, NO_DIA_UTIL) da última linha do mês (até `ate`) no calendário do Datasphere."""
    from .mapeamento import ColCalendario as C

    melhor = None
    for l in linhas:
        try:
            d = date.fromisoformat(str(l.get(C.DATA) or "")[:10])
            total, dia = int(float(l.get(C.DIAS_UTEIS_MES) or 0)), int(float(l.get(C.DIA_UTIL) or 0))
        except ValueError:
            continue
        if d.year == ano and d.month == mes and (ate is None or d <= ate) and (melhor is None or d > melhor[0]):
            melhor = (d, total, dia)
    return melhor


def do_datasphere(linhas: list[dict], hoje: date) -> Calendario | None:
    """Usa as linhas de AM_BND_MTR_CALENDARIO_DATA_ATUAL (DATA, NO_DIAS_UTEIS_MES, NO_DIA_UTIL).

    Devolve None se não houver linha do mês de hoje (o chamador cai no cálculo local).
    """
    ult = _ultima_linha(linhas, hoje.year, hoje.month, hoje)
    if not ult:
        return None
    d, total, dia = ult
    if total <= 0 or dia <= 0:
        return None
    return com_data_ontem(montar(hoje, total, dia, eh_dia_util=(d == hoje and hoje.weekday() < 5)), linhas)


def dia_util_hoje(linhas: list[dict], hoje: date) -> int:
    """Nº do dia útil de hoje (0 antes do 1º dia útil; em fim de semana/feriado, o último dia útil).

    Fonte: NO_DIA_UTIL do calendário do Datasphere; sem linha do mês, o cálculo local (seg-sex - feriados).
    """
    ult = _ultima_linha(linhas, hoje.year, hoje.month, hoje)
    if ult and ult[1] > 0:
        return max(0, ult[2])
    return sum(1 for d in dias_uteis_do_mes(hoje.year, hoje.month) if d <= hoje)


def total_dias_uteis(linhas: list[dict], ref: date) -> int:
    """Dias úteis do mês de `ref` (calendário do Datasphere ou, sem ele, cálculo local)."""
    ult = _ultima_linha(linhas, ref.year, ref.month)
    if ult and ult[1] > 0:
        return ult[1]
    return len(dias_uteis_do_mes(ref.year, ref.month))
