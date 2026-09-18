"""Testes do contexto enviado ao LLM e dos agentes."""

from __future__ import annotations

from app.agentes.digest_agent import AgenteDigest
from app.agentes.qa_agent import AVISO_PROVEDOR_FAKE, AgenteQA
from app.agentes.referencias import extrair_referencias
from app.schemas.conversa import DigestRequest, PerguntaChat
from app.schemas.licitacao import LicitacaoResumo
from app.services.contexto_service import ContextoService


class TestContextoService:
    async def test_contexto_lista_processos_e_contagens(self, servico, settings) -> None:
        licitacoes = await servico.todas()
        contexto = ContextoService(settings).montar(licitacoes)

        assert "BASE DE LICITAÇÕES DO SENAC/AP — 4 processos" in contexto
        assert "RESUMO — por modalidade:" in contexto
        assert "12/2026" in contexto
        assert "objeto: Aquisição de equipamentos" in contexto

    async def test_contexto_trunca_objeto_longo(self, servico) -> None:
        from app.core.config import Settings

        pequeno = Settings(_env_file=None, contexto_max_caracteres_objeto=30)
        licitacoes = await servico.todas()

        contexto = ContextoService(pequeno).montar(licitacoes)

        assert "..." in contexto
        for linha in contexto.splitlines():
            if linha.strip().startswith("objeto:"):
                assert len(linha.strip()) <= 30 + len("objeto: ") + 3

    async def test_contexto_respeita_limite_de_licitacoes(self, servico) -> None:
        from app.core.config import Settings

        limitado = Settings(_env_file=None, contexto_max_licitacoes=2)
        licitacoes = await servico.todas()

        contexto = ContextoService(limitado).montar(licitacoes)

        assert contexto.count("\n- ") == 2
        assert "não foram listados por limite de contexto" in contexto

    async def test_contexto_vazio_e_explicito(self, settings) -> None:
        assert "VAZIA" in ContextoService(settings).montar([])

    async def test_agregados_trazem_status_do_monitor(self, servico, settings) -> None:
        resumo = await servico.resumo()
        agregados = ContextoService(settings).montar_agregados(resumo)

        assert "TOTAL DE PROCESSOS ARMAZENADOS: 4" in agregados
        assert "ÚLTIMA VARREDURA DO MONITOR" in agregados
        assert "novas=0" in agregados

    async def test_janela_sem_processos(self, servico, settings) -> None:
        from app.schemas.licitacao import ProximasAberturas

        vazia = ProximasAberturas(janelaDias=7, total=0, itens=[])
        texto = ContextoService(settings).montar_janela(vazia)

        assert "NENHUMA ABERTURA" in texto

    async def test_janela_informa_o_link_de_disputa(self, servico, settings) -> None:
        """O prompt manda destacar processos sem link: o dado precisa existir.

        Sem este campo o modelo inventava a informação e chegou a afirmar que não
        havia processos sem link, contradizendo a tabela do mesmo e-mail.
        """
        janela = await servico.proximas_aberturas(30)
        texto = ContextoService(settings).montar_janela(janela)

        assert "link de disputa: NÃO INFORMADO" in texto

        com_link = [item for item in janela.itens if item.link]
        if com_link:
            assert f"link de disputa: {com_link[0].link}" in texto


class TestReferencias:
    def test_extrai_processos_citados(self) -> None:
        licitacoes = [
            LicitacaoResumo(id="a", numero_processo="12/2026", objeto="TI"),
            LicitacaoResumo(id="b", numero_processo="07/2026", objeto="Manutenção"),
        ]

        encontradas = extrair_referencias(
            "O processo 12/2026 abre em outubro, enquanto o 07/2026 já abriu.", licitacoes
        )

        assert [referencia.numero_processo for referencia in encontradas] == ["12/2026", "07/2026"]

    def test_ignora_processos_que_nao_existem_na_base(self) -> None:
        licitacoes = [LicitacaoResumo(id="a", numero_processo="12/2026")]

        assert extrair_referencias("O processo 99/2020 não existe.", licitacoes) == []

    def test_nao_repete_o_mesmo_processo(self) -> None:
        licitacoes = [LicitacaoResumo(id="a", numero_processo="12/2026")]

        encontradas = extrair_referencias("12/2026 e novamente 12/2026.", licitacoes)

        assert len(encontradas) == 1

    def test_normaliza_zero_a_esquerda(self) -> None:
        licitacoes = [LicitacaoResumo(id="a", numero_processo="02/2026")]

        assert len(extrair_referencias("processo 2/2026", licitacoes)) == 1

    def test_texto_vazio(self) -> None:
        assert extrair_referencias("", [LicitacaoResumo(id="a", numero_processo="12/2026")]) == []


class TestAgenteQA:
    async def test_responde_com_referencias_e_aviso(self, servico, provedor_fake, settings) -> None:
        agente = AgenteQA(servico, provedor_fake, settings=settings)

        resposta = await agente.responder(PerguntaChat(pergunta="quais processos tratam de engenharia?"))

        assert resposta.resposta.strip()
        assert resposta.provedor == "fake"
        assert resposta.aviso == AVISO_PROVEDOR_FAKE
        assert resposta.licitacoes_no_contexto == 4

    async def test_referencias_podem_ser_omitidas(self, servico, provedor_fake, settings) -> None:
        agente = AgenteQA(servico, provedor_fake, settings=settings)

        resposta = await agente.responder(
            PerguntaChat(pergunta="fale sobre 02/2026", incluir_referencias=False)
        )

        assert resposta.referencias == []

    async def test_historico_e_enviado_ao_modelo(self, servico, provedor_fake, settings) -> None:
        agente = AgenteQA(servico, provedor_fake, settings=settings)

        resposta = await agente.responder(
            PerguntaChat(
                pergunta="e o segundo?",
                historico=[
                    {"papel": "user", "conteudo": "quais pregões existem?"},
                    {"papel": "assistant", "conteudo": "Existem vários."},
                ],
            )
        )

        assert resposta.resposta.strip()

    async def test_pergunta_curta_e_rejeitada_pelo_modelo(self) -> None:
        import pytest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            PerguntaChat(pergunta="?")


class TestAgenteDigest:
    async def test_gera_html_com_tabela(self, servico, provedor_fake, settings) -> None:
        agente = AgenteDigest(servico, provedor_fake, settings=settings)

        digest = await agente.gerar(DigestRequest(dias=30))

        assert digest.enviado is False
        assert digest.total_licitacoes == 3
        assert "<table>" in digest.html
        assert "12/2026" in digest.html
        assert digest.janela_dias == 30

    async def test_narrativa_deterministica_com_provedor_fake(
        self, servico, provedor_fake, settings
    ) -> None:
        agente = AgenteDigest(servico, provedor_fake, settings=settings)

        digest = await agente.gerar(DigestRequest(dias=30))

        assert digest.provedor is None
        assert "processo(s)</strong> com abertura prevista" in digest.html

    async def test_sem_analise_llm_nao_chama_provedor(self, servico, settings) -> None:
        class ProvedorQueExplode:
            nome = "explode"
            modelo = "nenhum"

            async def gerar(self, *args, **kwargs):
                raise AssertionError("o provedor não deveria ser chamado")

            async def verificar_saude(self) -> bool:
                return True

            async def fechar(self) -> None:
                return None

        agente = AgenteDigest(servico, ProvedorQueExplode(), settings=settings)

        digest = await agente.gerar(DigestRequest(dias=30, incluir_analise_llm=False))

        assert digest.provedor is None
        assert digest.total_licitacoes == 3

    async def test_gerar_e_enviar_posta_para_a_api_do_monitor(
        self, servico, provedor_fake, settings, monitor_simulado
    ) -> None:
        agente = AgenteDigest(servico, provedor_fake, settings=settings)

        digest = await agente.gerar_e_enviar(DigestRequest(dias=30, enviar=True))

        assert digest.enviado is True
        assert digest.message_id == "<teste@senac>"
        assert monitor_simulado.corpos_postados[0]["titulo"] == digest.titulo
        assert "<table>" in monitor_simulado.corpos_postados[0]["html"]

    async def test_titulo_reflete_ausencia_de_aberturas(self, servico, provedor_fake, settings) -> None:
        agente = AgenteDigest(servico, provedor_fake, settings=settings)

        digest = await agente.gerar(DigestRequest(dias=1))

        assert digest.total_licitacoes == 0
        assert "sem aberturas" in digest.titulo

    async def test_html_escapa_marcacao_vinda_dos_dados(self) -> None:
        """Um objeto com HTML não deve virar código no e-mail."""
        from app.schemas.licitacao import ProximasAberturas
        from app.templates.digest import montar_html_digest

        janela = ProximasAberturas(
            janela_dias=7,
            total=1,
            itens=[
                LicitacaoResumo(
                    id="x",
                    numero_processo="09/2026",
                    modalidade="Pregão eletrônico",
                    objeto="<script>alert('xss')</script> obra",
                    data_abertura="2026-09-25T09:00:00Z",
                    situacao="Em processo",
                )
            ],
        )

        html = montar_html_digest(janela)

        assert "<script>" not in html
        assert "&lt;script&gt;" in html
