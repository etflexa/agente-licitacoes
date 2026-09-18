"""Cliente HTTP da API do monitor (projeto Node `monitor-licitacoes-IA`).

Este é o único ponto do agente que fala com o Node. Nenhuma regra de negócio é
duplicada aqui: filtros, estatísticas e janelas de data são resolvidos pelo
backend que já é dono dos dados.

O cliente devolve **modelos Pydantic**, não dicionários, para que qualquer
mudança de contrato apareça como erro explícito de validação em vez de um
`KeyError` no meio do prompt do LLM.
"""

from __future__ import annotations

from typing import Any, Self

import httpx

from app.core.config import Settings, obter_settings
from app.core.erros import ConfiguracaoError, MonitorApiError
from app.core.logging import obter_logger
from app.schemas.licitacao import (
    FiltrosLicitacao,
    Licitacao,
    LicitacaoResumo,
    ProximasAberturas,
    RespostaListaLicitacoes,
    ResumoLicitacoes,
)

logger = obter_logger(__name__)


class MonitorClient:
    """Cliente assíncrono da API do monitor."""

    def __init__(self, settings: Settings | None = None, cliente: httpx.AsyncClient | None = None) -> None:
        self._settings = settings or obter_settings()
        self._url_base = self._settings.monitor_api_url
        self._token = self._settings.token_monitor

        self._cliente = cliente or httpx.AsyncClient(
            base_url=self._url_base,
            timeout=self._settings.monitor_timeout_segundos,
        )
        self._cliente_proprio = cliente is None


    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_erro: object) -> None:
        await self.fechar()

    async def fechar(self) -> None:
        """Fecha o cliente HTTP, se ele foi criado por esta instância."""
        if self._cliente_proprio:
            await self._cliente.aclose()

    @property
    def escrita_habilitada(self) -> bool:
        """Indica se há token configurado (necessário para enviar digest)."""
        return bool(self._token)


    async def listar_licitacoes(self, filtros: FiltrosLicitacao | None = None) -> RespostaListaLicitacoes:
        """GET /api/licitacoes — lista paginada com filtros."""
        filtros = filtros or FiltrosLicitacao(limit=500)
        dados = await self._requisitar("GET", "/api/licitacoes", params=filtros.para_query())
        return RespostaListaLicitacoes.model_validate(dados)

    async def listar_todas(self, limite_maximo: int = 500) -> list[LicitacaoResumo]:
        """Baixa a base inteira (usado para montar o contexto do LLM)."""
        resposta = await self.listar_licitacoes(FiltrosLicitacao(limit=limite_maximo))

        if resposta.total > len(resposta.itens):
            logger.warning(
                "A base tem %s licitações e apenas %s foram carregadas (limite=%s).",
                resposta.total,
                len(resposta.itens),
                limite_maximo,
            )

        return resposta.itens

    async def obter_licitacao(self, licitacao_id: str) -> Licitacao:
        """GET /api/licitacoes/:id — registro completo, com documentos."""
        dados = await self._requisitar("GET", f"/api/licitacoes/{licitacao_id}")
        return Licitacao.model_validate(dados)

    async def resumo(self) -> ResumoLicitacoes:
        """GET /api/licitacoes/resumo — agregados e estado do monitor."""
        dados = await self._requisitar("GET", "/api/licitacoes/resumo")
        return ResumoLicitacoes.model_validate(dados)

    async def proximas_aberturas(self, dias: int = 7) -> ProximasAberturas:
        """GET /api/licitacoes/proximas-aberturas — abertura em até N dias."""
        dados = await self._requisitar(
            "GET", "/api/licitacoes/proximas-aberturas", params={"dias": dias}
        )
        return ProximasAberturas.model_validate(dados)

    async def enviar_digest(
        self,
        titulo: str,
        html: str,
        texto: str | None = None,
        destinatarios: list[str] | None = None,
    ) -> dict[str, Any]:
        """POST /api/notificacoes/digest — o Node envia o e-mail.

        As credenciais SMTP e o layout dos e-mails continuam pertencendo ao
        projeto Node: o agente só entrega o conteúdo pronto.
        """
        if not self._token:
            raise ConfiguracaoError(
                "MONITOR_API_TOKEN não configurado — não é possível enviar o digest. "
                "Defina o mesmo token usado no .env do projeto Node."
            )

        corpo: dict[str, Any] = {"titulo": titulo, "html": html}
        if texto:
            corpo["texto"] = texto
        if destinatarios:
            corpo["destinatarios"] = destinatarios

        return await self._requisitar("POST", "/api/notificacoes/digest", json=corpo)

    async def verificar_saude(self) -> dict[str, Any]:
        """GET /health do monitor, para o endpoint de saúde do agente."""
        return await self._requisitar("GET", "/health")


    async def _requisitar(self, metodo: str, caminho: str, **kwargs: Any) -> dict[str, Any]:
        """Executa a requisição traduzindo falhas em `MonitorApiError`.

        O token vai em todas as requisições quando configurado: os endpoints de
        leitura não o exigem, mas enviam o cabeçalho não custa nada e permite
        fechar as leituras no Node sem alterar o agente.
        """
        cabecalhos = dict(kwargs.pop("headers", {}) or {})

        if self._token:
            cabecalhos.setdefault("x-api-token", self._token)

        try:
            resposta = await self._cliente.request(metodo, caminho, headers=cabecalhos, **kwargs)
        except httpx.TimeoutException as erro:
            raise MonitorApiError(
                f"Tempo esgotado ao chamar o monitor em {self._url_base}{caminho}. "
                "O servidor Node está rodando (npm run api)?"
            ) from erro
        except httpx.HTTPError as erro:
            raise MonitorApiError(
                f"Falha de conexão com o monitor em {self._url_base}{caminho}: {erro}"
            ) from erro

        if resposta.status_code >= 400:
            raise MonitorApiError(
                self._mensagem_de_erro(resposta),
                status_code=resposta.status_code,
            )

        try:
            return resposta.json()
        except ValueError as erro:
            raise MonitorApiError(
                f"Resposta não-JSON do monitor em {caminho} (status {resposta.status_code})."
            ) from erro

    @staticmethod
    def _mensagem_de_erro(resposta: httpx.Response) -> str:
        """Extrai a mensagem de erro do padrão JSON usado pela API do Node."""
        try:
            corpo = resposta.json()
        except ValueError:
            return f"Monitor respondeu {resposta.status_code}: {resposta.text[:200]}"

        mensagem = corpo.get("mensagem") or corpo.get("erro") or resposta.text[:200]
        return f"Monitor respondeu {resposta.status_code}: {mensagem}"
