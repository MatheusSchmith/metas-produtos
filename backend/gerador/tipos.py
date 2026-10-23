"""
tipos.py — Formato intermediário (normalizado) entre o Datasphere e os JSONs da API.

fontes.py (dados reais) e simulado.py (dados fictícios) preenchem `Dados`; api.py só lê daqui.
Assim a montagem da API é testada sem rede.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime


@dataclass(frozen=True)
class Calendario:
    hoje: date
    total_dias_uteis: int
    dia_hoje: int          # nº do dia útil de hoje (1..total)
    dia_ontem: int         # dias úteis já fechados (0 no 1º dia útil)
    semana_num: int
    semana_tipo: str       # "par" | "ímpar"
    dia_semana: str        # "Terça-feira"
    mes_label: str         # "Outubro/26" (mês de referência)
    # Fechamento do mês: a API mostra o mês anterior (ref) já fechado, sem tendência nem meta do dia
    fechamento: bool = False
    ref: date | None = None    # 1º dia do mês de referência; None = mês de hoje
    data_ontem: date | None = None

    @property
    def pace_ontem_pct(self) -> int:
        """Ritmo esperado: % dos dias úteis já fechados."""
        return round(self.dia_ontem / self.total_dias_uteis * 100) if self.total_dias_uteis else 0

    @property
    def anomes(self) -> str:
        """ANOMES_REF do mês de referência (o anterior durante o fechamento)."""
        return (self.ref or self.hoje).strftime("%Y%m")


@dataclass(frozen=True)
class Cliente:
    pv: int
    nome: str
    rota: str
    gc: str            # sigla da gerência ('G1', 'IT', 'MO'...)
    sv: str            # 'SV.G1.1'
    nome_sv: str
    vendedor: str
    segmento: str = ""


@dataclass
class VolumeRota:
    """Volume de um produto em uma rota (critério do SAC).

    Tendência = real + neg_restante; % tendência = tendência / meta (meta da rota).
    """
    meta: float | None              # META_VOLUME da rota (modelo.meta_e_restante); None = sem meta
    real: float = 0.0               # Vol Real: faturado no mês com NF_STATUS em M.STATUS_NF_REAL
    neg_restante: float | None = None   # parte da meta ainda por vir (curva META_NEG); None no fechamento
    meta_dia: float | None = None       # META_RECUPERAVEL_ROTA de hoje; None = medida não veio / fechamento


@dataclass
class Dados:
    """Tudo o que a API precisa, já normalizado."""
    agora: datetime
    cal: Calendario
    clientes: list[Cliente]
    # rota -> produto -> VolumeRota
    volume: dict[str, dict[str, VolumeRota]]
    # rota -> pv -> produto -> (META_NEG do cliente no mês ou None, Vol Real do cliente)
    volume_cliente: dict[str, dict[int, dict[str, tuple[float | None, float]]]]
    # rota -> produto -> volume dos pedidos de hoje (WF Online); None = online indisponível (ex.: fechamento)
    online: dict[str, dict[str, float]] | None = None
    # rota -> pv -> produto -> volume dos pedidos de hoje
    online_cliente: dict[str, dict[int, dict[str, float]]] = field(default_factory=dict)
    # rotas ocultas com o Real de clientes em rotas EV* (rota -> sigla da gerência)
    eventuais: dict[str, str] = field(default_factory=dict)
    avisos: list[str] = field(default_factory=list)
    simulado: bool = False
