"""Texto: normalização para busca, truncamento e escape de HTML."""

from __future__ import annotations

import html
import re
import unicodedata

_TAGS_PERIGOSAS = re.compile(
    r"<\s*(script|style|iframe|object|embed)\b.*?<\s*/\s*\1\s*>",
    re.IGNORECASE | re.DOTALL,
)
_ESPACOS = re.compile(r"\s+")


def normalizar_texto(valor: object) -> str:
    """Remove acentos e caixa, para busca tolerante ("pregao" acha "Pregão")."""
    texto = unicodedata.normalize("NFD", str(valor or ""))
    sem_acento = "".join(caractere for caractere in texto if unicodedata.category(caractere) != "Mn")
    return _ESPACOS.sub(" ", sem_acento).strip().lower()


def truncar(valor: object, limite: int, sufixo: str = "...") -> str:
    """Trunca preservando palavras inteiras quando possível."""
    texto = _ESPACOS.sub(" ", str(valor or "")).strip()

    if len(texto) <= limite:
        return texto

    corte = texto[:limite].rsplit(" ", 1)[0]
    return f"{corte or texto[:limite]}{sufixo}"


def escapar_html(valor: object) -> str:
    """Escapa um valor para interpolação segura em HTML."""
    return html.escape(str(valor or ""), quote=True)


def limpar_html_llm(valor: str) -> str:
    """Remove tags perigosas do HTML gerado pelo modelo.

    O trecho narrativo do digest é escrito por um LLM e depois enviado por
    e-mail; sem esta limpeza, um texto gerado poderia injetar `<script>` na
    mensagem. Os dados tabulares do digest são montados por template, não pelo
    modelo, então o risco fica restrito a este trecho.
    """
    return _TAGS_PERIGOSAS.sub("", str(valor or "")).strip()


def contem_algum(texto: str, termos: list[str]) -> bool:
    """Indica se o texto normalizado contém algum dos termos informados."""
    alvo = normalizar_texto(texto)
    return any(normalizar_texto(termo) in alvo for termo in termos if termo)
