"""Rotas de licitações: repasse tipado da API do monitor."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path, Query

from app.api.dependencias import ServicoLicitacoesDep
from app.schemas.licitacao import (
    FiltrosLicitacao,
    Licitacao,
    ProximasAberturas,
    RespostaListaLicitacoes,
    ResumoLicitacoes,
)

rotas = APIRouter(prefix="/api/licitacoes", tags=["licitações"])


@rotas.get("", response_model=RespostaListaLicitacoes, summary="Lista licitações com filtros")
async def listar(
    servico: ServicoLicitacoesDep,
    filtros: Annotated[FiltrosLicitacao, Query()],
) -> RespostaListaLicitacoes:
    """Mesmos filtros da API do monitor, mas validados e documentados aqui."""
    return await servico.buscar(filtros)


@rotas.get("/resumo", response_model=ResumoLicitacoes, summary="Agregados e estado do monitor")
async def resumo(servico: ServicoLicitacoesDep) -> ResumoLicitacoes:
    return await servico.resumo()


@rotas.get(
    "/proximas-aberturas",
    response_model=ProximasAberturas,
    summary="Aberturas previstas nos próximos N dias",
)
async def proximas_aberturas(
    servico: ServicoLicitacoesDep,
    dias: Annotated[int, Query(ge=1, le=365, description="Janela em dias")] = 7,
) -> ProximasAberturas:
    return await servico.proximas_aberturas(dias)


@rotas.post("/cache/invalidar", summary="Descarta o cache local do agente")
async def invalidar_cache(servico: ServicoLicitacoesDep) -> dict:
    """Útil após uma varredura do monitor, para a próxima pergunta ver dados novos."""
    servico.invalidar_cache()
    return {"status": "cache_invalidado"}


@rotas.get("/{licitacao_id}", response_model=Licitacao, summary="Detalhe completo de uma licitação")
async def detalhar(
    servico: ServicoLicitacoesDep,
    licitacao_id: Annotated[str, Path(description="UUID da licitação")],
) -> Licitacao:
    return await servico.obter(licitacao_id)
