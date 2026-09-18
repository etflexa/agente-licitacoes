"""Configuração de logging do agente.

Centralizar aqui evita `print` espalhado e garante que bibliotecas verbosas
(httpx) não poluam o log em nível INFO.
"""

from __future__ import annotations

import logging
import sys

_FORMATO = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_DATA = "%Y-%m-%d %H:%M:%S"

_configurado = False


def configurar_logging(nivel: str = "INFO") -> None:
    """Configura o logging raiz uma única vez."""
    global _configurado

    if _configurado:
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(_FORMATO, datefmt=_DATA))

    raiz = logging.getLogger()
    raiz.setLevel(nivel.upper())
    raiz.handlers = [handler]

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    _configurado = True


def obter_logger(nome: str) -> logging.Logger:
    """Atalho para obter um logger nomeado."""
    return logging.getLogger(nome)
