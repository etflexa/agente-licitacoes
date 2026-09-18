"""Testes do adapter de LLM compatível com a OpenAI e da fábrica de provedores.

Cobrem o que costuma quebrar na troca de provedor: parâmetro não suportado,
chave ausente, erro HTTP, resposta truncada e resposta vazia. Nada aqui toca a
rede real — o transporte é simulado.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from app.core.config import Settings
from app.core.erros import ConfiguracaoError, LLMError
from app.llm.base import Mensagem, Papel
from app.llm.factory import criar_provedor, provedores_disponiveis
from app.llm.fake import ProvedorFake
from app.llm.openai_compativel import ProvedorOpenAICompativel


class LLMSimulado:
    """Transporte que captura o payload e devolve respostas programáveis."""

    def __init__(self) -> None:
        self.corpos: list[dict[str, Any]] = []
        self.cabecalhos: list[httpx.Headers] = []
        self.respostas: list[httpx.Response] = []
        self.resposta_padrao = httpx.Response(
            200,
            json={
                "model": "deepseek-flash",
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "Resposta de teste."},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 120, "completion_tokens": 8, "total_tokens": 128},
            },
        )

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.corpos.append(json.loads(request.content.decode()))
        self.cabecalhos.append(request.headers)

        if self.respostas:
            return self.respostas.pop(0)

        return self.resposta_padrao


def montar_settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "_env_file": None,
        "llm_provider": "openai_compativel",
        "llm_api_key": "chave-de-teste",
        "llm_base_url": "https://api.deepseek.com",
        "llm_modelo": "deepseek-flash",
        "llm_max_tentativas": 1,
    }
    base.update(overrides)
    return Settings(**base)


@pytest.fixture
def simulado() -> LLMSimulado:
    return LLMSimulado()


@pytest.fixture
def provedor(simulado: LLMSimulado) -> ProvedorOpenAICompativel:
    settings = montar_settings()
    http = httpx.AsyncClient(
        transport=httpx.MockTransport(simulado), base_url=settings.llm_base_url
    )
    return ProvedorOpenAICompativel(settings, cliente=http)


PERGUNTA = [Mensagem.sistema("Você é um assistente."), Mensagem.usuario("Olá")]


class TestPayload:
    async def test_envia_modelo_mensagens_e_temperatura(
        self, provedor: ProvedorOpenAICompativel, simulado: LLMSimulado
    ) -> None:
        await provedor.gerar(PERGUNTA)

        corpo = simulado.corpos[0]

        assert corpo["model"] == "deepseek-flash"
        assert corpo["messages"][0] == {"role": "system", "content": "Você é um assistente."}
        assert corpo["temperature"] == pytest.approx(0.2)
        assert corpo["max_tokens"] == 1500

    async def test_modo_pensamento_auto_nao_envia_o_campo(
        self, provedor: ProvedorOpenAICompativel, simulado: LLMSimulado
    ) -> None:
        """`auto` mantém compatibilidade com provedores que não conhecem o campo."""
        await provedor.gerar(PERGUNTA)

        assert "thinking" not in simulado.corpos[0]

    async def test_modo_pensamento_configurado_e_enviado(
        self, simulado: LLMSimulado
    ) -> None:
        settings = montar_settings(llm_modo_pensamento="disabled")
        http = httpx.AsyncClient(
            transport=httpx.MockTransport(simulado), base_url=settings.llm_base_url
        )
        provedor = ProvedorOpenAICompativel(settings, cliente=http)

        await provedor.gerar(PERGUNTA)

        assert simulado.corpos[0]["thinking"] == {"type": "disabled"}

    async def test_temperatura_e_max_tokens_podem_ser_sobrescritos(
        self, provedor: ProvedorOpenAICompativel, simulado: LLMSimulado
    ) -> None:
        await provedor.gerar(PERGUNTA, temperatura=0.7, max_tokens=99)

        assert simulado.corpos[0]["temperature"] == pytest.approx(0.7)
        assert simulado.corpos[0]["max_tokens"] == 99

    async def test_envia_a_chave_no_cabecalho(
        self, provedor: ProvedorOpenAICompativel, simulado: LLMSimulado
    ) -> None:
        await provedor.gerar(PERGUNTA)

        assert simulado.cabecalhos[0]["authorization"] == "Bearer chave-de-teste"


class TestResposta:
    async def test_extrai_texto_modelo_e_tokens(self, provedor: ProvedorOpenAICompativel) -> None:
        resposta = await provedor.gerar(PERGUNTA)

        assert resposta.texto == "Resposta de teste."
        assert resposta.modelo == "deepseek-flash"
        assert resposta.provedor == "openai_compativel"
        assert resposta.tokens is not None
        assert resposta.tokens.total == 128
        assert resposta.latencia_ms is not None

    async def test_mapeia_os_tokens_de_cache(
        self, provedor: ProvedorOpenAICompativel, simulado: LLMSimulado
    ) -> None:
        """O DeepSeek reporta o acerto de cache no topo de `usage`."""
        simulado.respostas.append(
            httpx.Response(
                200,
                json={
                    "model": "deepseek-flash",
                    "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                    "usage": {
                        "prompt_tokens": 14000,
                        "completion_tokens": 200,
                        "total_tokens": 14200,
                        "prompt_cache_hit_tokens": 13800,
                        "prompt_cache_miss_tokens": 200,
                    },
                },
            )
        )

        resposta = await provedor.gerar(PERGUNTA)

        assert resposta.tokens is not None
        assert resposta.tokens.cache_hit == 13800
        assert resposta.tokens.cache_miss == 200
        assert resposta.tokens.percentual_cache == pytest.approx(98.6)

    async def test_cache_ausente_em_outros_provedores(
        self, provedor: ProvedorOpenAICompativel
    ) -> None:
        """Sem os campos de cache, nada quebra e o percentual fica indefinido."""
        resposta = await provedor.gerar(PERGUNTA)

        assert resposta.tokens is not None
        assert resposta.tokens.cache_hit is None
        assert resposta.tokens.percentual_cache is None

    async def test_resposta_truncada_e_entregue_com_alerta(
        self, provedor: ProvedorOpenAICompativel, simulado: LLMSimulado, caplog
    ) -> None:
        simulado.respostas.append(
            httpx.Response(
                200,
                json={
                    "model": "deepseek-flash",
                    "choices": [
                        {"message": {"content": "Texto cortado no meio"}, "finish_reason": "length"}
                    ],
                },
            )
        )

        with caplog.at_level("WARNING"):
            resposta = await provedor.gerar(PERGUNTA)

        assert resposta.texto == "Texto cortado no meio"
        assert "truncada pelo max_tokens" in caplog.text

    async def test_resposta_vazia_e_erro(
        self, provedor: ProvedorOpenAICompativel, simulado: LLMSimulado
    ) -> None:
        simulado.respostas.append(
            httpx.Response(200, json={"choices": [{"message": {"content": "   "}}]})
        )

        with pytest.raises(LLMError, match="vazia"):
            await provedor.gerar(PERGUNTA)

    async def test_sem_escolhas_e_erro(
        self, provedor: ProvedorOpenAICompativel, simulado: LLMSimulado
    ) -> None:
        simulado.respostas.append(httpx.Response(200, json={"choices": []}))

        with pytest.raises(LLMError):
            await provedor.gerar(PERGUNTA)


class TestErros:
    async def test_sem_chave_falha_antes_da_rede(self, simulado: LLMSimulado) -> None:
        settings = montar_settings(llm_api_key=None)
        http = httpx.AsyncClient(
            transport=httpx.MockTransport(simulado), base_url=settings.llm_base_url
        )
        provedor = ProvedorOpenAICompativel(settings, cliente=http)

        with pytest.raises(ConfiguracaoError, match="LLM_API_KEY"):
            await provedor.gerar(PERGUNTA)

        assert simulado.corpos == []

    async def test_sem_mensagens_e_erro(self, provedor: ProvedorOpenAICompativel) -> None:
        with pytest.raises(LLMError, match="Nenhuma mensagem"):
            await provedor.gerar([])

    async def test_401_traz_a_mensagem_do_provedor(
        self, provedor: ProvedorOpenAICompativel, simulado: LLMSimulado
    ) -> None:
        simulado.respostas.append(
            httpx.Response(401, json={"error": {"message": "Authentication Fails"}})
        )

        with pytest.raises(LLMError) as capturado:
            await provedor.gerar(PERGUNTA)

        assert capturado.value.status_code == 401
        assert "Authentication Fails" in capturado.value.mensagem

    async def test_modelo_inexistente_400(
        self, provedor: ProvedorOpenAICompativel, simulado: LLMSimulado
    ) -> None:
        simulado.respostas.append(
            httpx.Response(400, json={"error": {"message": "Model Not Exist"}})
        )

        with pytest.raises(LLMError, match="Model Not Exist"):
            await provedor.gerar(PERGUNTA)

    async def test_429_tenta_novamente_e_tem_sucesso(
        self, provedor: ProvedorOpenAICompativel, simulado: LLMSimulado
    ) -> None:
        simulado.respostas.append(httpx.Response(429, json={"error": {"message": "Rate limit"}}))

        resposta = await provedor.gerar(PERGUNTA)

        assert resposta.texto == "Resposta de teste."
        assert len(simulado.corpos) == 2

    async def test_timeout_apos_tentativas(
        self, provedor: ProvedorOpenAICompativel
    ) -> None:
        def estourar(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("tempo esgotado", request=request)

        http = httpx.AsyncClient(
            transport=httpx.MockTransport(estourar), base_url="https://api.deepseek.com"
        )
        provedor = ProvedorOpenAICompativel(montar_settings(llm_max_tentativas=0), cliente=http)

        with pytest.raises(LLMError, match="Tempo esgotado"):
            await provedor.gerar(PERGUNTA)

    async def test_erro_nao_vaza_a_chave(
        self, provedor: ProvedorOpenAICompativel, simulado: LLMSimulado
    ) -> None:
        simulado.respostas.extend([httpx.Response(500, text="falha interna")] * 2)

        with pytest.raises(LLMError) as capturado:
            await provedor.gerar(PERGUNTA)

        assert "chave-de-teste" not in capturado.value.mensagem
        assert "falha interna" in capturado.value.mensagem


class TestFabrica:
    def test_cria_provedor_configurado(self) -> None:
        provedor = criar_provedor(settings=montar_settings())

        assert isinstance(provedor, ProvedorOpenAICompativel)
        assert provedor.nome == "openai_compativel"
        assert provedor.modelo == "deepseek-flash"

    def test_cria_provedor_fake(self) -> None:
        assert isinstance(criar_provedor(settings=montar_settings(llm_provider="fake")), ProvedorFake)

    def test_provedor_desconhecido_e_erro(self) -> None:
        with pytest.raises(ConfiguracaoError, match="desconhecido"):
            criar_provedor("gemini", montar_settings())

    def test_provedores_disponiveis(self) -> None:
        assert provedores_disponiveis() == ["fake", "openai_compativel"]


class TestMensagem:
    def test_atalhos_de_papel(self) -> None:
        assert Mensagem.sistema("a").papel == Papel.SISTEMA
        assert Mensagem.usuario("b").papel == "user"
        assert Mensagem.assistente("c").papel == "assistant"
