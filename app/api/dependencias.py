"""Dependências do FastAPI.

Os objetos caros (cliente HTTP, cache, provedor de LLM) são criados uma vez no
`lifespan` e guardados em `app.state`. As rotas os recebem por injeção, o que
mantém as funções testáveis e evita instanciar um provedor novo a cada request.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from app.agentes.digest_agent import AgenteDigest
from app.agentes.qa_agent import AgenteQA
from app.clients.monitor_client import MonitorClient
from app.core.config import Settings
from app.llm.base import ProvedorLLM
from app.services.licitacoes_service import LicitacoesService


def obter_settings(request: Request) -> Settings:
    return request.app.state.settings


def obter_cliente_monitor(request: Request) -> MonitorClient:
    return request.app.state.monitor_client


def obter_servico_licitacoes(request: Request) -> LicitacoesService:
    return request.app.state.servico_licitacoes


def obter_provedor_llm(request: Request) -> ProvedorLLM:
    return request.app.state.provedor_llm


def obter_agente_qa(request: Request) -> AgenteQA:
    return request.app.state.agente_qa


def obter_agente_digest(request: Request) -> AgenteDigest:
    return request.app.state.agente_digest


SettingsDep = Annotated[Settings, Depends(obter_settings)]
ClienteMonitorDep = Annotated[MonitorClient, Depends(obter_cliente_monitor)]
ServicoLicitacoesDep = Annotated[LicitacoesService, Depends(obter_servico_licitacoes)]
ProvedorDep = Annotated[ProvedorLLM, Depends(obter_provedor_llm)]
AgenteQADep = Annotated[AgenteQA, Depends(obter_agente_qa)]
AgenteDigestDep = Annotated[AgenteDigest, Depends(obter_agente_digest)]
