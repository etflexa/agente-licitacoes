"""Interface de linha de comando do agente.

Serve para testar o agente sem subir servidor nem abrir navegador, e para
automatizar o digest em um cron do próprio sistema operacional.

    python -m app.cli perguntar "quais processos abrem em outubro?"
    python -m app.cli resumo
    python -m app.cli listar --modalidade "Pregão eletrônico" --limite 5
    python -m app.cli digest --dias 7 --html-arquivo /tmp/digest.html
    python -m app.cli digest --dias 7 --enviar
    python -m app.cli health
    python -m app.cli servir
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from pathlib import Path

from app.clients.monitor_client import MonitorClient
from app.core.config import Settings, obter_settings
from app.core.erros import AgenteError
from app.core.logging import configurar_logging
from app.llm.base import ProvedorLLM
from app.llm.factory import criar_provedor, provedores_disponiveis
from app.schemas.conversa import DigestRequest, MensagemHistorico, PerguntaChat
from app.schemas.licitacao import FiltrosLicitacao
from app.services.licitacoes_service import LicitacoesService
from app.utils.datas import formatar_data_br


@asynccontextmanager
async def _dependencias(
    settings: Settings,
) -> AsyncIterator[tuple[LicitacoesService, ProvedorLLM, MonitorClient]]:
    """Monta e finaliza as dependências, igual ao `lifespan` da API."""
    cliente = MonitorClient(settings)
    servico = LicitacoesService(cliente, settings)
    provedor = criar_provedor(settings=settings)

    try:
        yield servico, provedor, cliente
    finally:
        await provedor.fechar()
        await cliente.fechar()


async def _perguntar(args: argparse.Namespace, settings: Settings) -> int:
    from app.agentes.qa_agent import AgenteQA

    pergunta = " ".join(args.pergunta).strip()

    if not pergunta:
        print("Informe a pergunta. Ex.: python -m app.cli perguntar \"quais processos abrem em outubro?\"")
        return 2

    async with _dependencias(settings) as (servico, provedor, _cliente):
        agente = AgenteQA(servico, provedor, settings=settings)

        historico = [
            MensagemHistorico(papel="user" if indice % 2 == 0 else "assistant", conteudo=texto)
            for indice, texto in enumerate(args.historico or [])
        ]

        resposta = await agente.responder(
            PerguntaChat(
                pergunta=pergunta,
                historico=historico,
                incluir_referencias=not args.sem_referencias,
            )
        )

        if args.json:
            print(json.dumps(resposta.model_dump(by_alias=True, mode="json"), ensure_ascii=False, indent=2))
            return 0

        print("\n" + "=" * 72)
        print(resposta.resposta)
        print("=" * 72)

        if resposta.aviso:
            print(f"⚠️  {resposta.aviso}")

        if resposta.referencias:
            print(f"\n📎 Processos citados ({len(resposta.referencias)}):")
            for referencia in resposta.referencias:
                print(
                    f"   • {referencia.numero_processo} — {referencia.modalidade} — "
                    f"abre {formatar_data_br(referencia.data_abertura)} — {referencia.situacao}"
                )

        print(f"\n🤖 {resposta.provedor}/{resposta.modelo} | {_descrever_tokens(resposta.tokens)}")
        print(f"   {resposta.licitacoes_no_contexto} licitações no contexto")

    return 0


async def _resumo(args: argparse.Namespace, settings: Settings) -> int:
    async with _dependencias(settings) as (servico, _provedor, _cliente):
        resumo = await servico.resumo()

        if args.json:
            print(json.dumps(resumo.model_dump(by_alias=True, mode="json"), ensure_ascii=False, indent=2))
            return 0

        print(f"\n📊 BASE DE LICITAÇÕES — {resumo.total} processos armazenados\n")
        print("Por modalidade:")
        for modalidade, quantidade in sorted(resumo.por_modalidade.items(), key=lambda item: -item[1]):
            print(f"   {modalidade:<22} {quantidade:>4}")
        print("\nPor situação:")
        for situacao, quantidade in sorted(resumo.por_situacao.items(), key=lambda item: -item[1]):
            print(f"   {situacao:<22} {quantidade:>4}")
        print(f"\nCom link de disputa: {resumo.com_link}")
        print(f"Documentos publicados: {resumo.total_documentos}")
        print(f"Próxima abertura: {formatar_data_br(resumo.proxima_abertura)}")

        if resumo.status_monitor:
            status = resumo.status_monitor
            print(
                f"Última varredura do monitor: {formatar_data_br(status.atualizado_em)} "
                f"(sucesso={status.sucesso}, novas={status.novas}, alterações de data={status.alteradas})"
            )

    return 0


async def _listar(args: argparse.Namespace, settings: Settings) -> int:
    filtros = FiltrosLicitacao(
        q=args.busca,
        modalidade=args.modalidade,
        situacao=args.situacao,
        de=args.de,
        ate=args.ate,
        somente_futuras=args.futuras,
        somente_com_documentos=args.com_documentos,
        ordenar=args.ordenar,
        direcao=args.direcao,
        limit=args.limite,
        offset=args.offset,
    )

    async with _dependencias(settings) as (servico, _provedor, _cliente):
        resposta = await servico.buscar(filtros)

        if args.json:
            print(json.dumps(resposta.model_dump(by_alias=True, mode="json"), ensure_ascii=False, indent=2))
            return 0

        print(f"\n📋 {resposta.total} processo(s) encontrados (base: {resposta.total_geral})\n")

        for licitacao in resposta.itens:
            objeto = (licitacao.objeto or "")[:110]
            print(
                f"   {licitacao.numero_processo or 's/ número':<10} "
                f"{formatar_data_br(licitacao.data_abertura):<22} "
                f"{licitacao.modalidade or 's/ modalidade':<20} {licitacao.situacao or ''}"
            )
            print(f"      {objeto}...")

    return 0


async def _detalhar(args: argparse.Namespace, settings: Settings) -> int:
    async with _dependencias(settings) as (servico, _provedor, _cliente):
        licitacao = await servico.obter(args.id)

        if args.json:
            print(json.dumps(licitacao.model_dump(by_alias=True, mode="json"), ensure_ascii=False, indent=2))
            return 0

        print(f"\n📄 {licitacao.numero_processo} — {licitacao.modalidade}")
        print(f"   Situação: {licitacao.situacao}")
        print(f"   Abertura: {formatar_data_br(licitacao.data_abertura)}")
        print(f"   Critério: {licitacao.criterio_de_julgamento or 'não informado'}")
        print(f"   Link: {licitacao.link or 'não informado'}")
        print(f"\n   Objeto: {licitacao.objeto}")

        if licitacao.documentos:
            print(f"\n   📎 {len(licitacao.documentos)} documento(s):")
            for documento in licitacao.documentos:
                print(
                    f"      • {documento.nome or 'documento'} ({documento.tipo or 's/ tipo'}) — "
                    f"{documento.arquivo or 's/ arquivo'} — {documento.tamanho_legivel or 'n/d'}"
                )

    return 0


async def _digest(args: argparse.Namespace, settings: Settings) -> int:
    from app.agentes.digest_agent import AgenteDigest

    requisicao = DigestRequest(
        dias=args.dias,
        enviar=args.enviar,
        incluir_analise_llm=not args.sem_llm,
    )

    async with _dependencias(settings) as (servico, provedor, _cliente):
        agente = AgenteDigest(servico, provedor, settings=settings)

        if args.enviar:
            resultado = await agente.gerar_e_enviar(requisicao)
        else:
            resultado = await agente.gerar(requisicao)

    return _imprimir_digest(resultado, args)


def _imprimir_digest(resultado: object, args: argparse.Namespace) -> int:
    """Grava o HTML (se pedido) e imprime o resultado do digest."""
    if args.html_arquivo:
        Path(args.html_arquivo).write_text(resultado.html, encoding="utf-8")
        print(f"💾 HTML salvo em {args.html_arquivo}")

    if args.json:
        print(json.dumps(resultado.model_dump(by_alias=True, mode="json"), ensure_ascii=False, indent=2))
        return 0

    print(f"\n📬 {resultado.titulo}")
    print(f"   Janela: {resultado.janela_dias} dia(s) | processos: {resultado.total_licitacoes}")
    print(f"   Gerado em: {formatar_data_br(resultado.gerado_em)}")

    if resultado.enviado:
        print(f"   ✅ Enviado para: {', '.join(resultado.destinatarios) or 'destinatários padrão'}")
        print(f"   Message ID: {resultado.message_id}")
    else:
        print("   ℹ️  Nada foi enviado (use --enviar para disparar o e-mail).")
        if args.mostrar_html:
            print("\n" + resultado.html)

    return 0


async def _health(_args: argparse.Namespace, settings: Settings) -> int:
    async with _dependencias(settings) as (servico, provedor, cliente):
        print(f"\n🩺 Agente de Licitações — diagnóstico ({settings.ambiente})")
        print(f"   LLM: {provedor.nome} | modelo: {provedor.modelo}")

        try:
            dados = await cliente.verificar_saude()
            print(f"   Monitor: OK ({dados.get('totalRegistros')} registros em {settings.monitor_api_url})")
            print(f"   Última varredura: {dados.get('ultimaSincronizacao') or 'n/d'}")
            print(f"   Envio de digest habilitado: {dados.get('escritaHabilitada')}")
        except AgenteError as erro:
            print(f"   ❌ Monitor indisponível: {erro}")

        try:
            resumo = await servico.resumo()
            print(f"   Licitações acessíveis: {resumo.total}")
        except AgenteError as erro:
            print(f"   ❌ Não foi possível ler as licitações: {erro}")

        print(f"   Provedores de LLM disponíveis: {', '.join(provedores_disponiveis())}\n")

    return 0


async def _testar_llm(args: argparse.Namespace, settings: Settings) -> int:
    """Faz uma chamada mínima ao provedor para validar chave, modelo e URL.

    Diferente do `health` (que só verifica se a chave existe e o endpoint
    responde), aqui a geração acontece de fato — é o teste que pega modelo
    inexistente, chave inválida ou parâmetro não suportado.
    """
    from app.llm.base import Mensagem

    async with _dependencias(settings) as (_servico, provedor, _cliente):
        print(f"\n🔌 Testando provedor: {provedor.nome} | modelo: {provedor.modelo}")
        print(f"   Base URL: {settings.llm_base_url}")
        print(
            f"   Modo de raciocínio: {settings.llm_modo_pensamento} | "
            f"max_tokens: {settings.llm_max_tokens}"
        )

        try:
            resposta = await provedor.gerar(
                [
                    Mensagem.sistema("Responda em português do Brasil, em uma única frase curta."),
                    Mensagem.usuario(args.prompt),
                ]
            )
        except AgenteError as erro:
            print(f"\n❌ Falha: {erro}\n")
            return 1

        print("\n✅ Resposta do modelo:")
        print(f"   {resposta.texto}")
        print(f"\n   modelo retornado: {resposta.modelo}")
        print(f"   latência: {resposta.latencia_ms} ms")

        if resposta.tokens:
            print(
                f"   tokens: prompt={resposta.tokens.prompt} "
                f"completion={resposta.tokens.completion} total={resposta.tokens.total}"
            )

        if provedor.nome == "fake":
            print(
                "\n⚠️  Este é o provedor de teste. Para usar IA real, configure no .env:\n"
                "   LLM_PROVIDER=openai_compativel\n"
                "   LLM_BASE_URL=https://api.deepseek.com\n"
                "   LLM_MODELO=deepseek-flash\n"
                "   LLM_MODO_PENSAMENTO=disabled\n"
                "   LLM_API_KEY=sua-chave"
            )

        print()
        return 0


def _servir(args: argparse.Namespace, settings: Settings) -> int:
    import uvicorn

    host = args.host or settings.agente_host
    porta = args.porta or settings.agente_port

    print(f"🌐 Subindo o agente em http://{host}:{porta} (docs em /docs)")
    uvicorn.run("app.main:app", host=host, port=porta, reload=args.reload)

    return 0


def _descrever_tokens(tokens: object) -> str:
    """Descreve o consumo de tokens, incluindo o acerto de cache quando houver."""
    if tokens is None or tokens.total is None:
        return "tokens: n/d"

    descricao = f"tokens: {tokens.total} (prompt {tokens.prompt} + resposta {tokens.completion})"

    if tokens.cache_hit:
        descricao += f" | cache: {tokens.percentual_cache}% do prompt reaproveitado"

    return descricao


def _construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agente-licitacoes",
        description="Agente de IA para consulta às licitações monitoradas do SENAC/AP.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    subparsers = parser.add_subparsers(dest="comando", required=True)

    perguntar = subparsers.add_parser(
        "perguntar", aliases=["ask"], help="Faz uma pergunta em linguagem natural"
    )
    perguntar.add_argument("pergunta", nargs="+", help="Texto da pergunta")
    perguntar.add_argument(
        "--historico", nargs="*", help="Mensagens anteriores, alternando usuário/assistente"
    )
    perguntar.add_argument("--sem-referencias", action="store_true", help="Não extrair os processos citados")
    perguntar.add_argument("--json", action="store_true", help="Saída em JSON")

    resumo = subparsers.add_parser("resumo", help="Mostra os agregados da base")
    resumo.add_argument("--json", action="store_true", help="Saída em JSON")

    listar = subparsers.add_parser("listar", help="Lista licitações com filtros")
    listar.add_argument("--busca", "-q", help="Busca textual (objeto, processo, modalidade)")
    listar.add_argument("--modalidade", help="Ex.: 'Pregão eletrônico'")
    listar.add_argument("--situacao", help="Ex.: 'Em processo' ou 'Finalizada'")
    listar.add_argument("--de", help="Data inicial AAAA-MM-DD")
    listar.add_argument("--ate", help="Data final AAAA-MM-DD")
    listar.add_argument("--futuras", action="store_true", help="Somente aberturas futuras")
    listar.add_argument("--com-documentos", action="store_true", help="Somente com editais anexados")
    listar.add_argument(
        "--ordenar",
        default="dataAbertura",
        choices=["dataAbertura", "numeroProcesso", "modalidade", "situacao"],
    )
    listar.add_argument("--direcao", default="asc", choices=["asc", "desc"])
    listar.add_argument("--limite", type=int, default=20)
    listar.add_argument("--offset", type=int, default=0)
    listar.add_argument("--json", action="store_true", help="Saída em JSON")

    detalhar = subparsers.add_parser("detalhar", help="Mostra o registro completo de uma licitação")
    detalhar.add_argument("id", help="UUID da licitação")
    detalhar.add_argument("--json", action="store_true", help="Saída em JSON")

    digest = subparsers.add_parser("digest", help="Gera (e opcionalmente envia) o digest de aberturas")
    digest.add_argument("--dias", type=int, default=7, help="Janela em dias (padrão: 7)")
    digest.add_argument("--enviar", action="store_true", help="Envia o e-mail via API do monitor")
    digest.add_argument("--sem-llm", action="store_true", help="Narrativa determinística, sem chamar o LLM")
    digest.add_argument("--html-arquivo", help="Salva o HTML gerado no caminho informado")
    digest.add_argument("--mostrar-html", action="store_true", help="Imprime o HTML gerado")
    digest.add_argument("--json", action="store_true", help="Saída em JSON")

    subparsers.add_parser("health", help="Verifica LLM e API do monitor")

    testar = subparsers.add_parser(
        "testar-llm",
        aliases=["llm"],
        help="Faz uma chamada real ao provedor de LLM (valida chave e modelo)",
    )
    testar.add_argument(
        "--prompt",
        default="Diga apenas: conexão com o provedor de LLM funcionando.",
        help="Texto enviado ao modelo",
    )

    servir = subparsers.add_parser("servir", help="Sobe a API HTTP do agente")
    servir.add_argument("--host", help="Host (padrão do .env)")
    servir.add_argument("--porta", type=int, help="Porta (padrão do .env)")
    servir.add_argument("--reload", action="store_true", help="Recarrega ao alterar o código")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Ponto de entrada da CLI."""
    parser = _construir_parser()
    args = parser.parse_args(argv)

    settings = obter_settings()
    configurar_logging("WARNING" if args.comando in {"perguntar", "ask"} else settings.log_level)

    if args.comando == "servir":
        return _servir(args, settings)

    acoes = {
        "perguntar": _perguntar,
        "ask": _perguntar,
        "resumo": _resumo,
        "listar": _listar,
        "detalhar": _detalhar,
        "digest": _digest,
        "health": _health,
        "testar-llm": _testar_llm,
        "llm": _testar_llm,
    }

    try:
        return asyncio.run(acoes[args.comando](args, settings))
    except AgenteError as erro:
        print(f"\n❌ {erro}\n", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrompido pelo usuário.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
