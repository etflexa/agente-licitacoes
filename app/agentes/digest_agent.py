"""Agente de digest proativo.

Gera um resumo das aberturas na janela de dias escolhida e, opcionalmente, pede
ao Node que o envie por e-mail.

Divisão de responsabilidades deliberada:
  - **tabela e destaques** → template determinístico (fatos verificáveis);
  - **texto de abertura** → LLM (opcional), sanitizado antes de virar HTML;
  - **envio** → API do projeto Node, dona das credenciais SMTP e do layout.
"""

from __future__ import annotations

from app.agentes import prompts
from app.core.config import Settings, obter_settings
from app.core.logging import obter_logger
from app.llm.base import Mensagem, ProvedorLLM
from app.schemas.conversa import DigestRequest, DigestResponse
from app.schemas.licitacao import ProximasAberturas
from app.services.contexto_service import ContextoService
from app.services.licitacoes_service import LicitacoesService
from app.templates.digest import montar_html_digest
from app.utils.datas import agora_utc

logger = obter_logger(__name__)


class AgenteDigest:
    """Produz o digest periódico de aberturas."""

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

    async def gerar(self, requisicao: DigestRequest | None = None) -> DigestResponse:
        """Monta o digest. NÃO envia e-mail, mesmo se `enviar=True`."""
        requisicao = requisicao or DigestRequest(dias=self._settings.digest_dias_padrao)

        janela = await self._servico.proximas_aberturas(requisicao.dias)
        gerado_em = agora_utc()

        narrativa, provedor_usado, modelo_usado = await self._narrativa(janela, requisicao)

        html = montar_html_digest(janela, narrativa_html=narrativa, gerado_em=gerado_em)
        titulo = self._titulo(janela.total, requisicao.dias)

        return DigestResponse(
            titulo=titulo,
            html=html,
            texto=self._texto_alternativo(janela.total, requisicao.dias),
            janela_dias=requisicao.dias,
            total_licitacoes=janela.total,
            provedor=provedor_usado,
            modelo=modelo_usado,
            enviado=False,
            destinatarios=requisicao.destinatarios or [],
            gerado_em=gerado_em,
        )

    async def gerar_e_enviar(self, requisicao: DigestRequest | None = None) -> DigestResponse:
        """Gera o digest e pede ao monitor (Node) que envie por e-mail."""
        requisicao = requisicao or DigestRequest(dias=self._settings.digest_dias_padrao)
        digest = await self.gerar(requisicao)

        resultado = await self._servico.enviar_digest(
            titulo=digest.titulo,
            html=digest.html,
            texto=digest.texto,
            destinatarios=requisicao.destinatarios,
        )

        digest.enviado = True
        digest.message_id = (resultado or {}).get("messageId")
        digest.destinatarios = (resultado or {}).get("destinatarios") or digest.destinatarios

        logger.info("Digest enviado (%s processos na janela)", digest.total_licitacoes)

        return digest


    async def _narrativa(
        self, janela: ProximasAberturas, requisicao: DigestRequest
    ) -> tuple[str | None, str | None, str | None]:
        """Produz o parágrafo de abertura (LLM ou determinístico)."""
        provedor_real = self._provedor.nome != "fake"

        if not requisicao.incluir_analise_llm or not provedor_real:
            motivo = (
                "análise por LLM desativada na requisição"
                if not requisicao.incluir_analise_llm
                else "provedor de teste (fake) ativo"
            )
            logger.info("Digest com narrativa determinística (%s)", motivo)
            return self._narrativa_deterministica(janela), None, None

        dados = self._contexto.montar_janela(janela)

        resposta = await self._provedor.gerar(
            [
                Mensagem.sistema(
                    prompts.montar_sistema_digest(
                        dados=dados,
                        cabecalho_temporal=self._contexto.cabecalho_temporal(),
                    )
                ),
                Mensagem.usuario(
                    f"Redija o texto de abertura do digest de aberturas dos próximos "
                    f"{requisicao.dias} dias."
                ),
            ],
            temperatura=0.3,
        )

        return resposta.texto, resposta.provedor, resposta.modelo

    def _narrativa_deterministica(self, janela: ProximasAberturas) -> str:
        """Texto de abertura montado sem LLM, a partir dos números da janela."""
        total = janela.total

        if total == 0:
            return (
                "<p>Não há licitações com abertura prevista na janela consultada. "
                "O monitoramento segue ativo e qualquer novo processo ou alteração de data "
                "será notificado automaticamente.</p>"
            )

        modalidades: dict[str, int] = {}
        for licitacao in janela.itens:
            chave = licitacao.modalidade or "não informada"
            modalidades[chave] = modalidades.get(chave, 0) + 1

        predominantes = ", ".join(
            f"{modalidade} ({quantidade})"
            for modalidade, quantidade in sorted(modalidades.items(), key=lambda item: -item[1])
        )

        return (
            f"<p>Há <strong>{total} processo(s)</strong> com abertura prevista nos próximos "
            f"{janela.janela_dias} dias. Por modalidade: {predominantes}.</p>"
        )

    @staticmethod
    def _titulo(total: int, dias: int) -> str:
        if total == 0:
            return f"📋 Licitações SENAC/AP — sem aberturas nos próximos {dias} dias"
        return f"📋 Licitações SENAC/AP — {total} abertura(s) nos próximos {dias} dias"

    @staticmethod
    def _texto_alternativo(total: int, dias: int) -> str:
        """Versão em texto puro, para clientes de e-mail sem HTML."""
        if total == 0:
            return f"Nenhuma licitação com abertura nos próximos {dias} dias."
        return f"{total} licitação(ões) com abertura nos próximos {dias} dias. Veja a tabela no e-mail."
