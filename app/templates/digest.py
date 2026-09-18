"""Montagem do HTML do digest.

A parte tabular é 100% determinística e passa por `escapar_html` — os dados vêm
de uma API pública, mas tratá-los como não confiáveis é a postura correta quando
o destino é um e-mail. O modelo contribui apenas com o trecho narrativo, que é
sanitizado em `limpar_html_llm`.
"""

from __future__ import annotations

from datetime import datetime

from app.schemas.licitacao import LicitacaoResumo, ProximasAberturas
from app.utils.datas import formatar_data_br, para_datetime
from app.utils.texto import escapar_html, limpar_html_llm, truncar

_LIMITE_OBJETO_TABELA = 160


def montar_html_digest(
    janela: ProximasAberturas,
    narrativa_html: str | None = None,
    gerado_em: datetime | None = None,
) -> str:
    """Monta o corpo do digest (o Node envelopa no layout padrão de e-mail)."""
    partes: list[str] = []

    if narrativa_html:
        partes.append(f"<div class='narrativa'>{limpar_html_llm(narrativa_html)}</div>")

    if not janela.itens:
        partes.append(
            "<p><strong>Nenhuma licitação com abertura na janela consultada"
            f" ({escapar_html(formatar_data_br(janela.de, com_hora=False))} a"
            f" {escapar_html(formatar_data_br(janela.ate, com_hora=False))}).</strong></p>"
        )
        return "\n".join(partes)

    partes.append(f"<h2>Aberturas nos próximos {janela.janela_dias} dias</h2>")
    partes.append(
        "<p>Janela: "
        f"{escapar_html(formatar_data_br(janela.de, com_hora=False))} a "
        f"{escapar_html(formatar_data_br(janela.ate, com_hora=False))} — "
        f"{janela.total} processo(s).</p>"
    )
    partes.append(_tabela(janela.itens))
    partes.append(_destaques(janela.itens, gerado_em))

    return "\n".join(partes)


def _tabela(licitacoes: list[LicitacaoResumo]) -> str:
    """Tabela com um processo por linha."""
    linhas = [
        "<table>",
        (
            "<thead><tr>"
            "<th>Processo</th><th>Modalidade</th><th>Abertura</th>"
            "<th>Situação</th><th>Docs</th><th>Objeto</th>"
            "</tr></thead>"
        ),
        "<tbody>",
    ]

    for licitacao in licitacoes:
        objeto = truncar(licitacao.objeto, _LIMITE_OBJETO_TABELA) or "não informado"
        link = (
            f" <a href='{escapar_html(licitacao.link)}'>disputa</a>" if licitacao.link else ""
        )

        linhas.append(
            "<tr>"
            f"<td>{escapar_html(licitacao.numero_processo or 's/ número')}</td>"
            f"<td>{escapar_html(licitacao.modalidade or 's/ modalidade')}</td>"
            f"<td>{escapar_html(formatar_data_br(licitacao.data_abertura))}</td>"
            f"<td>{escapar_html(licitacao.situacao or 's/ situação')}</td>"
            f"<td>{licitacao.total_documentos}</td>"
            f"<td>{escapar_html(objeto)}{link}</td>"
            "</tr>"
        )

    linhas.extend(["</tbody>", "</table>"])

    return "\n".join(linhas)


def _destaques(licitacoes: list[LicitacaoResumo], gerado_em: datetime | None) -> str:
    """Lista curta de pontos de atenção."""
    referencia = para_datetime(gerado_em) or None
    sem_link = [licitacao for licitacao in licitacoes if not licitacao.link]

    itens: list[str] = []

    if licitacoes:
        proxima = min(
            (licitacao for licitacao in licitacoes if licitacao.data_abertura),
            key=lambda licitacao: licitacao.data_abertura,
            default=None,
        )
        if proxima:
            itens.append(
                "Abertura mais próxima: "
                f"<strong>{escapar_html(proxima.numero_processo or 's/ número')}</strong> "
                f"({escapar_html(proxima.modalidade or 's/ modalidade')}) em "
                f"{escapar_html(formatar_data_br(proxima.data_abertura))}."
            )

    if sem_link:
        numeros = ", ".join(
            escapar_html(licitacao.numero_processo or "s/ número") for licitacao in sem_link[:5]
        )
        restante = f" e mais {len(sem_link) - 5}" if len(sem_link) > 5 else ""
        itens.append(
            f"{len(sem_link)} processo(s) sem link de disputa eletrônica: {numeros}{restante}."
        )

    if referencia:
        itens.append(f"Digest gerado em {escapar_html(formatar_data_br(referencia))}.")

    if not itens:
        return ""

    linhas = "".join(f"<li>{item}</li>" for item in itens)

    return f"<h3>Destaques</h3><ul>{linhas}</ul>"
