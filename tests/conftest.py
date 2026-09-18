"""Fixtures compartilhadas: API do monitor simulada e dependências de teste.

Nenhum teste toca a rede real: as chamadas ao monitor passam por um
`httpx.MockTransport` que devolve dados equivalentes aos da API verdadeira. Assim
a suíte roda offline, em milissegundos, e sem risco de disparar e-mail.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from app.clients.monitor_client import MonitorClient
from app.core.config import Settings
from app.llm.fake import ProvedorFake
from app.services.licitacoes_service import LicitacoesService

LICITACOES: list[dict[str, Any]] = [
    {
        "id": "11111111-1111-1111-1111-111111111111",
        "modalidade": "Pregão eletrônico",
        "numeroProcesso": "12/2026",
        "objeto": "Aquisição de equipamentos de informática para os laboratórios de ensino",
        "dataAbertura": "2026-10-05T09:00:00Z",
        "situacao": "Em processo",
        "criterioDeJulgamento": "1-Menor preço",
        "link": "https://www.gov.br/compras",
        "totalDocumentos": 3,
    },
    {
        "id": "22222222-2222-2222-2222-222222222222",
        "modalidade": "Pregão presencial",
        "numeroProcesso": "07/2026",
        "objeto": "Contratação de serviços de manutenção predial preventiva e corretiva",
        "dataAbertura": "2026-09-22T13:30:00Z",
        "situacao": "Em processo",
        "criterioDeJulgamento": None,
        "link": None,
        "totalDocumentos": 1,
    },
    {
        "id": "33333333-3333-3333-3333-333333333333",
        "modalidade": "Concorrência",
        "numeroProcesso": "02/2026",
        "objeto": "Obras de engenharia para adaptação de câmaras frigoríficas",
        "dataAbertura": "2026-08-17T09:00:00Z",
        "situacao": "Finalizada",
        "criterioDeJulgamento": "1-Menor preço",
        "link": None,
        "totalDocumentos": 7,
    },
    {
        "id": "44444444-4444-4444-4444-444444444444",
        "modalidade": "Leilão",
        "numeroProcesso": "02/2026",
        "objeto": "Alienação de veículo automotor Chevrolet S10",
        "dataAbertura": "2026-09-25T09:00:00Z",
        "situacao": "Em processo",
        "criterioDeJulgamento": None,
        "link": None,
        "totalDocumentos": 1,
    },
]

RESUMO: dict[str, Any] = {
    "total": len(LICITACOES),
    "comLink": 1,
    "totalDocumentos": 12,
    "legadoSemDetalhes": 0,
    "porModalidade": {"Pregão eletrônico": 1, "Pregão presencial": 1, "Concorrência": 1, "Leilão": 1},
    "porSituacao": {"Em processo": 3, "Finalizada": 1},
    "proximaAbertura": "2026-09-22T13:30:00Z",
    "statusMonitor": {
        "sucesso": True,
        "totalApi": 4,
        "novas": 0,
        "alteradas": 1,
        "duracaoSegundos": 1.25,
        "dataUltimaCargaApi": "2026-09-17T10:17:41.946Z",
        "atualizadoEm": "2026-09-18T06:00:00.000Z",
        "erro": None,
    },
}

DOCUMENTOS: list[dict[str, Any]] = [
    {
        "id": "doc-1",
        "nome": "Edital 1",
        "tipo": "Edital",
        "dataPublicacao": "2026-09-01T12:00:00-03:00",
        "arquivo": "EDITAL 12-2026.pdf",
        "tamanhoBytes": 926939,
        "ativo": True,
    }
]


def detalhe(licitacao: dict[str, Any]) -> dict[str, Any]:
    """Completa um item de lista com os campos exclusivos do detalhe."""
    return {
        **licitacao,
        "modalidadeId": "modalidade-1",
        "dataSituacao": None,
        "documentos": DOCUMENTOS,
        "legado": False,
        "primeiraVisualizacaoEm": "2026-09-18T06:13:02.757Z",
        "atualizadoEm": "2026-09-18T06:13:06.541Z",
    }


class MonitorSimulado:
    """Handler de `httpx.MockTransport` que imita a API do Node."""

    def __init__(self) -> None:
        self.requisicoes: list[httpx.Request] = []
        self.corpos_postados: list[dict[str, Any]] = []
        self.falha_forcada: int | None = None
        self.timeout_forcado = False

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requisicoes.append(request)

        if self.timeout_forcado:
            raise httpx.ReadTimeout("tempo esgotado", request=request)

        if self.falha_forcada is not None:
            return httpx.Response(
                self.falha_forcada,
                json={"erro": "erro_simulado", "mensagem": "falha simulada pelo teste"},
            )

        caminho = request.url.path

        if caminho == "/health":
            return httpx.Response(
                200,
                json={
                    "status": "ok",
                    "servico": "monitor-licitacoes-api",
                    "totalRegistros": len(LICITACOES),
                    "ultimaSincronizacao": "2026-09-18T06:00:00.000Z",
                    "escritaHabilitada": True,
                },
            )

        if caminho == "/api/licitacoes":
            return httpx.Response(200, json=self._listar(request))

        if caminho == "/api/licitacoes/resumo":
            return httpx.Response(200, json=RESUMO)

        if caminho == "/api/licitacoes/proximas-aberturas":
            return httpx.Response(200, json=self._janela(request))

        if caminho.startswith("/api/licitacoes/"):
            return self._detalhe(caminho.rsplit("/", 1)[-1])

        if caminho == "/api/notificacoes/digest":
            if request.headers.get("x-api-token") != "token-de-teste":
                return httpx.Response(401, json={"erro": "nao_autorizado", "mensagem": "token inválido"})

            self.corpos_postados.append(json.loads(request.content.decode()))
            return httpx.Response(202, json={"status": "enviado", "messageId": "<teste@senac>"})

        return httpx.Response(404, json={"erro": "rota_nao_encontrada", "mensagem": caminho})

    def _listar(self, request: httpx.Request) -> dict[str, Any]:
        """Aplica os filtros que o Node aplicaria, para o teste exercitar o repasse."""
        params = request.url.params
        itens = list(LICITACOES)

        modalidade = params.get("modalidade")
        if modalidade:
            itens = [i for i in itens if modalidade.lower() in (i["modalidade"] or "").lower()]

        situacao = params.get("situacao")
        if situacao:
            itens = [i for i in itens if situacao.lower() in (i["situacao"] or "").lower()]

        termo = params.get("q")
        if termo:
            itens = [i for i in itens if termo.lower() in (i["objeto"] or "").lower()]

        limite = int(params.get("limit") or 50)
        deslocamento = int(params.get("offset") or 0)

        return {
            "total": len(itens),
            "limit": limite,
            "offset": deslocamento,
            "totalGeral": len(LICITACOES),
            "itens": itens[deslocamento : deslocamento + limite],
        }

    def _janela(self, request: httpx.Request) -> dict[str, Any]:
        """Janela calculada a partir de uma data fixa (2026-09-18), para o teste ser determinístico."""
        dias = int(request.url.params.get("dias") or 7)
        inicio_dt = datetime(2026, 9, 18, tzinfo=UTC)
        fim_dt = inicio_dt + timedelta(days=dias)

        selecionadas = [
            licitacao
            for licitacao in LICITACOES
            if inicio_dt <= datetime.fromisoformat(licitacao["dataAbertura"]) <= fim_dt
        ]

        return {
            "janelaDias": dias,
            "de": inicio_dt.isoformat(),
            "ate": fim_dt.isoformat(),
            "total": len(selecionadas),
            "itens": selecionadas,
        }

    def _detalhe(self, licitacao_id: str) -> httpx.Response:
        encontrada = next((item for item in LICITACOES if item["id"] == licitacao_id), None)

        if encontrada is None:
            return httpx.Response(
                404, json={"erro": "nao_encontrado", "mensagem": f"Nenhuma licitação com id {licitacao_id}."}
            )

        return httpx.Response(200, json=detalhe(encontrada))


@pytest.fixture
def settings() -> Settings:
    """Configuração isolada: ignora o .env e usa o provedor determinístico."""
    return Settings(
        _env_file=None,
        ambiente="desenvolvimento",
        log_level="WARNING",
        monitor_api_url="http://monitor-teste",
        monitor_api_token="token-de-teste",
        monitor_cache_ttl_segundos=0,
        llm_provider="fake",
    )


@pytest.fixture
def monitor_simulado() -> MonitorSimulado:
    return MonitorSimulado()


@pytest.fixture
async def cliente(settings: Settings, monitor_simulado: MonitorSimulado) -> Any:
    """Cliente do monitor apontando para o transporte simulado."""
    transporte = httpx.MockTransport(monitor_simulado)
    http = httpx.AsyncClient(transport=transporte, base_url=settings.monitor_api_url)

    cliente = MonitorClient(settings, cliente=http)
    try:
        yield cliente
    finally:
        await http.aclose()


@pytest.fixture
def servico(cliente: MonitorClient, settings: Settings) -> LicitacoesService:
    return LicitacoesService(cliente, settings)


@pytest.fixture
def provedor_fake(settings: Settings) -> Iterator[ProvedorFake]:
    yield ProvedorFake(settings)
