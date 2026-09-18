"""Modelos do endpoint de saúde do agente."""

from __future__ import annotations

from app.schemas.licitacao import ModeloBase


class SaudeLLM(ModeloBase):
    """Estado do provedor de LLM configurado."""

    provedor: str
    modelo: str
    configurado: bool


class SaudeMonitor(ModeloBase):
    """Estado da API do monitor (Node)."""

    status: str
    url: str
    total_registros: int | None = None
    ultima_sincronizacao: str | None = None
    escrita_habilitada: bool | None = None
    erro: str | None = None


class SaudeAgente(ModeloBase):
    """Resposta de `GET /health`."""

    status: str
    versao: str
    ambiente: str
    llm: SaudeLLM
    monitor: SaudeMonitor
