"""Rota de chat: pergunta em linguagem natural sobre as licitações."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.dependencias import AgenteQADep
from app.schemas.conversa import PerguntaChat, RespostaChat

rotas = APIRouter(prefix="/api", tags=["agente"])


@rotas.post(
    "/chat",
    response_model=RespostaChat,
    summary="Pergunta em linguagem natural sobre as licitações monitoradas",
)
async def chat(pergunta: PerguntaChat, agente: AgenteQADep) -> RespostaChat:
    """Ex.: `{"pergunta": "quais pregões eletrônicos abrem em outubro?"}`.

    Quando `incluirReferencias` é verdadeiro, a resposta traz os processos
    citados com seus dados, o que permite conferir o que o modelo afirmou.
    """
    return await agente.responder(pergunta)
