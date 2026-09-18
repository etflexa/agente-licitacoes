"""Testes da API HTTP do agente.

Usam `TestClient` com `dependency_overrides`: as rotas são exercitadas de ponta a
ponta (validação, serialização, tratamento de erro) sem subir servidor e sem
tocar a rede.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.agentes.digest_agent import AgenteDigest
from app.agentes.qa_agent import AgenteQA
from app.api import dependencias
from app.main import criar_app


@pytest.fixture
def api(cliente, servico, provedor_fake, settings) -> Iterator[TestClient]:
    """Cliente HTTP do agente com todas as dependências substituídas."""
    app = criar_app()

    app.dependency_overrides[dependencias.obter_settings] = lambda: settings
    app.dependency_overrides[dependencias.obter_cliente_monitor] = lambda: cliente
    app.dependency_overrides[dependencias.obter_servico_licitacoes] = lambda: servico
    app.dependency_overrides[dependencias.obter_provedor_llm] = lambda: provedor_fake
    app.dependency_overrides[dependencias.obter_agente_qa] = lambda: AgenteQA(
        servico, provedor_fake, settings=settings
    )
    app.dependency_overrides[dependencias.obter_agente_digest] = lambda: AgenteDigest(
        servico, provedor_fake, settings=settings
    )

    with TestClient(app) as cliente_teste:
        yield cliente_teste

    app.dependency_overrides.clear()


class TestHealth:
    def test_health_reporta_llm_e_monitor(self, api: TestClient) -> None:
        resposta = api.get("/health")

        assert resposta.status_code == 200

        corpo = resposta.json()

        assert corpo["status"] == "ok"
        assert corpo["llm"]["provedor"] == "fake"
        assert corpo["monitor"]["totalRegistros"] == 4

    def test_health_degrada_quando_monitor_falha(
        self, api: TestClient, monitor_simulado
    ) -> None:
        monitor_simulado.falha_forcada = 500

        corpo = api.get("/health").json()

        assert corpo["status"] == "degradado"
        assert corpo["monitor"]["status"] == "indisponivel"


class TestLicitacoes:
    def test_listar(self, api: TestClient) -> None:
        corpo = api.get("/api/licitacoes").json()

        assert corpo["total"] == 4
        assert corpo["totalGeral"] == 4
        assert len(corpo["itens"]) == 4

    def test_listar_com_filtro_de_modalidade(self, api: TestClient) -> None:
        corpo = api.get("/api/licitacoes", params={"modalidade": "Pregão eletrônico"}).json()

        assert corpo["total"] == 1
        assert corpo["itens"][0]["numeroProcesso"] == "12/2026"

    def test_resposta_usa_camel_case(self, api: TestClient) -> None:
        """O agente fala o mesmo dialeto da API do Node."""
        item = api.get("/api/licitacoes").json()["itens"][0]

        assert "numeroProcesso" in item
        assert "dataAbertura" in item
        assert "totalDocumentos" in item

    def test_filtro_invalido_retorna_422(self, api: TestClient) -> None:
        assert api.get("/api/licitacoes", params={"limit": 0}).status_code == 422
        assert api.get("/api/licitacoes", params={"ordenar": "invalido"}).status_code == 422

    def test_resumo(self, api: TestClient) -> None:
        corpo = api.get("/api/licitacoes/resumo").json()

        assert corpo["total"] == 4
        assert corpo["porModalidade"]["Pregão eletrônico"] == 1
        assert corpo["statusMonitor"]["alteradas"] == 1

    def test_proximas_aberturas(self, api: TestClient) -> None:
        corpo = api.get("/api/licitacoes/proximas-aberturas", params={"dias": 30}).json()

        assert corpo["total"] == 3
        assert corpo["janelaDias"] == 30

    def test_detalhe(self, api: TestClient) -> None:
        corpo = api.get("/api/licitacoes/11111111-1111-1111-1111-111111111111").json()

        assert corpo["numeroProcesso"] == "12/2026"
        assert corpo["documentos"][0]["nome"] == "Edital 1"

    def test_detalhe_inexistente_retorna_404(self, api: TestClient) -> None:
        resposta = api.get("/api/licitacoes/00000000-0000-0000-0000-000000000000")

        assert resposta.status_code == 404
        assert resposta.json()["erro"] == "nao_encontrado"

    def test_monitor_fora_do_ar_retorna_502(self, api: TestClient, monitor_simulado) -> None:
        monitor_simulado.falha_forcada = 500

        resposta = api.get("/api/licitacoes")

        assert resposta.status_code == 502
        assert resposta.json()["erro"] == "monitor_indisponivel"

    def test_invalidar_cache(self, api: TestClient) -> None:
        assert api.post("/api/licitacoes/cache/invalidar").json()["status"] == "cache_invalidado"


class TestChat:
    def test_pergunta_em_linguagem_natural(self, api: TestClient) -> None:
        resposta = api.post("/api/chat", json={"pergunta": "quais processos tratam de engenharia?"})

        assert resposta.status_code == 200

        corpo = resposta.json()

        assert corpo["resposta"].strip()
        assert corpo["provedor"] == "fake"
        assert corpo["aviso"]
        assert corpo["licitacoesNoContexto"] == 4

    def test_pergunta_curta_retorna_422(self, api: TestClient) -> None:
        assert api.post("/api/chat", json={"pergunta": "?"}).status_code == 422

    def test_campo_ausente_retorna_422(self, api: TestClient) -> None:
        assert api.post("/api/chat", json={}).status_code == 422

    def test_referencias_aparecem_quando_o_processo_e_citado(self, api: TestClient) -> None:
        corpo = api.post(
            "/api/chat",
            json={"pergunta": "o que diz o processo 12/2026 de equipamentos?"},
        ).json()

        assert any(referencia["numeroProcesso"] == "12/2026" for referencia in corpo["referencias"])


class TestDigest:
    def test_preview_nao_envia(self, api: TestClient, monitor_simulado) -> None:
        corpo = api.post("/api/digest", json={"dias": 30}).json()

        assert corpo["enviado"] is False
        assert "<table>" in corpo["html"]
        assert corpo["totalLicitacoes"] == 3
        assert monitor_simulado.corpos_postados == []

    def test_envio_delega_para_o_node(self, api: TestClient, monitor_simulado) -> None:
        corpo = api.post("/api/digest", json={"dias": 30, "enviar": True}).json()

        assert corpo["enviado"] is True
        assert corpo["messageId"] == "<teste@senac>"
        assert len(monitor_simulado.corpos_postados) == 1

    def test_dias_invalido_retorna_422(self, api: TestClient) -> None:
        assert api.post("/api/digest", json={"dias": 0}).status_code == 422
        assert api.post("/api/digest", json={"dias": 999}).status_code == 422

    def test_token_ausente_no_monitor_retorna_503(
        self, provedor_fake, settings, monitor_simulado
    ) -> None:
        """Sem token configurado, o envio falha com 503 e mensagem clara."""
        import httpx

        from app.clients.monitor_client import MonitorClient
        from app.services.licitacoes_service import LicitacoesService

        sem_token = settings.model_copy(update={"monitor_api_token": None})
        http = httpx.AsyncClient(
            transport=httpx.MockTransport(monitor_simulado), base_url=settings.monitor_api_url
        )
        cliente_sem_token = MonitorClient(sem_token, cliente=http)
        servico_sem_token = LicitacoesService(cliente_sem_token, sem_token)

        app = criar_app()
        app.dependency_overrides[dependencias.obter_settings] = lambda: sem_token
        app.dependency_overrides[dependencias.obter_cliente_monitor] = lambda: cliente_sem_token
        app.dependency_overrides[dependencias.obter_servico_licitacoes] = lambda: servico_sem_token
        app.dependency_overrides[dependencias.obter_agente_digest] = lambda: AgenteDigest(
            servico_sem_token, provedor_fake, settings=sem_token
        )

        try:
            with TestClient(app) as cliente_teste:
                resposta = cliente_teste.post("/api/digest", json={"dias": 30, "enviar": True})
        finally:
            app.dependency_overrides.clear()

        assert resposta.status_code == 503
        assert "MONITOR_API_TOKEN" in resposta.json()["mensagem"]
        assert monitor_simulado.corpos_postados == []


class TestDocumentacao:
    def test_openapi_disponivel(self, api: TestClient) -> None:
        esquema = api.get("/openapi.json").json()

        assert "/api/chat" in esquema["paths"]
        assert "/api/digest" in esquema["paths"]
        assert "/api/licitacoes" in esquema["paths"]
