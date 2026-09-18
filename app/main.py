"""Aplicação FastAPI do agente de licitações.

    uvicorn app.main:app --reload
    # ou
    agente-licitacoes servir

Documentação interativa em http://127.0.0.1:8000/docs.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app import __version__
from app.agentes.digest_agent import AgenteDigest
from app.agentes.qa_agent import AgenteQA
from app.api.rotas import chat, digest, health, licitacoes
from app.clients.monitor_client import MonitorClient
from app.core.config import Settings, obter_settings
from app.core.erros import AgenteError, ConfiguracaoError, LLMError, MonitorApiError
from app.core.logging import configurar_logging, obter_logger
from app.llm.factory import criar_provedor
from app.services.licitacoes_service import LicitacoesService

logger = obter_logger(__name__)

DESCRICAO = """
Agente de IA que responde perguntas sobre as licitações monitoradas do SENAC/AP.

Ele **não acessa o banco nem os arquivos do monitor**: consome a API HTTP do
projeto Node (`monitor-licitacoes-IA`), que segue como dona dos dados e das
regras de negócio. O envio de e-mail também é delegado ao Node.
"""


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Cria as dependências caras uma única vez, no start do servidor."""
    settings: Settings = obter_settings()
    configurar_logging(settings.log_level)

    cliente = MonitorClient(settings)
    servico = LicitacoesService(cliente, settings)
    provedor = criar_provedor(settings=settings)

    app.state.settings = settings
    app.state.monitor_client = cliente
    app.state.servico_licitacoes = servico
    app.state.provedor_llm = provedor
    app.state.agente_qa = AgenteQA(servico, provedor, settings=settings)
    app.state.agente_digest = AgenteDigest(servico, provedor, settings=settings)

    logger.info(
        "Agente iniciado | monitor=%s | llm=%s (%s)",
        settings.monitor_api_url,
        provedor.nome,
        provedor.modelo,
    )

    yield

    await provedor.fechar()
    await cliente.fechar()
    logger.info("Agente encerrado.")


def criar_app() -> FastAPI:
    """Monta a aplicação (separado do módulo para facilitar testes)."""
    app = FastAPI(
        title="Agente de Licitações SENAC/AP",
        description=DESCRICAO,
        version=__version__,
        lifespan=lifespan,
    )

    app.include_router(health.rotas)
    app.include_router(chat.rotas)
    app.include_router(digest.rotas)
    app.include_router(licitacoes.rotas)

    @app.exception_handler(MonitorApiError)
    async def _tratar_monitor(_req: Request, erro: MonitorApiError) -> JSONResponse:
        """Traduz a falha do monitor para o status mais informativo ao chamador."""
        if erro.status_code == status.HTTP_404_NOT_FOUND:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"erro": "nao_encontrado", "mensagem": erro.mensagem},
            )

        if erro.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_503_SERVICE_UNAVAILABLE):
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={"erro": "monitor_sem_credencial", "mensagem": erro.mensagem},
            )

        codigo = (
            status.HTTP_504_GATEWAY_TIMEOUT
            if "Tempo esgotado" in erro.mensagem
            else status.HTTP_502_BAD_GATEWAY
        )
        return JSONResponse(
            status_code=codigo,
            content={"erro": "monitor_indisponivel", "mensagem": erro.mensagem},
        )

    @app.exception_handler(LLMError)
    async def _tratar_llm(_req: Request, erro: LLMError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content={
                "erro": "llm_indisponivel",
                "mensagem": erro.mensagem,
                "provedor": erro.provedor,
            },
        )

    @app.exception_handler(ConfiguracaoError)
    async def _tratar_configuracao(_req: Request, erro: ConfiguracaoError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"erro": "configuracao_invalida", "mensagem": str(erro)},
        )

    @app.exception_handler(AgenteError)
    async def _tratar_agente(_req: Request, erro: AgenteError) -> JSONResponse:
        logger.exception("Erro no agente")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"erro": "erro_agente", "mensagem": str(erro)},
        )

    return app


app = criar_app()


def main() -> None:
    """Sobe o servidor com uvicorn, usando as configurações do .env."""
    import uvicorn

    settings = obter_settings()
    configurar_logging(settings.log_level)

    uvicorn.run(
        "app.main:app",
        host=settings.agente_host,
        port=settings.agente_port,
        reload=settings.ambiente == "desenvolvimento",
    )


if __name__ == "__main__":
    main()
