"""Provedor determinístico para desenvolvimento, testes e demonstração.

Não é um LLM: ele extrai da pergunta as palavras significativas e devolve as
linhas do bloco de fatos que as contêm. Isso permite exercitar todo o caminho
(API do monitor → contexto → agente → HTTP) sem chave de API e sem custo, e
serve de duplo de teste nas suítes automatizadas.

Quando uma resposta sai daqui, os agentes marcam `aviso` no retorno e os digests
usam um texto determinístico — nunca se apresenta saída deste provedor como
análise de IA.
"""

from __future__ import annotations

import re
import time

from app.llm.base import Mensagem, Papel, ProvedorLLM, RespostaLLM

_STOPWORDS = {
    "a", "ao", "aos", "as", "com", "como", "da", "das", "de", "do", "dos", "e", "em", "entre",
    "essa", "esse", "esta", "este", "eu", "foi", "ha", "há", "isso", "isto", "ja", "já", "mais",
    "mas", "me", "na", "nas", "no", "nos", "o", "os", "ou", "para", "pela", "pelo", "por", "que",
    "quais", "qual", "quando", "quanto", "se", "sem", "ser", "sua", "tem", "ter", "um", "uma",
    "voce", "você", "lista", "listar", "mostra", "mostrar", "diga", "informe", "sobre", "todos",
    "todas", "gostaria", "saber", "poderia", "favor", "por favor",
}

_LIMITE_LINHAS = 60
_TAMANHO_MINIMO_TERMO = 4


class ProvedorFake(ProvedorLLM):
    """Duplo de teste que responde a partir do próprio contexto recebido."""

    nome = "fake"

    async def gerar(
        self,
        mensagens: list[Mensagem],
        temperatura: float | None = None,
        max_tokens: int | None = None,
    ) -> RespostaLLM:
        inicio = time.perf_counter()

        pergunta = next(
            (m.conteudo for m in reversed(mensagens) if m.papel in (Papel.USUARIO, "user")),
            "",
        )
        contexto = "\n".join(
            m.conteudo for m in mensagens if m.papel in (Papel.SISTEMA, "system")
        )

        linhas = self._selecionar_linhas(pergunta, contexto)

        texto = "\n".join(
            [
                "**[provedor de teste — nenhuma IA foi consultada]**",
                "",
                f"Pergunta recebida: {pergunta.strip() or '(vazia)'}",
                "",
                "Trechos da base de licitações relacionados à pergunta:",
                "",
                *linhas,
                "",
                (
                    "Para obter respostas redigidas em linguagem natural, configure um "
                    "provedor de LLM real (LLM_PROVIDER=openai_compativel e LLM_API_KEY)."
                ),
            ]
        )

        return RespostaLLM(
            texto=texto,
            provedor=self.nome,
            modelo="deterministico",
            tokens=None,
            latencia_ms=int((time.perf_counter() - inicio) * 1000),
        )

    async def verificar_saude(self) -> bool:
        """Sempre disponível: não depende de rede nem de credenciais."""
        return True


    def _selecionar_linhas(self, pergunta: str, contexto: str) -> list[str]:
        """Devolve as linhas da seção de DADOS que casam com os termos da pergunta.

        A busca é restrita ao bloco de dados: se olhasse o prompt inteiro, as
        próprias regras do sistema ("responda sobre os processos...") apareceriam
        como resultados.
        """
        linhas = [linha for linha in self._secao_dados(contexto).splitlines() if linha.strip()]
        termos = self._extrair_termos(pergunta)

        if not termos:
            return linhas[:_LIMITE_LINHAS]

        selecionadas: list[str] = []

        for indice, linha in enumerate(linhas):
            if not any(termo in linha.lower() for termo in termos):
                continue

            conteudo = linha.strip()

            if conteudo.startswith("objeto:") and indice > 0:
                anterior = linhas[indice - 1].strip()
                if anterior.startswith("- ") and anterior not in selecionadas:
                    selecionadas.append(anterior)

            if conteudo not in selecionadas:
                selecionadas.append(conteudo)

        if not selecionadas:
            return ["(nenhum processo da base correspondeu aos termos da pergunta)"]

        return selecionadas[:_LIMITE_LINHAS]

    @staticmethod
    def _secao_dados(contexto: str) -> str:
        """Recorta o bloco após o marcador `=== DADOS ===`."""
        marcador = "=== DADOS ==="
        posicao = contexto.find(marcador)

        return contexto[posicao + len(marcador) :] if posicao >= 0 else contexto

    @staticmethod
    def _extrair_termos(pergunta: str) -> list[str]:
        """Palavras significativas da pergunta (sem stopwords e com 4+ letras).

        Cada palavra entra também sem o "s" final: sem isso, "concorrências" não
        casaria com "Concorrência" e a busca não devolveria nada.
        """
        palavras = re.findall(r"[0-9a-zA-ZÀ-ÿ/]+", pergunta.lower())

        termos: list[str] = []

        for palavra in palavras:
            if len(palavra) < _TAMANHO_MINIMO_TERMO or palavra in _STOPWORDS:
                continue

            termos.append(palavra)

            if palavra.endswith("s") and len(palavra) - 1 >= _TAMANHO_MINIMO_TERMO:
                termos.append(palavra[:-1])

        return termos
