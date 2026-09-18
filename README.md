# Agente de Licitações — SENAC/AP

Agente de IA que responde perguntas em linguagem natural sobre as licitações
monitoradas pelo sistema de monitoramento do SENAC/AP.

Módulo **independente**: não lê arquivos nem banco do projeto Node, e não
duplica regra de negócio. Ele consome a API HTTP do projeto
[`monitor-licitacoes-IA`](../monitor-licitacoes-IA), que continua sendo a dona
dos dados.

---

## 1. Arquitetura

```
┌─────────────────────────────┐        ┌──────────────────────────────────┐
│  monitor-licitacoes-IA      │        │  agente-licitacoes (este módulo) │
│  (Node)                     │        │  (Python / FastAPI)              │
│                             │        │                                  │
│  cron */5 * * * *           │        │  GET  /api/chat   ─┐             │
│    └─ busca API do portal   │◄───────┼── GET  /api/licitacoes           │
│    └─ compara com o store   │  HTTP  │   POST /api/digest ─┘             │
│    └─ envia e-mail          │        │                                  │
│                             │        │  ContextoService → Prompt → LLM  │
│  data/licitacoes.json       │        │                                  │
│  (registro completo)        │        │  LLM plugável (OpenAI-compatível)│
└─────────────────────────────┘        └──────────────────────────────────┘
```

Decisões de projeto:

| Decisão | Motivo |
|---|---|
| O agente fala HTTP, não lê arquivo | Mantém o Node como fonte única da verdade e permite trocar o backend sem tocar no agente. |
| Filtros e janelas de data no Node | Comparação exata de datas no backend; o LLM só redige, não calcula. |
| Envio de e-mail no Node | Credenciais SMTP e layout dos e-mails já vivem lá — um só lugar para manter. |
| Camada de LLM abstrata | Trocar de provedor é escrever uma classe, não reescrever os agentes. |
| Digest = template determinístico + narrativa do LLM | Os fatos (tabela, datas) vêm do código; o modelo só escreve o texto de abertura. |

### Contexto em uma única chamada

A base inteira (127 processos) é compactada em ~2 mil linhas de texto enxuto
(objeto truncado em 240 caracteres) e enviada no *system prompt*, junto com os
agregados. Isso cabe folgadamente no contexto de um modelo atual, roda em **uma
chamada** e dispensa o laço de *tool-calling* — mais simples de depurar e mais
barato por pergunta.

---

## 2. Instalação

```bash
cd agente-licitacoes

python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt  # só runtime: requirements.txt

cp .env.example .env
```

No `.env`, o campo `MONITOR_API_TOKEN` precisa ser **idêntico** ao `API_TOKEN` do
`.env` do projeto Node:

```bash
# gera um token e grava nos dois .env
TOKEN=$(openssl rand -hex 24)
sed -i "s|^API_TOKEN=.*|API_TOKEN=$TOKEN|" ../monitor-licitacoes-IA/.env
sed -i "s|^MONITOR_API_TOKEN=.*|MONITOR_API_TOKEN=$TOKEN|" .env
```

---

## 3. Subir o sistema

Dois processos, em terminais separados:

```bash
# 1) API do monitor (dona dos dados) — porta 3333
cd ../monitor-licitacoes-IA && npm run api

# 2) Agente de IA — porta 8000
cd ../agente-licitacoes && source .venv/bin/activate && python -m app.main
```

- Documentação interativa: <http://127.0.0.1:8000/docs>
- Diagnóstico: <http://127.0.0.1:8000/health>

Se o monitor não estiver no ar, as rotas de licitações devolvem **502** com a
mensagem `O servidor Node está rodando (npm run api)?`.

---

## 4. Endpoints

| Método | Rota | Descrição |
|---|---|---|
| `GET` | `/health` | Estado do agente, do LLM e do monitor |
| `POST` | `/api/chat` | Pergunta em linguagem natural |
| `GET` | `/api/licitacoes` | Lista paginada com filtros (`q`, `modalidade`, `situacao`, `de`, `ate`, `somenteFuturas`, `limit`, `offset`…) |
| `GET` | `/api/licitacoes/resumo` | Agregados por modalidade/situação e estado do monitor |
| `GET` | `/api/licitacoes/proximas-aberturas?dias=7` | Aberturas na janela |
| `GET` | `/api/licitacoes/{id}` | Registro completo, com documentos |
| `POST` | `/api/licitacoes/cache/invalidar` | Descarta o cache local do agente |
| `POST` | `/api/digest` | Gera o digest e, com `enviar=true`, envia por e-mail |

### Exemplo: perguntar

```bash
curl -s -X POST http://127.0.0.1:8000/api/chat \
  -H 'content-type: application/json' \
  -d '{"pergunta": "quais pregões eletrônicos abrem em outubro de 2026?"}' | jq
```

```json
{
  "resposta": "...",
  "provedor": "openai_compativel",
  "modelo": "gpt-4o-mini",
  "referencias": [
    {"numeroProcesso": "12/2026", "modalidade": "Pregão eletrônico", "dataAbertura": "2026-10-05T09:00:00Z"}
  ],
  "licitacoesNoContexto": 127,
  "geradoEm": "2026-09-18T06:30:00Z"
}
```

O campo `referencias` **não** vem do modelo: os números de processo são
procurados na resposta por expressão regular e cruzados com a base. É assim que
o consumidor consegue conferir o que a IA afirmou.

### Exemplo: digest

```bash
# só gera (não envia)
curl -s -X POST http://127.0.0.1:8000/api/digest -d '{"dias": 30}' \
  -H 'content-type: application/json' | jq -r .html > /tmp/digest.html

# gera e envia por e-mail
curl -s -X POST http://127.0.0.1:8000/api/digest -d '{"dias": 30, "enviar": true}' \
  -H 'content-type: application/json' | jq
```

---

## 5. Linha de comando

Útil para testar sem subir servidor e para agendar o digest no cron do sistema:

```bash
python -m app.cli perguntar "quais processos tratam de obras de engenharia?"
python -m app.cli perguntar "e o segundo?" --historico "quais concorrências existem?" "Existem quatro."
python -m app.cli resumo
python -m app.cli listar --modalidade "Pregão eletrônico" --situacao "Em processo" --limite 5
python -m app.cli listar --futuras --ordenar numeroProcesso --json
python -m app.cli detalhar 01884554-c548-4de2-9663-10fc57ff2b52
python -m app.cli digest --dias 7 --mostrar-html
python -m app.cli digest --dias 7 --enviar
python -m app.cli health
python -m app.cli testar-llm          # valida a chave do provedor com uma chamada real
python -m app.cli servir --reload
```

Agendando o digest diário às 8h (opcional — o monitor de novas licitações já
roda no Node):

```cron
0 8 * * 1-5 cd /caminho/agente-licitacoes && .venv/bin/python -m app.cli digest --dias 7 --enviar
```

Após instalar o pacote (`pip install -e .`), os mesmos comandos ficam
disponíveis como `agente-licitacoes <comando>`.

---

## 6. Escolhendo o provedor de LLM

O provedor padrão é **`fake`**: determinístico, sem custo e sem chave — ele
permite validar toda a integração antes de gastar com API. As respostas vêm
marcadas com o campo `aviso`, e o digest usa um texto determinístico em vez de
narrativa de IA.

Para usar IA de verdade, no `.env`:

```ini
LLM_PROVIDER=openai_compativel
LLM_API_KEY=sua-chave
LLM_MODELO=gpt-4o-mini
LLM_BASE_URL=https://api.openai.com/v1
```

### Provedor recomendado: DeepSeek

```ini
LLM_PROVIDER=openai_compativel
LLM_BASE_URL=https://api.deepseek.com
LLM_MODELO=deepseek-flash
LLM_MODO_PENSAMENTO=disabled
LLM_API_KEY=sua-chave
```

Valide a chave com uma chamada real antes de usar:

```bash
python -m app.cli testar-llm
```

Três particularidades do DeepSeek que valem atenção:

| Ponto | Detalhe |
|---|---|
| Nomes de modelo | Hoje são **`deepseek-flash`** e **`deepseek-v4-pro`**. O antigo `deepseek-chat` não é mais aceito. |
| Base URL | `https://api.deepseek.com` — a barra final é removida automaticamente, e a chamada vai para `/chat/completions`. |
| Modo de raciocínio | Vem **ligado por padrão** (effort `high`). Nesse modo o `temperature` é **ignorado sem erro** e os tokens de raciocínio consomem o `max_tokens` — com `LLM_MAX_TOKENS=1500` a resposta pode chegar truncada. Por isso o padrão aqui é `LLM_MODO_PENSAMENTO=disabled`. |

Com `disabled`, as respostas são factuais, reproduzíveis e o `temperature` volta
a valer. Se você fizer perguntas que exijam raciocínio sobre as datas, teste
`LLM_MODO_PENSAMENTO=enabled` **aumentando `LLM_MAX_TOKENS`** (em modo de
raciocínio o padrão do provedor é 64K, e uma resposta truncada gera aviso no
log com `finish_reason=length`).

Sobre custo — **medido**, não estimado. O contexto (127 processos ≈ 14.300
tokens) é idêntico entre perguntas; só a pergunta final muda, então o cache de
contexto do DeepSeek reaproveita quase todo o prompt. Em duas perguntas
consecutivas:

| Chamada | Prompt | Cache | Resposta | Custo aprox. (off-peak) |
|---|---|---|---|---|
| 1ª (cache frio) | 14.281 | 1,8% | 397 | ~US$ 0,0024 |
| 2ª em diante | 14.281 | **98,6%** | 292 | ~US$ 0,0003 |

A primeira pergunta custa ~0,24 centavo de dólar e as seguintes ~0,03. Nos
horários de pico do provedor (01h–04h e 06h–10h UTC, seg–sex) os valores dobram.
O consumo vem no campo `tokens` de cada resposta (com `cacheHit` e `cacheMiss`),
e a CLI mostra o percentual reaproveitado.

### Outros provedores compatíveis

O provedor `openai_compativel` fala o dialeto `/chat/completions` e funciona com
qualquer serviço equivalente — basta trocar a base URL:

| Serviço | `LLM_BASE_URL` | Exemplo de `LLM_MODELO` |
|---|---|---|
| DeepSeek | `https://api.deepseek.com` | `deepseek-flash` |
| OpenAI | `https://api.openai.com/v1` | `gpt-4o-mini` |
| Groq | `https://api.groq.com/openai/v1` | `llama-3.3-70b-versatile` |
| Together | `https://api.together.xyz/v1` | `meta-llama/Llama-3.3-70B-Instruct-Turbo` |
| Ollama (local) | `http://localhost:11434/v1` | `llama3.1:8b` |
| LM Studio (local) | `http://localhost:1234/v1` | conforme o modelo carregado |

Para provedores que **não** conhecem o campo `thinking`, deixe
`LLM_MODO_PENSAMENTO=auto` (padrão): o campo não é enviado e eles não retornam
400 por parâmetro desconhecido.

Adicionar um provedor de dialeto diferente (Gemini, Anthropic):

1. crie `app/llm/meu_provedor.py` herdando de `ProvedorLLM`;
2. registre em `_PROVEDORES` no `app/llm/factory.py`;
3. acrescente o nome ao tipo `ProviderNome` em `app/core/config.py`.

Nenhum agente, rota ou teste precisa ser alterado.

---

## 7. Configuração (`.env`)

| Variável | Padrão | Descrição |
|---|---|---|
| `AMBIENTE` | `desenvolvimento` | Em `producao`, o servidor sobe sem *reload*. |
| `LOG_LEVEL` | `INFO` | `DEBUG` mostra o cache hit/miss. |
| `MONITOR_API_URL` | `http://127.0.0.1:3333` | Base da API do Node. |
| `MONITOR_API_TOKEN` | — | Mesmo token do `.env` do Node; sem ele não há envio de digest. |
| `MONITOR_TIMEOUT_SEGUNDOS` | `20` | Timeout das chamadas ao monitor. |
| `MONITOR_CACHE_TTL_SEGUNDOS` | `60` | Validade do cache local; `0` desliga o cache. |
| `LLM_PROVIDER` | `fake` | `fake` ou `openai_compativel`. |
| `LLM_MODELO` / `LLM_API_KEY` / `LLM_BASE_URL` | — | Configuração do provedor. |
| `LLM_TEMPERATURA` | `0.2` | Baixa por padrão: respostas factuais. |
| `LLM_MAX_TOKENS` | `1500` | Limite de saída. |
| `LLM_MAX_TENTATIVAS` | `2` | Retentativas em 429/5xx. |
| `LLM_MODO_PENSAMENTO` | `auto` | `auto` (não envia o campo), `disabled` ou `enabled` — dialeto do DeepSeek. |
| `CONTEXTO_MAX_LICITACOES` | `150` | Quantos processos entram no prompt. |
| `CONTEXTO_MAX_CARACTERES_OBJETO` | `240` | Truncamento do objeto no contexto. |
| `AGENTE_HOST` / `AGENTE_PORT` | `127.0.0.1` / `8000` | Bind do servidor do agente. |
| `DIGEST_DIAS_PADRAO` | `7` | Janela padrão do digest. |

---

## 8. Testes

```bash
source .venv/bin/activate
pytest            # 98 testes, ~4s
pytest -v         # detalhado
```

Os testes **não tocam a rede**: as chamadas ao monitor passam por um
`httpx.MockTransport` que imita a API do Node, e o provedor é o `fake`. Nenhum
e-mail é enviado. Cobrem:

- utilitários de data (ISO, formato brasileiro, valores inválidos) e de texto
  (normalização, truncamento, escape de HTML);
- cliente HTTP: filtros em camelCase, erros 404/500/timeout, autenticação e
  ausência de token;
- contexto: contagens, truncamento, limite de licitações;
- agentes: Q&A com extração de referências, digest com template/escape;
- API: status de cada rota, `422` de validação, tradução de erros do monitor
  (`404` → 404, `5xx` → 502, falta de token → 503) e OpenAPI;
- adapter de LLM: payload enviado, cabeçalho `Authorization`, `thinking` só
  quando configurado, resposta truncada/vazia, 401/400/429, tokens de cache,
  validação da chave e seleção de provedor pela fábrica.

---

## 9. Estrutura

```
agente-licitacoes/
├── app/
│   ├── main.py                  aplicação FastAPI + lifespan
│   ├── cli.py                   linha de comando
│   ├── core/
│   │   ├── config.py            Settings (pydantic-settings)
│   │   ├── erros.py             erros de domínio
│   │   └── logging.py
│   ├── schemas/                 contratos (snake_case ↔ camelCase)
│   ├── clients/
│   │   └── monitor_client.py    único ponto que fala com o Node
│   ├── services/
│   │   ├── licitacoes_service.py cache com TTL
│   │   └── contexto_service.py   montagem do contexto do LLM
│   ├── llm/
│   │   ├── base.py              interface ProvedorLLM
│   │   ├── openai_compativel.py implementação HTTP genérica
│   │   ├── fake.py              provedor determinístico
│   │   └── factory.py           seleção por configuração
│   ├── agentes/
│   │   ├── qa_agent.py          perguntas e respostas
│   │   ├── digest_agent.py      digest periódico
│   │   ├── prompts.py           prompts (ponto de ajuste fino)
│   │   └── referencias.py       processos citados, por regex
│   ├── templates/digest.py      HTML determinístico do digest
│   └── api/                     rotas e dependências
└── tests/                       74 testes, sem rede
```

---

## 10. Limitações conhecidas

- **Sem RAG sobre os PDFs.** Os 914 documentos (editais/anexos) entram apenas
  como metadados — nome, tipo, tamanho. A API do portal não expõe URL de
  download, então responder "o que diz a cláusula 5 do edital?" exigiria baixar
  os arquivos e indexá-los (embeddings + vector store). É o próximo passo
  natural, e o desenho atual não o impede.
- **Sem memória entre requisições.** O histórico é enviado pelo cliente a cada
  chamada; nada é persistido. Para conversas longas com histórico grande, um
  store de sessão seria necessário.
- **Contexto limitado a `CONTEXTO_MAX_LICITACOES`.** Com a base em 127
  processos não há truncamento; acima de ~300 o ideal passa a ser filtrar antes
  de montar o prompt.
- **Perfis de acesso.** A API do agente não tem autenticação; ela deve ficar em
  `127.0.0.1` ou atrás de um proxy com autenticação.
