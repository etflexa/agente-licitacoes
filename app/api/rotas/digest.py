"""Rota de digest: gera o resumo de aberturas e, se pedido, envia por e-mail."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.dependencias import AgenteDigestDep
from app.schemas.conversa import DigestRequest, DigestResponse

rotas = APIRouter(prefix="/api", tags=["digest"])


@rotas.post(
    "/digest",
    response_model=DigestResponse,
    summary="Gera (e opcionalmente envia) o digest de aberturas",
)
async def digest(requisicao: DigestRequest, agente: AgenteDigestDep) -> DigestResponse:
    """Com `enviar=false` (padrão) devolve o HTML do digest sem enviar nada.

    Com `enviar=true`, o conteúdo é entregue à API do monitor (Node), que é quem
    possui as credenciais SMTP e o layout dos e-mails.
    """
    if requisicao.enviar:
        return await agente.gerar_e_enviar(requisicao)

    return await agente.gerar(requisicao)
