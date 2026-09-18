"""Fábrica de provedores de LLM.

Ponto único de decisão: a configuração diz o nome do provedor e a fábrica
devolve a implementação. Adicionar Gemini, Anthropic ou um modelo local
diferente é registrar uma classe nova em `_PROVEDORES`.
"""

from __future__ import annotations

from collections.abc import Callable

from app.core.config import ProviderNome, Settings, obter_settings
from app.core.erros import ConfiguracaoError
from app.core.logging import obter_logger
from app.llm.base import ProvedorLLM
from app.llm.fake import ProvedorFake
from app.llm.openai_compativel import ProvedorOpenAICompativel

logger = obter_logger(__name__)

_PROVEDORES: dict[str, Callable[..., ProvedorLLM]] = {
    ProvedorFake.nome: ProvedorFake,
    ProvedorOpenAICompativel.nome: ProvedorOpenAICompativel,
}


def criar_provedor(nome: ProviderNome | str | None = None, settings: Settings | None = None) -> ProvedorLLM:
    """Instancia o provedor configurado.

    @param nome: sobrescreve `LLM_PROVIDER` (útil em testes).
    """
    settings = settings or obter_settings()
    escolhido = nome or settings.llm_provider

    fabrica = _PROVEDORES.get(str(escolhido))

    if fabrica is None:
        disponiveis = ", ".join(sorted(_PROVEDORES))
        raise ConfiguracaoError(f"LLM_PROVIDER desconhecido: {escolhido}. Opções: {disponiveis}.")

    provedor = fabrica(settings)

    if provedor.nome == ProvedorFake.nome:
        logger.warning(
            "LLM_PROVIDER=fake: o agente responde de forma determinística, sem IA. "
            "Configure um provedor real para respostas em linguagem natural."
        )
    else:
        logger.info("Provedor de LLM: %s | modelo: %s", provedor.nome, provedor.modelo)

    return provedor


def provedores_disponiveis() -> list[str]:
    """Lista os nomes de provedores registrados."""
    return sorted(_PROVEDORES)
