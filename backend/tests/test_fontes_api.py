"""Consulta -> normalização -> API, com um Datasphere falso e valores conferidos à mão.

Cenário (22/10/2026, dia útil 15 de 21; 14 fechados; ritmo esperado 67%):
  rota 111 (G1, SV.G1.1): clientes 1 e 2   | rota 112 (G1, SV.G1.2): cliente 3
  cliente 9 está numa rota eventual (EV5), gerência comercial G1
  Sucos  111: META_VOLUME 100; META_NEG cli 1 = 40 até ontem + 20 de hoje em diante; cli 2 = 30 + 10
              faturado: cli 1 = 50 Acertado + 10 Cancelada (fora); cli 2 = 20 Em Aberto
              pedidos de hoje: cli 1 = 3 (Inc. e Exp.), cli 2 = 4 (Cancelado, fora); meta do dia 4
  Sucos  112: META_VOLUME 40, sem META_NEG; faturado cli 3 = 15
  Powerade 111: META_VOLUME 50, nada faturado
  EV5 (cliente 9): faturado Sucos 5 -> entra só no total da G1
"""
import sys
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gerador import api, fontes, validacao  # noqa: E402
from gerador import mapeamento as M  # noqa: E402
from tests.falso import ConsultaFalsa  # noqa: E402

AGORA = datetime(2026, 10, 22, 10, 0)


def _fato(rota, pv, ag, fonte="Basis", data="2026-10-10", gc_com="Gc. G1", **medidas):
    return {"ANOMES_REF": "202610", "CD_ROTA_Clien": rota, "DS_GC_AGRUPADA_ATUAL_Clien": "Gc. G1",
            "DS_GERENCIA_COMERCIAL_AT_Clien": gc_com, "CD_CLIENTE": str(pv), "DS_AGRUPADOR_Agrupador_Prod": ag,
            "DATA_MOVIMENTO": data, "FONTE": fonte, "SITUACAO_Pedido": medidas.pop("situacao", "Inc. e Exp."),
            "NF_STATUS_Nota_Fiscal": medidas.pop("nf", "Acertado"),
            "ANOMES_REF_Chave_Meta_SAP": None, "CD_ROTA_Chave_Meta_SAP": medidas.pop("rota_meta", None),
            "AGRUPADOR_PRODU_Chave_Meta_SAP": None, **medidas}


def _meta(rota, ag, valor, anomes="202610"):
    return {"ANOMES_REF": anomes, "ANOMES_REF_Chave_Meta_SAP": anomes, "CD_ROTA_Chave_Meta_SAP": rota,
            "AGRUPADOR_PRODU_Chave_Meta_SAP": ag, "META_VOLUME_Chave_Meta_SAP": valor}


def _cliente(pv, rota, sv):
    return {"CD_ROTA": rota, "CD_CLIENTE": str(pv), "NM_NOME_FANTASIA": f"Cliente {pv}", "DS_SEGMENTO": "Boteco",
            "DS_GC_AGRUPADA_ATUAL": "Gc. G1", "DS_SUPERVISOR_ATUAL": sv, "DS_NOME_SUPERVISOR_ATUAL": f"Nome {sv}",
            "DS_VENDEDOR_ATUAL": f"Vend {rota}", "QUANTIDADE": 1, "FL_CORRENTE": "S", "STATUS_CLIENTE": "Ativo"}


def cenario() -> ConsultaFalsa:
    neg = lambda pv, data, v: _fato("111", pv, "Sucos", fonte="Meta NEG", data=data, situacao="Meta NEG",  # noqa: E731
                                    nf="Meta Neg", rota_meta="111", META_NEG=v)
    meta = [
        _meta("111", "Sucos", 100), _meta("111", "Powerade", 50), _meta("112", "Sucos", 40),
        _meta("999", "Cervejas", 999),   # agrupador fora da API: ignorado
    ]
    fatos = [
        neg(1, "2026-10-10", 40), neg(1, "2026-10-22", 10), neg(1, "2026-10-28", 10),
        neg(2, "2026-10-15", 30), neg(2, "2026-10-23", 10),
        _fato("111", 1, "Sucos", FX_VOL_PADRAO_FAT=50),
        _fato("111", 1, "Sucos", nf="Cancelada", FX_VOL_PADRAO_FAT=10),
        _fato("111", 2, "Sucos", nf="Em Aberto", FX_VOL_PADRAO_FAT=20),
        _fato("112", 3, "Sucos", FX_VOL_PADRAO_FAT=15),
        _fato("112", 3, "SUCOS", FX_VOL_PADRAO_FAT=99),   # grafia diferente: o $filter é exato, fica fora
        _fato("EV5", 9, "Sucos", FX_VOL_PADRAO_FAT=5),
        _fato("111", 1, "Sucos", fonte="WF Online", data="2026-10-22", FX_VOL_PADRAO_WF_ONLINE=3),
        _fato("111", 2, "Sucos", fonte="WF Online", data="2026-10-22", situacao="Cancelado", FX_VOL_PADRAO_WF_ONLINE=4),
        _fato("111", 1, "Sucos", fonte="Meta NEG", data="2026-10-22", rota_meta="111", META_RECUPERAVEL_ROTA=4),
        _fato("111", 1, "Cervejas", FX_VOL_PADRAO_FAT=500),                 # fora da API
    ]
    base = [_cliente(1, "111", "Sv. G1.1"), _cliente(2, "111", "Sv. G1.1"), _cliente(3, "112", "Sv. G1. 2"),
            _cliente(9, "EV5", "Sv. G1.1")]
    cal = [{"DATA": "2026-10-22", "NO_DIAS_UTEIS_MES": 21, "NO_DIA_UTIL": 15, "NO_DIAS_UTEIS_RESTANTES": 7}]
    return ConsultaFalsa({M.OBJ_META: meta + fatos, M.OBJ_BASE_CLIENTE: base, M.OBJ_CALENDARIO: cal},
                         tipos={M.OBJ_META: {"DATA_MOVIMENTO": "Edm.Date"}})


class TestCenario(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dados = fontes.carregar(cenario(), AGORA)
        cls.api = api.montar(cls.dados)

    def test_calendario(self):
        cal = self.api["v1/index.json"]["calendario"]
        self.assertEqual((cal["dias_uteis_mes"], cal["dia_util_hoje"], cal["dias_uteis_fechados"]), (21, 15, 14))
        self.assertEqual(cal["ritmo_esperado_pct"], 67)
        self.assertFalse(self.api["v1/index.json"]["mes_referencia"]["fechamento"])

    def test_rota_111_sucos(self):
        b = self.api["v1/rotas/111.json"]["produtos"]["sucos"]
        self.assertEqual(b["meta"], 100.0)
        self.assertEqual(b["realizado"], 70.0)            # 50 + 20; a NF cancelada fica fora
        self.assertEqual(b["tendencia"], 100.0)           # 70 + 30 restante da META_NEG (direto)
        self.assertEqual(b["tendencia_pct"], 100)
        self.assertEqual(b["atingimento_pct"], 70)
        self.assertEqual(b["meta_dia"], 4.0)
        self.assertEqual(b["online_hoje"], 3.0)           # pedido cancelado fora
        self.assertEqual(b["status"], "no_ritmo")

    def test_rota_112_sem_curva(self):
        b = self.api["v1/rotas/112.json"]["produtos"]["sucos"]
        self.assertEqual((b["meta"], b["realizado"]), (40.0, 15.0))
        self.assertEqual(b["tendencia"], round(15 + 40 * 7 / 21, 1))   # restante por dias úteis
        self.assertEqual(b["status"], "abaixo_do_ritmo")

    def test_powerade_sem_venda(self):
        b = self.api["v1/rotas/111.json"]["produtos"]["powerade"]
        self.assertEqual((b["meta"], b["realizado"], b["atingimento_pct"]), (50.0, 0.0, 0))

    def test_produto_sem_meta(self):
        self.assertEqual(self.api["v1/rotas/111.json"]["produtos"]["sabores"]["status"], "sem_meta")

    def test_clientes(self):
        cli = {c["pv"]: c for c in self.api["v1/rotas/111.json"]["clientes"]}
        self.assertEqual(set(cli), {1, 2})
        c1, c2 = cli[1]["produtos"]["sucos"], cli[2]["produtos"]["sucos"]
        self.assertEqual((c1["meta"], c1["realizado"], c1["atingimento_pct"], c1["online_hoje"]), (60.0, 50.0, 83, 3.0))
        self.assertEqual(c1["status"], "no_ritmo")        # 83% >= 67%
        self.assertEqual((c2["meta"], c2["realizado"], c2["status"]), (40.0, 20.0, "abaixo_do_ritmo"))
        self.assertEqual(cli[1]["nome"], "CLIENTE 1")

    def test_supervisao_com_espaco_no_codigo(self):
        rota = self.api["v1/rotas/112.json"]["rota"]
        self.assertEqual((rota["supervisao"], rota["gerencia"]), ("SV.G1.2", "G1"))

    def test_gerencia_soma_rotas_e_eventuais(self):
        g = self.api["v1/gerencias/G1.json"]
        b = g["produtos"]["sucos"]
        self.assertEqual(b["meta"], 140.0)                # 100 + 40 (+ 0 da rota eventual)
        self.assertEqual(b["realizado"], 90.0)            # 70 + 15 + 5 do cliente em EV5
        tipos = {r["id"]: r["tipo"] for r in g["rotas"]}
        self.assertEqual(tipos, {"111": "normal", "112": "normal", "G1-EV": "eventual"})
        sv1 = next(s for s in g["supervisoes"] if s["id"] == "SV.G1.1")
        self.assertEqual(sv1["produtos"]["sucos"]["realizado"], 70.0)

    def test_empresa_igual_soma_das_gerencias(self):
        r = self.api["v1/resumo.json"]
        for k in M.IDS_PRODUTOS:
            soma = sum(g["produtos"][k]["realizado"] or 0 for g in r["gerencias"])
            self.assertAlmostEqual(r["empresa"]["produtos"][k]["realizado"] or 0, soma, places=1)

    def test_busca_sem_cliente_de_rota_eventual(self):
        self.assertEqual([c[0] for c in self.api["v1/busca.json"]["clientes"]], [1, 2, 3])

    def test_validacao_passa_com_aviso_dos_produtos_sem_meta(self):
        erros, avisos = validacao.validar(self.api)
        self.assertEqual(erros, [])
        self.assertTrue(any("Vol. Sabores" in a for a in avisos))

    def test_consultas_so_com_agrupadores_da_api(self):
        cons = cenario()
        fontes.carregar(cons, AGORA)
        for objeto, _, filtro in cons.chamadas:
            if objeto == M.OBJ_META and filtro:
                self.assertNotIn("Cervejas", filtro)


class TestFechamento(unittest.TestCase):
    def test_primeiro_dia_util_mostra_mes_anterior(self):
        cons = cenario()
        cons.dados[M.OBJ_CALENDARIO] = [
            {"DATA": "2026-09-30", "NO_DIAS_UTEIS_MES": 22, "NO_DIA_UTIL": 22, "NO_DIAS_UTEIS_RESTANTES": 0},
            {"DATA": "2026-10-01", "NO_DIAS_UTEIS_MES": 21, "NO_DIA_UTIL": 1, "NO_DIAS_UTEIS_RESTANTES": 21}]
        for l in cons.dados[M.OBJ_META]:   # dados de setembro
            l["ANOMES_REF"] = "202609"
            if l.get("ANOMES_REF_Chave_Meta_SAP"):
                l["ANOMES_REF_Chave_Meta_SAP"] = "202609"
        a = api.montar(fontes.carregar(cons, datetime(2026, 10, 1, 9, 0)))
        idx = a["v1/index.json"]
        self.assertEqual(idx["mes_referencia"], {"anomes": "202609", "rotulo": "Setembro/26", "fechamento": True})
        b = a["v1/rotas/111.json"]["produtos"]["sucos"]
        self.assertEqual((b["realizado"], b["tendencia"], b["meta_dia"], b["online_hoje"]), (70.0, None, None, None))
        self.assertEqual(b["status"], "abaixo_do_ritmo")   # 70% realizado no mês fechado


if __name__ == "__main__":
    unittest.main()
