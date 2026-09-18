"""Modelos das requisições e respostas do agente (chat e digest)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator

from app.schemas.licitacao import ModeloBase


class MensagemHistorico(ModeloBase):
    """Uma mensagem anterior da conversa, enviada para dar contexto ao modelo."""

    papel: Literal["user", "assistant"]
    conteudo: str = Field(min_length=1, max_length=8000)


class PerguntaChat(ModeloBase):
    """Pergunta em linguagem natural sobre as licitações monitoradas."""

    pergunta: str = Field(min_length=3, max_length=2000, description="Ex.: 'quais pregões abrem em outubro?'")
    historico: list[MensagemHistorico] = Field(default_factory=list, max_length=20)
    incluir_referencias: bool = Field(
        default=True,
        description="Se verdadeiro, a resposta lista os processos citados com seus dados",
    )

    @field_validator("pergunta")
    @classmethod
    def _limpar_pergunta(cls, valor: str) -> str:
        return valor.strip()


class ReferenciaLicitacao(ModeloBase):
    """Licitação citada na resposta — extraída por comparação determinística."""

    id: str
    numero_processo: str | None = None
    modalidade: str | None = None
    objeto: str | None = None
    data_abertura: datetime | None = None
    situacao: str | None = None

    @field_validator("data_abertura", mode="before")
    @classmethod
    def _converter_data(cls, valor: object) -> datetime | None:
        from app.utils.datas import para_datetime

        return para_datetime(valor)


class TokensUso(ModeloBase):
    """Consumo de tokens informado pelo provedor, quando disponível."""

    prompt: int | None = None
    completion: int | None = None
    total: int | None = None
    cache_hit: int | None = None
    cache_miss: int | None = None

    @property
    def percentual_cache(self) -> float | None:
        """Percentual do prompt que veio do cache (None quando não informado)."""
        if not self.cache_hit or not self.prompt:
            return None

        return round(self.cache_hit / self.prompt * 100, 1)


class RespostaChat(ModeloBase):
    """Resposta do agente para uma pergunta."""

    resposta: str
    provedor: str
    modelo: str
    tokens: TokensUso | None = None
    referencias: list[ReferenciaLicitacao] = Field(default_factory=list)
    licitacoes_no_contexto: int = 0
    gerado_em: datetime
    aviso: str | None = Field(
        default=None,
        description="Preenchido quando a resposta tem ressalvas (ex.: provedor de teste)",
    )


class DigestRequest(ModeloBase):
    """Pedido de digest: resumo dos processos com abertura na janela informada."""

    dias: int = Field(default=7, ge=1, le=365)
    enviar: bool = Field(
        default=False,
        description="Se falso (padrão), apenas gera o digest. Se verdadeiro, envia por e-mail.",
    )
    destinatarios: list[str] | None = Field(
        default=None, description="Sobrescreve os destinatários configurados"
    )
    incluir_analise_llm: bool = Field(
        default=True,
        description="Se falso, gera apenas a parte tabular determinística",
    )


class DigestResponse(ModeloBase):
    """Resultado da geração (e eventual envio) do digest."""

    titulo: str
    html: str
    texto: str | None = None
    janela_dias: int
    total_licitacoes: int
    provedor: str | None = None
    modelo: str | None = None
    enviado: bool = False
    message_id: str | None = None
    destinatarios: list[str] = Field(default_factory=list)
    gerado_em: datetime
