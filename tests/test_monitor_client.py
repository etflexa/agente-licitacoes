"""Testes do cliente HTTP do monitor.

O foco é a fronteira: garantir que erros do Node viram `MonitorApiError` com
mensagem útil, que a autenticação é exigida no envio de digest e que os payloads
são validados contra os modelos (falha de contrato não deve passar silenciosa).
"""

from __future__ import annotations

import pytest

from app.clients.monitor_client import MonitorClient
from app.core.erros import ConfiguracaoError, MonitorApiError
from app.schemas.licitacao import FiltrosLicitacao


class TestLeituras:
    async def test_listar_licitacoes(self, cliente: MonitorClient) -> None:
        resposta = await cliente.listar_licitacoes()

        assert resposta.total == 4
        assert resposta.itens[0].numero_processo in {"12/2026", "07/2026", "02/2026"}
        assert resposta.itens[0].data_abertura is not None

    async def test_listar_todas_devolve_base_completa(self, cliente: MonitorClient) -> None:
        licitacoes = await cliente.listar_todas()

        assert len(licitacoes) == 4
        assert {licitacao.modalidade for licitacao in licitacoes} == {
            "Pregão eletrônico",
            "Pregão presencial",
            "Concorrência",
            "Leilão",
        }

    async def test_filtros_sao_enviados_como_camel_case(
        self, cliente: MonitorClient, monitor_simulado
    ) -> None:
        await cliente.listar_licitacoes(
            FiltrosLicitacao(modalidade="Pregão eletrônico", somente_com_documentos=True, limit=10)
        )

        parametros = monitor_simulado.requisicoes[-1].url.params

        assert parametros.get("modalidade") == "Pregão eletrônico"
        assert parametros.get("somenteComDocumentos") == "true"
        assert parametros.get("limit") == "10"

    async def test_filtros_falsos_sao_omitidos(self, cliente: MonitorClient, monitor_simulado) -> None:
        await cliente.listar_licitacoes(FiltrosLicitacao(limit=5))

        parametros = monitor_simulado.requisicoes[-1].url.params

        assert "somenteComLink" not in parametros
        assert "somenteFuturas" not in parametros
        assert "q" not in parametros

    async def test_obter_detalhe_traz_documentos(self, cliente: MonitorClient) -> None:
        licitacao = await cliente.obter_licitacao("11111111-1111-1111-1111-111111111111")

        assert licitacao.numero_processo == "12/2026"
        assert len(licitacao.documentos) == 1
        assert licitacao.documentos[0].tamanho_legivel == "905 KB"

    async def test_resumo_traz_status_do_monitor(self, cliente: MonitorClient) -> None:
        resumo = await cliente.resumo()

        assert resumo.total == 4
        assert resumo.status_monitor is not None
        assert resumo.status_monitor.alteradas == 1

    async def test_proximas_aberturas(self, cliente: MonitorClient) -> None:
        janela = await cliente.proximas_aberturas(30)

        assert janela.janela_dias == 30
        assert janela.total == 3
        assert {item.numero_processo for item in janela.itens} == {"07/2026", "02/2026", "12/2026"}


class TestErros:
    async def test_404_do_monitor_vira_erro_de_dominio(
        self, cliente: MonitorClient, monitor_simulado
    ) -> None:
        monitor_simulado.falha_forcada = 404

        with pytest.raises(MonitorApiError) as capturado:
            await cliente.obter_licitacao("inexistente")

        assert capturado.value.status_code == 404
        assert "falha simulada pelo teste" in capturado.value.mensagem

    async def test_erro_500_e_propagado(self, cliente: MonitorClient, monitor_simulado) -> None:
        monitor_simulado.falha_forcada = 500

        with pytest.raises(MonitorApiError) as capturado:
            await cliente.resumo()

        assert capturado.value.status_code == 500

    async def test_timeout_tem_mensagem_orientadora(
        self, cliente: MonitorClient, monitor_simulado
    ) -> None:
        monitor_simulado.timeout_forcado = True

        with pytest.raises(MonitorApiError) as capturado:
            await cliente.listar_licitacoes()

        assert "Tempo esgotado" in capturado.value.mensagem
        assert "npm run api" in capturado.value.mensagem


class TestEscrita:
    async def test_digest_envia_com_token(self, cliente: MonitorClient, monitor_simulado) -> None:
        resultado = await cliente.enviar_digest(titulo="Digest", html="<p>ok</p>")

        assert resultado["status"] == "enviado"
        assert monitor_simulado.corpos_postados[0]["titulo"] == "Digest"
        assert monitor_simulado.requisicoes[-1].headers["x-api-token"] == "token-de-teste"

    async def test_digest_sem_token_configurado_falha_antes_da_rede(
        self, settings, monitor_simulado
    ) -> None:
        import httpx

        sem_token = settings.model_copy(update={"monitor_api_token": None})
        http = httpx.AsyncClient(
            transport=httpx.MockTransport(monitor_simulado), base_url=settings.monitor_api_url
        )

        try:
            cliente = MonitorClient(sem_token, cliente=http)

            with pytest.raises(ConfiguracaoError) as capturado:
                await cliente.enviar_digest(titulo="x", html="<p>x</p>")

            assert "MONITOR_API_TOKEN" in str(capturado.value)
            assert monitor_simulado.requisicoes == []
        finally:
            await http.aclose()

    async def test_token_invalido_no_monitor_e_reportado(self, settings, monitor_simulado) -> None:
        import httpx

        errado = settings.model_copy(update={"monitor_api_token": "token-errado"})
        http = httpx.AsyncClient(
            transport=httpx.MockTransport(monitor_simulado), base_url=settings.monitor_api_url
        )

        try:
            cliente = MonitorClient(errado, cliente=http)

            with pytest.raises(MonitorApiError) as capturado:
                await cliente.enviar_digest(titulo="x", html="<p>x</p>")

            assert capturado.value.status_code == 401
        finally:
            await http.aclose()


class TestSaude:
    async def test_health(self, cliente: MonitorClient) -> None:
        dados = await cliente.verificar_saude()

        assert dados["status"] == "ok"
        assert dados["totalRegistros"] == 4
