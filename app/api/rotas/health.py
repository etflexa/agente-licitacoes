"""Saúde do agente: verifica o LLM e a API do monitor."""

from __future__ import annotations

from fastapi import APIRouter

from app import __version__
from app.api.dependencias import ClienteMonitorDep, ProvedorDep, SettingsDep
from app.core.erros import MonitorApiError
from app.core.logging import obter_logger
from app.schemas.saude import SaudeAgente, SaudeLLM, SaudeMonitor

logger = obter_logger(__name__)

rotas = APIRouter(tags=["health"])


@rotas.get("/health", response_model=SaudeAgente, summary="Estado do agente, do LLM e do monitor")
async def health(
    settings: SettingsDep,
    provedor: ProvedorDep,
    cliente: ClienteMonitorDep,
) -> SaudeAgente:
    """Devolve um diagnóstico rápido de cada dependência externa."""
    try:
        dados = await cliente.verificar_saude()
        monitor = SaudeMonitor(
            status="ok" if dados.get("status") == "ok" else "degradado",
            url=settings.monitor_api_url,
            total_registros=dados.get("totalRegistros"),
            ultima_sincronizacao=dados.get("ultimaSincronizacao"),
            escrita_habilitada=dados.get("escritaHabilitada"),
        )
    except MonitorApiError as erro:
        monitor = SaudeMonitor(
            status="indisponivel",
            url=settings.monitor_api_url,
            erro=erro.mensagem,
        )

    llm_configurado = await provedor.verificar_saude()

    return SaudeAgente(
        status="ok" if monitor.status == "ok" and llm_configurado else "degradado",
        versao=__version__,
        ambiente=settings.ambiente,
        llm=SaudeLLM(
            provedor=provedor.nome,
            modelo=provedor.modelo,
            configurado=llm_configurado,
        ),
        monitor=monitor,
    )
