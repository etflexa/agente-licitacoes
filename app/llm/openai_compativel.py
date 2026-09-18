"""Provedor compatível com a API `/chat/completions` da OpenAI.

Cobre, sem código adicional, qualquer serviço que fale esse dialeto:

    OpenAI       https://api.openai.com/v1
    DeepSeek     https://api.deepseek.com/v1
    Groq         https://api.groq.com/openai/v1
    Together     https://api.together.xyz/v1
    Ollama       http://localhost:11434/v1   (chave pode ser qualquer texto)
    LM Studio    http://localhost:1234/v1

Por isso a implementação usa HTTP direto (httpx) em vez do SDK oficial: uma
dependência a menos e liberdade para apontar para qualquer base URL.
"""

from __future__ import annotations

import asyncio
import time

import httpx

from app.core.config import Settings
from app.core.erros import ConfiguracaoError, LLMError
from app.core.logging import obter_logger
from app.llm.base import Mensagem, ProvedorLLM, RespostaLLM
from app.schemas.conversa import TokensUso

logger = obter_logger(__name__)

_STATUS_RETENTAVEIS = {408, 409, 429, 500, 502, 503, 504}


class ProvedorOpenAICompativel(ProvedorLLM):
    """Cliente HTTP para qualquer serviço compatível com a OpenAI."""

    nome = "openai_compativel"

    def __init__(self, settings: Settings | None = None, cliente: httpx.AsyncClient | None = None) -> None:
        super().__init__(settings)

        self._url_base = self._settings.llm_base_url
        self._cliente = cliente or httpx.AsyncClient(
            base_url=self._url_base,
            timeout=self._settings.llm_timeout_segundos,
        )
        self._cliente_proprio = cliente is None

        self._cabecalhos = (
            {"Authorization": f"Bearer {self._settings.chave_llm}"}
            if self._settings.chave_llm
            else {}
        )

    @property
    def nome_exibicao(self) -> str:
        return f"{self.nome} ({self._url_base})"

    async def fechar(self) -> None:
        if self._cliente_proprio:
            await self._cliente.aclose()

    async def verificar_saude(self) -> bool:
        """Considera saudável quando a chave está presente e a base responde."""
        if not self._settings.chave_llm:
            return False

        try:
            resposta = await self._cliente.get("/models", headers=self._cabecalhos)
        except httpx.HTTPError:
            return False

        return resposta.status_code < 500

    async def gerar(
        self,
        mensagens: list[Mensagem],
        temperatura: float | None = None,
        max_tokens: int | None = None,
    ) -> RespostaLLM:
        """Chama `/chat/completions` com retentativas em falhas temporárias."""
        if not self._settings.chave_llm:
            raise ConfiguracaoError(
                "LLM_API_KEY não configurada. Defina a chave do provedor no .env "
                "(ou use LLM_PROVIDER=fake para testes sem custo)."
            )

        if not mensagens:
            raise LLMError("Nenhuma mensagem foi enviada ao modelo.", provedor=self.nome)

        corpo = {
            "model": self.modelo,
            "messages": [
                {"role": mensagem.papel, "content": mensagem.conteudo} for mensagem in mensagens
            ],
            "temperature": (
                temperatura if temperatura is not None else self._settings.llm_temperatura
            ),
            "max_tokens": max_tokens or self._settings.llm_max_tokens,
        }

        if self._settings.llm_modo_pensamento != "auto":
            corpo["thinking"] = {"type": self._settings.llm_modo_pensamento}

        inicio = time.perf_counter()
        ultimo_erro: Exception | None = None

        for tentativa in range(self._settings.llm_max_tentativas + 1):
            try:
                resposta = await self._cliente.post(
                    "/chat/completions", json=corpo, headers=self._cabecalhos
                )
            except httpx.TimeoutException:
                ultimo_erro = LLMError(
                    f"Tempo esgotado ({self._settings.llm_timeout_segundos}s) ao chamar {self._url_base}.",
                    provedor=self.nome,
                )
                logger.warning(
                    "Timeout na tentativa %s/%s",
                    tentativa + 1,
                    self._settings.llm_max_tentativas + 1,
                )
                await self._aguardar(tentativa)
                continue
            except httpx.HTTPError as erro:
                raise LLMError(
                    f"Falha de conexão com o provedor em {self._url_base}: {erro}", provedor=self.nome
                ) from erro

            if resposta.status_code in _STATUS_RETENTAVEIS and tentativa < self._settings.llm_max_tentativas:
                logger.warning(
                    "Provedor respondeu %s (tentativa %s/%s); aguardando nova tentativa.",
                    resposta.status_code,
                    tentativa + 1,
                    self._settings.llm_max_tentativas + 1,
                )
                ultimo_erro = LLMError(
                    self._extrair_erro(resposta), provedor=self.nome, status_code=resposta.status_code
                )
                await self._aguardar(tentativa)
                continue

            if resposta.status_code >= 400:
                raise LLMError(
                    self._extrair_erro(resposta), provedor=self.nome, status_code=resposta.status_code
                )

            return self._interpretar(resposta, int((time.perf_counter() - inicio) * 1000))

        raise ultimo_erro or LLMError("Falha ao chamar o provedor de LLM.", provedor=self.nome)


    async def _aguardar(self, tentativa: int) -> None:
        """Backoff exponencial curto entre tentativas."""
        await asyncio.sleep(min(2**tentativa * 0.5, 4.0))

    def _interpretar(self, resposta: httpx.Response, latencia_ms: int) -> RespostaLLM:
        """Extrai texto e uso de tokens do payload da OpenAI."""
        try:
            dados = resposta.json()
        except ValueError as erro:
            raise LLMError("Resposta não-JSON do provedor de LLM.", provedor=self.nome) from erro

        escolhas = dados.get("choices") or []
        if not escolhas:
            raise LLMError("O provedor não retornou nenhuma escolha de resposta.", provedor=self.nome)

        escolha = escolhas[0]
        texto = (escolha.get("message") or {}).get("content") or ""

        if not texto.strip():
            raise LLMError("O provedor retornou uma resposta vazia.", provedor=self.nome)

        if escolha.get("finish_reason") == "length":
            logger.warning(
                "Resposta truncada pelo max_tokens (%s). Aumente LLM_MAX_TOKENS ou "
                "desative o modo de raciocínio (LLM_MODO_PENSAMENTO=disabled).",
                self._settings.llm_max_tokens,
            )

        uso = dados.get("usage") or {}
        tokens = (
            TokensUso(
                prompt=uso.get("prompt_tokens"),
                completion=uso.get("completion_tokens"),
                total=uso.get("total_tokens"),
                cache_hit=uso.get("prompt_cache_hit_tokens"),
                cache_miss=uso.get("prompt_cache_miss_tokens"),
            )
            if uso
            else None
        )

        if tokens and tokens.cache_hit:
            logger.info(
                "Contexto servido pelo cache: %s%% do prompt (%s tokens).",
                tokens.percentual_cache,
                tokens.cache_hit,
            )

        return RespostaLLM(
            texto=texto.strip(),
            provedor=self.nome,
            modelo=dados.get("model") or self.modelo,
            tokens=tokens,
            latencia_ms=latencia_ms,
        )

    @staticmethod
    def _extrair_erro(resposta: httpx.Response) -> str:
        """Mensagem de erro legível, sem vazar a chave da API."""
        try:
            corpo = resposta.json()
            detalhe = (corpo.get("error") or {}).get("message") or corpo.get("message")
        except ValueError:
            detalhe = resposta.text[:300]

        return f"Provedor de LLM respondeu {resposta.status_code}: {detalhe or 'sem detalhes'}"
