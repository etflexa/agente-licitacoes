"""Extração determinística das licitações citadas numa resposta.

O modelo não é confiável para dizer "usei os processos X e Y", então isso não é
perguntado a ele: procuramos na própria resposta os números de processo da base
e devolvemos os registros correspondentes. É o que permite exibir a resposta com
dados verificáveis ao lado.
"""

from __future__ import annotations

import re

from app.schemas.conversa import ReferenciaLicitacao
from app.schemas.licitacao import LicitacaoResumo

_PADRAO_PROCESSO = re.compile(r"\b(\d{1,4})\s*/\s*(\d{4})\b")

LIMITE_REFERENCIAS = 12


def extrair_referencias(
    texto: str,
    licitacoes: list[LicitacaoResumo],
    limite: int = LIMITE_REFERENCIAS,
) -> list[ReferenciaLicitacao]:
    """Devolve as licitações cujo número de processo aparece no texto."""
    if not texto or not licitacoes:
        return []

    indices = {_chave(licitacao.numero_processo): licitacao for licitacao in licitacoes}
    encontrados: list[ReferenciaLicitacao] = []
    vistos: set[str] = set()

    for numero, ano in _PADRAO_PROCESSO.findall(texto):
        chave = f"{int(numero)}/{ano}"
        licitacao = indices.get(chave)

        if licitacao is None or licitacao.id in vistos:
            continue

        vistos.add(licitacao.id)
        encontrados.append(
            ReferenciaLicitacao(
                id=licitacao.id,
                numero_processo=licitacao.numero_processo,
                modalidade=licitacao.modalidade,
                objeto=licitacao.objeto,
                data_abertura=licitacao.data_abertura,
                situacao=licitacao.situacao,
            )
        )

        if len(encontrados) >= limite:
            break

    return encontrados


def _chave(numero_processo: str | None) -> str:
    """Normaliza "02/2026" e "2/2026" para a mesma chave."""
    if not numero_processo:
        return ""

    encontrado = _PADRAO_PROCESSO.search(numero_processo)

    return f"{int(encontrado.group(1))}/{encontrado.group(2)}" if encontrado else numero_processo.lower()
