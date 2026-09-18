"""Montagem do contexto enviado ao LLM.

Os dados são serializados aqui, de forma determinística e compacta, por dois
motivos:

1. **Tokens** — 127 licitações com o objeto completo estouram o orçamento de
   contexto; truncando o objeto, a base inteira cabe com folga.
2. **Previsibilidade** — o formato do contexto é código testado, não algo que
   o modelo improvisa. O LLM recebe fatos e só redige a resposta.
"""

from __future__ import annotations

from app.core.config import Settings, obter_settings
from app.schemas.licitacao import LicitacaoResumo, ProximasAberturas, ResumoLicitacoes
from app.utils.datas import agora_utc, formatar_data_br
from app.utils.texto import truncar


class ContextoService:
    """Converte licitações em texto para o prompt."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or obter_settings()

    def montar(self, licitacoes: list[LicitacaoResumo]) -> str:
        """Monta um bloco de fatos com uma linha por licitação."""
        if not licitacoes:
            return "BASE DE LICITAÇÕES VAZIA: o monitor não retornou nenhum registro."

        limite = self._settings.contexto_max_licitacoes
        selecionadas = self._ordenar_por_data(licitacoes)[:limite]

        linhas = [
            (
                f"BASE DE LICITAÇÕES DO SENAC/AP — {len(licitacoes)} processos no total; "
                f"{len(selecionadas)} listados abaixo, ordenados por data de abertura."
            ),
            "",
            self._contagens(licitacoes),
            "",
            (
                "FORMATO: número do processo | modalidade | situação | abertura | "
                "nº de documentos | critério | link"
            ),
            "objeto: <descrição resumida>",
            "",
        ]

        truncamento = self._settings.contexto_max_caracteres_objeto

        for licitacao in selecionadas:
            documentos = licitacao.total_documentos
            linhas.append(
                "- {processo} ({modalidade}) | {situacao} | abre {abertura} | {documentos} doc(s) | "
                "critério: {criterio} | link: {link}".format(
                    processo=licitacao.numero_processo or "s/ número",
                    modalidade=licitacao.modalidade or "s/ modalidade",
                    situacao=licitacao.situacao or "s/ situação",
                    abertura=formatar_data_br(licitacao.data_abertura),
                    documentos=documentos,
                    criterio=licitacao.criterio_de_julgamento or "não informado",
                    link=licitacao.link or "não informado",
                )
            )
            linhas.append(f"  objeto: {truncar(licitacao.objeto, truncamento) or 'não informado'}")

        if len(licitacoes) > len(selecionadas):
            linhas.append("")
            linhas.append(
                f"({len(licitacoes) - len(selecionadas)} processos não foram listados por limite "
                "de contexto; se a pergunta exigir, informe que a listagem foi truncada.)"
            )

        return "\n".join(linhas)

    def montar_agregados(self, resumo: ResumoLicitacoes) -> str:
        """Bloco com números agregados, usado em perguntas de panorama."""
        por_modalidade = ", ".join(
            f"{modalidade}: {quantidade}" for modalidade, quantidade in sorted(resumo.por_modalidade.items())
        )
        por_situacao = ", ".join(
            f"{situacao}: {quantidade}" for situacao, quantidade in sorted(resumo.por_situacao.items())
        )

        linhas = [
            f"TOTAL DE PROCESSOS ARMAZENADOS: {resumo.total}",
            f"POR MODALIDADE: {por_modalidade or 'não informado'}",
            f"POR SITUAÇÃO: {por_situacao or 'não informado'}",
            f"PROCESSOS COM LINK DE DISPUTA: {resumo.com_link}",
            f"DOCUMENTOS (editais e anexos) PUBLICADOS: {resumo.total_documentos}",
            f"PRÓXIMA ABERTURA REGISTRADA: {formatar_data_br(resumo.proxima_abertura)}",
        ]

        if resumo.status_monitor and resumo.status_monitor.atualizado_em:
            linhas.append(
                "ÚLTIMA VARREDURA DO MONITOR: "
                f"{formatar_data_br(resumo.status_monitor.atualizado_em)} "
                f"(sucesso={resumo.status_monitor.sucesso}, novas={resumo.status_monitor.novas}, "
                f"alertas de data={resumo.status_monitor.alteradas})"
            )

        return "\n".join(linhas)

    def montar_janela(self, janela: ProximasAberturas) -> str:
        """Bloco com as aberturas dentro da janela de dias consultada."""
        inicio = formatar_data_br(janela.de, com_hora=False)
        fim = formatar_data_br(janela.ate, com_hora=False)

        if not janela.itens:
            return (
                f"NENHUMA ABERTURA nos próximos {janela.janela_dias} dias "
                f"(janela de {inicio} a {fim})."
            )

        linhas = [
            f"ABERTURAS NOS PRÓXIMOS {janela.janela_dias} DIAS: {janela.total} processo(s)",
            f"JANELA: {inicio} a {fim}",
            "",
        ]

        for licitacao in janela.itens:
            linhas.append(
                f"- {licitacao.numero_processo or 's/ número'} ({licitacao.modalidade or 's/ modalidade'}) "
                f"abre {formatar_data_br(licitacao.data_abertura)} | {licitacao.situacao or 's/ situação'} | "
                f"{licitacao.total_documentos} doc(s) | "
                f"link de disputa: {licitacao.link or 'NÃO INFORMADO'}"
            )
            linhas.append(
                f"  objeto: {truncar(licitacao.objeto, self._settings.contexto_max_caracteres_objeto)}"
            )

        return "\n".join(linhas)

    def cabecalho_temporal(self) -> str:
        """Data/hora atual, para o modelo raciocinar sobre prazos relativos."""
        agora = agora_utc()
        return (
            f"DATA E HORA ATUAIS (UTC): {agora.strftime('%d/%m/%Y %H:%M')} "
            f"({agora.strftime('%A')}). Considere esta data como 'hoje' ao interpretar "
            "'próxima semana', 'este mês' etc."
        )


    @staticmethod
    def _contagens(licitacoes: list[LicitacaoResumo]) -> str:
        modalidades: dict[str, int] = {}
        situacoes: dict[str, int] = {}

        for licitacao in licitacoes:
            modalidades[licitacao.modalidade or "não informada"] = (
                modalidades.get(licitacao.modalidade or "não informada", 0) + 1
            )
            situacoes[licitacao.situacao or "não informada"] = (
                situacoes.get(licitacao.situacao or "não informada", 0) + 1
            )

        por_modalidade = ", ".join(f"{chave}: {valor}" for chave, valor in sorted(modalidades.items()))
        por_situacao = ", ".join(f"{chave}: {valor}" for chave, valor in sorted(situacoes.items()))

        return f"RESUMO — por modalidade: {por_modalidade} | por situação: {por_situacao}"

    @staticmethod
    def _ordenar_por_data(licitacoes: list[LicitacaoResumo]) -> list[LicitacaoResumo]:
        """Ordena por data de abertura, jogando os registros sem data para o fim."""
        return sorted(
            licitacoes,
            key=lambda licitacao: (
                licitacao.data_abertura is None,
                licitacao.data_abertura or agora_utc(),
            ),
        )
