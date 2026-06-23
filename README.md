# MTGA Tracker

Lê o `Player.log` do MTG Arena e registra o histórico de partidas (deck,
oponente, resultado, duração) no banco do
[mtg-collection-manager](https://github.com/leogaraph/mtg-collection-manager),
via a API existente daquele projeto. Não roda sozinho — depende do stack
do mtg-collection-manager estar de pé.

## Como funciona

```
Player.log (host)
     │
     ▼
mtga-tracker  — lê e interpreta os blocos JSON do log
     │  - MATCH_START → POST /api/matches
     │  - GAME_END     → PATCH /api/matches/:id
     ▼
mtg_api (do mtg-collection-manager) → mtg_collection (MySQL, tabela `matches`)
```

A detecção automática de qual deck foi jogado compara o `deck_arena_ids`
da partida (lido do log) com os decks marcados `platform='arena'` e
`is_active=1` no banco — se 80%+ das cartas baterem, associa
automaticamente.

## Pré-requisitos

- [mtg-collection-manager](https://github.com/leogaraph/mtg-collection-manager)
  já rodando via Docker Compose (`docker compose up -d` nele primeiro —
  este projeto se conecta na rede Docker que ele cria)
- MTG Arena instalado, com **"Detailed Logs (Plugin Support)"** ativado
  nas configurações do jogo (sem isso o `Player.log` não tem os blocos
  JSON necessários)

## Como rodar

### 1. Configurar o caminho do `Player.log` e o token de API

```bash
cp .env.example .env
```

Edite `.env` e ajuste `MTGA_LOG_DIR` para a pasta que contém o
`Player.log` no seu usuário Windows:

```
MTGA_LOG_DIR=C:\Users\SEU_USUARIO\AppData\LocalLow\Wizards Of The Coast\MTGA
```

Desde a versão multi-usuário do mtg-collection-manager, registrar
partidas exige um **token de API** da sua conta (sem ele, o tracker
detecta as partidas mas não consegue salvá-las). Gere um:

```bash
# 1. login normal (troque email/senha pela sua conta)
curl -X POST http://localhost:3001/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"voce@exemplo.com","password":"sua_senha"}'

# 2. com o token retornado, gera o token de API (de novo com a senha)
curl -X POST http://localhost:3001/api/auth/api-token \
  -H "Authorization: Bearer <token_do_passo_1>" \
  -H "Content-Type: application/json" \
  -d '{"password":"sua_senha"}'
```

Cole o token retornado em `API_TOKEN=` no `.env`.

### 2. Subir o container

```bash
docker compose up -d --build
```

A partir daí ele acompanha o log em tempo real (`tail`) e registra
automaticamente toda nova partida que você jogar.

### 3. Importar histórico de partidas passadas (opcional, uma vez)

```bash
docker compose run --rm tracker python main.py --history
```

Lê o `Player.log` inteiro do início e importa todas as partidas já
registradas nele (o arquivo é rotacionado pelo Arena periodicamente, então
isso não pega *todo* o histórico desde sempre — só o que ainda está no log
atual).

## Verificar que está funcionando

```bash
docker logs -f mtga_tracker
```

Cada `MATCH_START`/`GAME_END` aparece no log do container e fica
disponível na UI do mtg-collection-manager, aba **Partidas**
(`GET /api/matches`).

## Rodar sem Docker

```bash
pip install --upgrade pip  # só stdlib, sem dependências externas
python main.py --api http://localhost:3001 --api-token <seu-token>
# ou para importar histórico:
python main.py --api http://localhost:3001 --api-token <seu-token> --history
```

Por padrão usa `%USERPROFILE%\AppData\LocalLow\Wizards Of The Coast\MTGA\Player.log`
— sobrescreva com `--log <caminho>` ou a variável de ambiente `LOG_PATH`.

## Arquivos

| Arquivo | Função |
|---|---|
| `log_reader.py` | Segue o `Player.log` (`tail` ou leitura completa) e extrai os blocos JSON |
| `parser.py` | Interpreta cada bloco (estado da partida, vida, fases, MATCH_START/GAME_END) |
| `card_db.py` | Mapeamento `arena_id → nome` (via API, público) e chamadas HTTP autenticadas (`API_TOKEN`) para `/api/matches` |
| `formatter.py` | Formata eventos para impressão colorida no terminal |
| `main.py` | Loop principal — liga tudo |

## Limitações conhecidas

- A Wizards remove campos do log periodicamente entre patches — se algo
  parar de funcionar, o primeiro lugar a checar é se a estrutura do bloco
  JSON mudou (compare com `parser.py`).
- Detecção de deck por overlap de `arena_id` só funciona para decks
  marcados `is_active=1` no banco.
