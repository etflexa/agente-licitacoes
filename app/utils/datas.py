"""Datas: conversão tolerante e formatação em português.

A origem dos dados mistura ISO 8601 (`2026-08-17T09:00:00Z`) e formato
brasileiro (`17/08/2026 09:00`), então a conversão precisa aceitar ambos sem
derrubar o agente quando aparecer um valor inesperado.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

_FORMATOS_BR = ("%d/%m/%Y %H:%M", "%d/%m/%Y")


def para_datetime(valor: object) -> datetime | None:
    """Converte um valor arbitrário em `datetime` com timezone, ou None.

    Valores inválidos viram None em vez de exceção: um registro com data
    estranha não deve impedir a listagem inteira de funcionar.
    """
    if valor is None or valor == "":
        return None

    if isinstance(valor, datetime):
        return valor if valor.tzinfo else valor.replace(tzinfo=UTC)

    if isinstance(valor, date):
        return datetime(valor.year, valor.month, valor.day, tzinfo=UTC)

    texto = str(valor).strip()

    try:
        convertido = datetime.fromisoformat(texto)
        return convertido if convertido.tzinfo else convertido.replace(tzinfo=UTC)
    except ValueError:
        pass

    for formato in _FORMATOS_BR:
        try:
            return datetime.strptime(texto, formato).replace(tzinfo=UTC)
        except ValueError:
            continue

    return None


def formatar_data_br(valor: object, com_hora: bool = True) -> str:
    """Formata em `17/08/2026 às 09:00` (ou `17/08/2026` quando `com_hora=False`)."""
    convertido = para_datetime(valor)

    if convertido is None:
        return "N/A"

    if not com_hora:
        return convertido.strftime("%d/%m/%Y")

    return convertido.strftime("%d/%m/%Y às %H:%M")


def formatar_data_iso(valor: object) -> str | None:
    """Formata em ISO 8601 (usado para montar filtros da API do monitor)."""
    convertido = para_datetime(valor)
    return convertido.isoformat() if convertido else None


def agora_utc() -> datetime:
    """Agora, em UTC e com timezone."""
    return datetime.now(UTC)


def dias_entre(inicio: object, fim: object) -> int | None:
    """Diferença em dias inteiros entre duas datas (None se alguma for inválida)."""
    a, b = para_datetime(inicio), para_datetime(fim)
    if a is None or b is None:
        return None
    return (b - a).days
