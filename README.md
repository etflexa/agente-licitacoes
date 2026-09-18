# Agente de Licitações

Agente de IA que responde perguntas em linguagem natural sobre processos de
licitação pública, a partir dos dados coletados por um monitor de portal de
transparência.

Projeto **independente**: consome a API HTTP do monitor
([monitorDeProcessos](https://github.com/etflexa/monitorDeProcessos)) e não
acessa arquivos ou banco de dados dele.

---

## Funcionalidades

- **Perguntas em linguagem natural** — "quais pregões eletrônicos abrem em
  outubro?", "tem algo de obra de engenharia?", "quantos processos por
  modalidade?".
- **Consultas estruturadas** — filtros por modalidade, situação, intervalo de
  datas e busca textual, com paginação e ordenação.
- **Digest periódico por e-mail** — resumo das aberturas previstas na janela de
  dias escolhida, com prévia em HTML antes de enviar.
- **API REST** com documentação automática e **CLI** para uso em terminal e
  agendamento via cron.
- **Tolerante a falha**: responde em modo determinístico, sem IA e sem custo,
  quando não há chave de LLM configurada.

## Decisões técnicas

| Decisão | Motivo |
|---|---|
| O agente fala HTTP com o monitor | Uma única fonte da verdade; filtros e comparação de datas ficam no backend que domina os dados, e o LLM apenas redige |
| Uma chamada por pergunta | A base é compactada no *system prompt*; dispensa laço de *tool-calling* e é mais simples de depurar |
| Camada de LLM abstrata | Trocar de provedor é implementar uma classe e registrá-la na fábrica, sem tocar em agentes, rotas ou testes |
| Referências verificáveis | Os processos citados na resposta são extraídos por regex e cruzados com a base, em vez de declarados pelo modelo |
| Digest = template + narrativa | A parte factual (tabela, datas) vem de código determinístico; o modelo escreve só o texto de abertura, sanitizado antes do envio |
| Erros traduzidos por dependência | Monitor fora do ar vira `502`, recurso inexistente `404`, configuração ausente `503` |

## Custo e consumo de tokens

Cuidado deliberado, porque contexto grande é onde o custo de um agente costuma
sair de controle:

- **Contexto compactado** — o objeto de cada processo é truncado
  (`CONTEXTO_MAX_CARACTERES_OBJETO`, padrão 240 caracteres) e a quantidade de
  processos enviados é limitada (`CONTEXTO_MAX_LICITACOES`), mantendo o prompt
  previsível.
- **Cache de contexto** — como o contexto é idêntico entre perguntas e só a
  pergunta final muda, o provedor reaproveita o prefixo. Medido em duas
  perguntas consecutivas: **1,8% de acerto na primeira e 98,6% na segunda**.
- **Custo por pergunta, medido** (não estimado): ~US$ 0,0024 na primeira
  chamada e ~US$ 0,0003 nas seguintes, com uma base de 127 processos
  (~14.300 tokens de prompt).
- **Consumo visível** — cada resposta devolve `tokens` com `prompt`,
  `completion`, `cacheHit` e `cacheMiss`, e a CLI mostra o percentual
  reaproveitado.
- **Limites explícitos** — `LLM_MAX_TOKENS` e `LLM_MODO_PENSAMENTO` controlam o
  gasto de saída. Com o modo de raciocínio desligado, respostas ficam factuais e
  reproduzíveis e os tokens de raciocínio não consomem o limite.

## Stack

Python 3.11+ · FastAPI · Pydantic v2 · httpx · pytest

LLM por API compatível com a OpenAI, o que cobre OpenAI, DeepSeek, Groq,
Together, Ollama e LM Studio apenas trocando a base URL.

## Como rodar

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env          # preencha a chave do provedor
python -m app.main            # http://127.0.0.1:8000/docs
```

Sem chave configurada, o agente já sobe no provedor determinístico — útil para
validar a integração antes de gastar com API.

```bash
python -m app.cli perguntar "quais processos tratam de obras de engenharia?"
python -m app.cli resumo
python -m app.cli digest --dias 7 --mostrar-html
python -m app.cli testar-llm     # valida a chave com uma chamada real
```

## Testes

```bash
pytest        # 98 testes, ~4s
```

Rodam **sem rede, sem chave de API e sem enviar e-mail**: as chamadas ao monitor
passam por um `httpx.MockTransport` e o provedor é o determinístico. Cobrem
utilitários de data e texto, cliente HTTP (erros, timeout, autenticação),
montagem de contexto, os dois agentes, todas as rotas da API e o adapter de LLM
(payload, autenticação, retentativas, resposta truncada e tokens de cache).

## Estrutura

```
app/
├── main.py            aplicação FastAPI
├── cli.py             linha de comando
├── core/              configuração, logging e erros de domínio
├── schemas/           contratos (snake_case ↔ camelCase)
├── clients/           único ponto que fala com o monitor
├── services/          cache e montagem do contexto do LLM
├── llm/               interface abstrata, provedor OpenAI-compatível e determinístico
├── agentes/           Q&A, digest, prompts e extração de referências
├── templates/         HTML determinístico do digest
└── api/               rotas e injeção de dependências
```

## Limitações

- **Sem RAG sobre os PDFs.** Os editais entram apenas como metadados, porque o
  portal não expõe URL de download. Responder "o que diz a cláusula 5?" exigiria
  baixar e indexar os arquivos (embeddings + vector store) — o desenho atual não
  impede isso.
- **Sem memória entre requisições.** O histórico é enviado pelo cliente a cada
  chamada e nada é persistido.
- **A API do agente não tem autenticação**; deve rodar em `127.0.0.1` ou atrás
  de um proxy com login.
