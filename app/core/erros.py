"""Erros de domínio do agente.

Ter exceções próprias permite que a camada HTTP traduza cada falha em um status
adequado (502 para o monitor fora do ar, 503 para o LLM não configurado, etc.)
sem inspecionar mensagens de bibliotecas de terceiros.
"""

from __future__ import annotations


class AgenteError(Exception):
    """Erro base do agente."""


class ConfiguracaoError(AgenteError):
    """Configuração ausente ou inválida (ex.: chave de LLM não definida)."""


class MonitorApiError(AgenteError):
    """Falha ao consultar a API do monitor (Node)."""

    def __init__(self, mensagem: str, status_code: int | None = None) -> None:
        super().__init__(mensagem)
        self.mensagem = mensagem
        self.status_code = status_code


class LLMError(AgenteError):
    """Falha ao chamar o provedor de LLM."""

    def __init__(self, mensagem: str, provedor: str | None = None, status_code: int | None = None) -> None:
        super().__init__(mensagem)
        self.mensagem = mensagem
        self.provedor = provedor
        self.status_code = status_code
