"""Contrato da camada de LLM.

O agente depende **apenas** desta interface. Trocar de provedor (OpenAI,
Gemini, DeepSeek, Ollama...) significa escrever uma classe nova e registrá-la na
fábrica — nenhum agente, rota ou teste precisa mudar.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.core.config import Settings, obter_settings
from app.schemas.conversa import TokensUso


class Papel(StrEnum):
    """Papel da mensagem no formato de chat."""

    SISTEMA = "system"
    USUARIO = "user"
    ASSISTENTE = "assistant"


class Mensagem(BaseModel):
    """Uma mensagem do histórico enviado ao modelo."""

    model_config = ConfigDict(use_enum_values=True)

    papel: Papel
    conteudo: str

    @classmethod
    def sistema(cls, conteudo: str) -> Mensagem:
        return cls(papel=Papel.SISTEMA, conteudo=conteudo)

    @classmethod
    def usuario(cls, conteudo: str) -> Mensagem:
        return cls(papel=Papel.USUARIO, conteudo=conteudo)

    @classmethod
    def assistente(cls, conteudo: str) -> Mensagem:
        return cls(papel=Papel.ASSISTENTE, conteudo=conteudo)


class RespostaLLM(BaseModel):
    """Resultado de uma chamada ao modelo, com metadados de consumo."""

    texto: str
    provedor: str
    modelo: str
    tokens: TokensUso | None = None
    latencia_ms: int | None = Field(default=None, description="Duração da chamada, em milissegundos")


class ProvedorLLM(ABC):
    """Interface que todo provedor de LLM precisa implementar."""

    nome: str = "base"

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or obter_settings()

    @property
    def modelo(self) -> str:
        """Identificador do modelo em uso."""
        return self._settings.llm_modelo

    @abstractmethod
    async def gerar(
        self,
        mensagens: list[Mensagem],
        temperatura: float | None = None,
        max_tokens: int | None = None,
    ) -> RespostaLLM:
        """Gera uma resposta a partir da lista de mensagens."""

    async def gerar_texto(
        self,
        mensagens: list[Mensagem],
        temperatura: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """Atalho que devolve apenas o texto — usado pelos agentes."""
        resposta = await self.gerar(mensagens, temperatura=temperatura, max_tokens=max_tokens)
        return resposta.texto

    async def verificar_saude(self) -> bool:
        """Confirma que o provedor está configurado e alcançável."""
        return True

    async def fechar(self) -> None:
        """Libera recursos (conexões HTTP)."""
