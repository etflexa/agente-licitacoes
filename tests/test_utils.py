"""Testes dos utilitários de data e texto.

São funções puras, mas concentram as regras que mais aparecem nos dados reais
(ISO com 'Z', formato brasileiro, valores ausentes), então valem teste direto.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.utils.datas import (
    dias_entre,
    formatar_data_br,
    formatar_data_iso,
    para_datetime,
)
from app.utils.texto import escapar_html, limpar_html_llm, normalizar_texto, truncar


class TestDatas:
    @pytest.mark.parametrize(
        "entrada",
        [
            "2026-08-17T09:00:00Z",
            "2026-08-17T09:00:00+00:00",
            "17/08/2026 09:00",
        ],
    )
    def test_formatar_aceita_formatos_mistos(self, entrada: str) -> None:
        assert formatar_data_br(entrada) == "17/08/2026 às 09:00"

    def test_formatar_sem_hora(self) -> None:
        assert formatar_data_br("2026-08-17T09:00:00Z", com_hora=False) == "17/08/2026"

    def test_formatar_iso_para_filtros(self) -> None:
        assert formatar_data_iso("17/08/2026 09:00") == "2026-08-17T09:00:00+00:00"

    @pytest.mark.parametrize("entrada", [None, "", "data inválida", "32/13/2026"])
    def test_formatar_valores_invalidos_nao_quebram(self, entrada: object) -> None:
        assert formatar_data_br(entrada) == "N/A"

    def test_datetime_ingenuo_recebe_utc(self) -> None:
        convertido = para_datetime(datetime.fromisoformat("2026-08-17T09:00:00"))

        assert convertido is not None
        assert convertido.tzinfo == UTC

    def test_dias_entre(self) -> None:
        assert dias_entre("2026-09-18T00:00:00Z", "2026-09-25T00:00:00Z") == 7
        assert dias_entre("2026-09-18T00:00:00Z", None) is None


class TestTexto:
    @pytest.mark.parametrize(
        ("entrada", "esperado"),
        [
            ("Pregão eletrônico", "pregao eletronico"),
            ("  OBRA   de Engenharia ", "obra de engenharia"),
            (None, ""),
        ],
    )
    def test_normalizar_texto(self, entrada: object, esperado: str) -> None:
        assert normalizar_texto(entrada) == esperado

    def test_truncar_respeita_palavras(self) -> None:
        original = "Contratação de serviços de engenharia para obras"
        resultado = truncar(original, 30)

        assert resultado.endswith("...")

        corpo = resultado[: -len("...")]
        assert corpo in original
        assert len(corpo) <= 30

    def test_truncar_texto_curto_nao_altera(self) -> None:
        assert truncar("Obras", 30) == "Obras"

    def test_escapar_html_neutraliza_marcacao(self) -> None:
        assert escapar_html("<script>alert('x')</script>") == (
            "&lt;script&gt;alert(&#x27;x&#x27;)&lt;/script&gt;"
        )

    def test_limpar_html_llm_remove_tags_perigosas(self) -> None:
        sujo = "<p>Resumo</p><script>roubar()</script><style>body{}</style>"

        limpo = limpar_html_llm(sujo)

        assert "<script>" not in limpo
        assert "<style>" not in limpo
        assert "<p>Resumo</p>" in limpo
