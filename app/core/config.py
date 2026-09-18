"""Configuração central do agente, carregada de variáveis de ambiente/.env.

Todo acesso a `os.environ` acontece aqui: o restante do código recebe um objeto
`Settings` já validado, o que torna os módulos testáveis (basta injetar outra
instância) e evita `os.getenv` espalhado pelo projeto.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ProviderNome = Literal["fake", "openai_compativel"]


class Settings(BaseSettings):
    """Configurações do agente."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    ambiente: Literal["desenvolvimento", "producao"] = "desenvolvimento"
    log_level: str = "INFO"

    monitor_api_url: str = "http://127.0.0.1:3333"
    monitor_api_token: SecretStr | None = None
    monitor_timeout_segundos: float = Field(default=20.0, gt=0)
    monitor_cache_ttl_segundos: int = Field(default=60, ge=0)

    llm_provider: ProviderNome = "fake"
    llm_modelo: str = "gpt-4o-mini"
    llm_api_key: SecretStr | None = None
    llm_base_url: str = "https://api.openai.com/v1"
    llm_temperatura: float = Field(default=0.2, ge=0, le=2)
    llm_max_tokens: int = Field(default=1500, gt=0)
    llm_timeout_segundos: float = Field(default=60.0, gt=0)
    llm_max_tentativas: int = Field(default=2, ge=0, le=5)
    llm_modo_pensamento: Literal["auto", "enabled", "disabled"] = "auto"
    """Controle do modo de raciocínio (dialeto do DeepSeek: `thinking.type`).

    `auto` não envia o campo — necessário para provedores que não o conhecem
    (OpenAI, Groq...), que rejeitariam uma chave desconhecida.

    No DeepSeek o raciocínio vem **ligado por padrão**, e nesse modo o
    `temperature` é ignorado e os tokens de raciocínio consomem o
    `max_tokens`. Para respostas factuais sobre dados já filtrados, `disabled`
    é mais rápido, mais barato e devolve resultados reproduzíveis.
    """

    contexto_max_licitacoes: int = Field(default=150, gt=0)
    contexto_max_caracteres_objeto: int = Field(default=240, gt=20)

    agente_host: str = "127.0.0.1"
    agente_port: int = Field(default=8000, gt=0, lt=65536)

    digest_dias_padrao: int = Field(default=7, gt=0, le=365)

    @field_validator("monitor_api_url", "llm_base_url")
    @classmethod
    def _remover_barra_final(cls, valor: str) -> str:
        return valor.rstrip("/")

    @field_validator("log_level")
    @classmethod
    def _validar_log_level(cls, valor: str) -> str:
        nivel = valor.upper()
        if nivel not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError(f"LOG_LEVEL inválido: {valor}")
        return nivel

    @property
    def token_monitor(self) -> str | None:
        """Token da API do monitor em texto puro (ou None quando não configurado)."""
        return _segredo_para_texto(self.monitor_api_token)

    @property
    def chave_llm(self) -> str | None:
        """Chave da API do LLM em texto puro (ou None quando não configurada)."""
        return _segredo_para_texto(self.llm_api_key)


def _segredo_para_texto(valor: SecretStr | str | None) -> str | None:
    """Extrai o texto de um `SecretStr`, tolerando `model_copy` (que não valida).

    Sem esta tolerância, um `settings.model_copy(update={"monitor_api_token": None})`
    em teste guardaria uma `str` crua no campo e quebraria o acesso ao segredo.
    """
    if valor is None:
        return None

    if isinstance(valor, SecretStr):
        return valor.get_secret_value()

    return str(valor)


@lru_cache
def obter_settings() -> Settings:
    """Devolve a configuração única da aplicação (memoizada)."""
    return Settings()
