"""Serviço de licitações: cache local sobre a API do monitor.

Sem cache, cada pergunta em linguagem natural baixaria a base inteira (427 KB)
do Node, e o mesmo valeria para cada geração de digest. Com TTL curto, perguntas
em sequência reaproveitam a mesma leitura, e um `asyncio.Lock` evita que várias
requisições simultâneas disparem buscas duplicadas.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from app.clients.monitor_client import MonitorClient
from app.core.config import Settings, obter_settings
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

T = TypeVar("T")


@dataclass
class _EntradaCache(Generic[T]):
    """Valor em cache com o instante (monotônico) em que expira."""

    valor: T
    expira_em: float


class LicitacoesService:
    """Fachada de leitura das licitações, com cache de curta duração."""

    def __init__(self, cliente: MonitorClient, settings: Settings | None = None) -> None:
        self._cliente = cliente
        self._settings = settings or obter_settings()
        self._ttl = self._settings.monitor_cache_ttl_segundos
        self._cache: dict[str, _EntradaCache[Any]] = {}
        self._lock = asyncio.Lock()


    def invalidar_cache(self) -> None:
        """Descarta o cache (usado pelo endpoint de administração e nos testes)."""
        self._cache.clear()

    def _ler_cache(self, chave: str) -> Any | None:
        entrada = self._cache.get(chave)

        if entrada is None:
            return None

        if entrada.expira_em < asyncio.get_running_loop().time():
            self._cache.pop(chave, None)
            return None

        return entrada.valor

    def _gravar_cache(self, chave: str, valor: Any) -> None:
        if self._ttl <= 0:
            return

        expira_em = asyncio.get_running_loop().time() + self._ttl
        self._cache[chave] = _EntradaCache(valor=valor, expira_em=expira_em)

    async def _com_cache(self, chave: str, fabrica: Any, forcar: bool = False) -> Any:
        """Devolve o valor do cache ou o produz uma única vez por vez."""
        if not forcar:
            valor = self._ler_cache(chave)
            if valor is not None:
                logger.debug("Cache hit: %s", chave)
                return valor

        async with self._lock:
            if not forcar:
                valor = self._ler_cache(chave)
                if valor is not None:
                    return valor

            valor = await fabrica()
            self._gravar_cache(chave, valor)
            return valor


    async def todas(self, forcar: bool = False) -> list[LicitacaoResumo]:
        """Todas as licitações do store, para montar o contexto do LLM."""
        return await self._com_cache(
            "licitacoes:todas",
            lambda: self._cliente.listar_todas(limite_maximo=500),
            forcar=forcar,
        )

    async def resumo(self, forcar: bool = False) -> ResumoLicitacoes:
        """Agregados por modalidade/situação e estado da última varredura."""
        return await self._com_cache("licitacoes:resumo", self._cliente.resumo, forcar=forcar)

    async def buscar(self, filtros: FiltrosLicitacao) -> RespostaListaLicitacoes:
        """Listagem filtrada — sempre vai à API, pois os filtros são variados."""
        return await self._cliente.listar_licitacoes(filtros)

    async def obter(self, licitacao_id: str) -> Licitacao:
        """Registro completo de uma licitação."""
        return await self._cliente.obter_licitacao(licitacao_id)

    async def proximas_aberturas(self, dias: int | None = None) -> ProximasAberturas:
        """Aberturas na janela de N dias (padrão vindo da configuração)."""
        janela = dias or self._settings.digest_dias_padrao
        return await self._com_cache(
            f"licitacoes:proximas:{janela}",
            lambda: self._cliente.proximas_aberturas(janela),
        )


    async def enviar_digest(
        self,
        titulo: str,
        html: str,
        texto: str | None = None,
        destinatarios: list[str] | None = None,
    ) -> dict[str, Any]:
        """Pede ao Node que envie o digest por e-mail."""
        return await self._cliente.enviar_digest(
            titulo=titulo, html=html, texto=texto, destinatarios=destinatarios
        )
