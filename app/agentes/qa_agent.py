"""Agente de perguntas e respostas sobre as licitações monitoradas.

Estratégia: **contexto embutido em uma única chamada**. A base inteira é
compactada (ver `ContextoService`) e enviada no prompt, junto com os agregados.
Para 127 processos isso custa poucos milhares de tokens, roda em uma chamada só
e evita a complexidade de um laço de tool-calling — o backend Node já resolve os
filtros, então o modelo só precisa redigir a resposta sobre fatos prontos.
"""

from __future__ import annotations

from app.agentes import prompts, referencias
from app.core.config import Settings, obter_settings
from app.core.logging import obter_logger
from app.llm.base import Mensagem, ProvedorLLM
from app.schemas.conversa import PerguntaChat, ReferenciaLicitacao, RespostaChat
from app.services.contexto_service import ContextoService
from app.services.licitacoes_service import LicitacoesService
from app.utils.datas import agora_utc

logger = obter_logger(__name__)

AVISO_PROVEDOR_FAKE = (
    "Resposta gerada pelo provedor de teste (LLM_PROVIDER=fake): houve busca "
    "determinística nos dados, sem interpretação por IA. Configure um provedor "
    "de LLM para respostas redigidas em linguagem natural."
)


class AgenteQA:
    """Responde perguntas em linguagem natural sobre os processos salvos."""

    def __init__(
        self,
        licitacoes_service: LicitacoesService,
        provedor: ProvedorLLM,
        contexto_service: ContextoService | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._servico = licitacoes_service
        self._provedor = provedor
        self._settings = settings or obter_settings()
        self._contexto = contexto_service or ContextoService(self._settings)

    async def responder(self, pergunta: PerguntaChat) -> RespostaChat:
        """Monta o contexto, consulta o modelo e devolve a resposta com fontes."""
        licitacoes = await self._servico.todas()
        resumo = await self._servico.resumo()

        mensagens = [
            Mensagem.sistema(
                prompts.montar_sistema_qa(
                    agregados=self._contexto.montar_agregados(resumo),
                    contexto=self._contexto.montar(licitacoes),
                    cabecalho_temporal=self._contexto.cabecalho_temporal(),
                )
            )
        ]

        for mensagem in pergunta.historico[-10:]:
            mensagens.append(
                Mensagem.usuario(mensagem.conteudo)
                if mensagem.papel == "user"
                else Mensagem.assistente(mensagem.conteudo)
            )

        mensagens.append(Mensagem.usuario(pergunta.pergunta))

        logger.info(
            "Consultando %s com %s licitações no contexto", self._provedor.nome, len(licitacoes)
        )
        resposta = await self._provedor.gerar(mensagens)

        fontes: list[ReferenciaLicitacao] = (
            referencias.extrair_referencias(resposta.texto, licitacoes)
            if pergunta.incluir_referencias
            else []
        )

        return RespostaChat(
            resposta=resposta.texto,
            provedor=resposta.provedor,
            modelo=resposta.modelo,
            tokens=resposta.tokens,
            referencias=fontes,
            licitacoes_no_contexto=len(licitacoes),
            gerado_em=agora_utc(),
            aviso=AVISO_PROVEDOR_FAKE if resposta.provedor == "fake" else None,
        )
