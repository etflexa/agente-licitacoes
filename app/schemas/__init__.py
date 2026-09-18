"""Modelos de dados (contratos da API do monitor e da API do agente)."""

from app.schemas.conversa import (
    DigestRequest,
    DigestResponse,
    PerguntaChat,
    ReferenciaLicitacao,
    RespostaChat,
)
from app.schemas.licitacao import (
    Documento,
    FiltrosLicitacao,
    Licitacao,
    LicitacaoResumo,
    ProximasAberturas,
    RespostaListaLicitacoes,
    ResumoLicitacoes,
    StatusMonitor,
)

__all__ = [
    "DigestRequest",
    "DigestResponse",
    "Documento",
    "FiltrosLicitacao",
    "Licitacao",
    "LicitacaoResumo",
    "PerguntaChat",
    "ProximasAberturas",
    "ReferenciaLicitacao",
    "RespostaChat",
    "RespostaListaLicitacoes",
    "ResumoLicitacoes",
    "StatusMonitor",
]
