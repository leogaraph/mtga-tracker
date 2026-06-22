# MTGA Log Parser — Plano (v2: Docker + mínimo de código)

Baseado em [`raw/mtga-log-parser-spec.md`](../../raw/mtga-log-parser-spec.md), revisado para:
- rodar em Docker, sem mexer no `mtg-collection-manager` existente
- reusar o banco de cartas que já existe em `mtg_collection` (via API), em vez de baixar/montar `cards_slim.json` do Scryfall
- zero (ou quase zero) classes — `GameState` é um `dict` comum
- funções pequenas e diretas, só stdlib (`socket`/`urllib`, `json`, `re`, `time`)

---

## 1. Reuso do banco existente (em vez do Scryfall bulk)

A tabela `cards` do `mtg_collection` já tem `arena_id` e `name`
([schema.sql](../mtg-collection-manager/db/schema.sql)). Em vez de baixar o
bulk do Scryfall e manter `cards_slim.json`, o tracker pede esse mapeamento
pronto à API que já roda (`mtg_api`, porta 3001).

**Mudança mínima e aditiva no `mtg-collection-manager/api/index.js`:**
um novo endpoint, só leitura, ~6 linhas:

```js
// GET /api/cards/arena-map → { "12345": "Lightning Bolt", ... }
app.get('/api/cards/arena-map', asyncHandler(async (req, res) => {
  const [rows] = await pool.query(
    'SELECT arena_id, name FROM cards WHERE arena_id IS NOT NULL'
  )
  const map = {}
  for (const r of rows) map[r.arena_id] = r.name
  res.json(map)
}))
```

Não altera nenhuma rota existente. Se a API não estiver no ar, o tracker
cai num fallback (mostra `#<grpId>` no lugar do nome) — sem quebrar.

`card_db.py` fica então com **uma função**:

```python
def load_card_map(api_url: str) -> dict[int, str]:
    # GET {api_url}/api/cards/arena-map via urllib, converte chaves para int
    # em caso de erro de rede: retorna {} e o formatter usa fallback "#grpId"
```

---

## 2. Estrutura de arquivos (reduzida)

```
mtga-tracker/
├── docker-compose.yml   # novo serviço, junta a rede do mtg-collection-manager
├── Dockerfile
├── main.py              # loop principal
├── log_reader.py        # tail_log, extract_json_blocks
├── parser.py            # process_block + apply_state (tudo num arquivo)
├── card_db.py           # load_card_map (1 função)
└── formatter.py         # format_event (1 função)
```

Sem `state.py`. Estado = um `dict` único criado em `main.py`:

```python
state = {
    "turn": 0, "phase": "", "active_player": 0,
    "players": {},   # seatId -> {"name": str, "life": int}
    "objects": {},   # instanceId -> {"grpId": int, "zoneId": int, "ownerSeatId": int}
}
```

`GameEvent` também não vira classe — é uma tupla simples
`(turn, phase, event_type, description)` consumida direto pelo `formatter`.

---

## 3. Docker — não derruba nada existente

Compose **separado**, na pasta `mtga-tracker/`, conectado por **rede externa**
ao compose do `mtg-collection-manager` (que continua rodando do jeito que está):

```yaml
# mtga-tracker/docker-compose.yml
services:
  tracker:
    build: .
    container_name: mtga_tracker
    restart: unless-stopped
    environment:
      CARD_API_URL: http://mtg_api:3001
    volumes:
      # Player.log do Windows montado read-only dentro do container
      - "${MTGA_LOG_DIR}:/log:ro"
      # saída opcional do --save
      - ./output:/output
    networks:
      - mtg_default

networks:
  mtg_default:
    external: true
    name: mtg-collection-manager_default   # confirmar nome real com `docker network ls`
```

- `MTGA_LOG_DIR` = pasta `...AppData\LocalLow\Wizards Of The Coast\MTGA` no host (Docker Desktop monta paths Windows direto).
- `tracker` enxerga `mtg_api` pelo nome do container porque entra na mesma rede — **nenhuma porta nova exposta no host**, nenhum serviço existente é alterado/reiniciado.
- Se a rede do outro projeto tiver outro nome, é só ajustar o `name:` — sem impacto no projeto original.

`Dockerfile` é trivial (Python slim, copia os `.py`, `CMD ["python", "main.py"]`).

---

## 4. Pipeline (sem mudança de fundo, só simplificado)

```
tail_log()  →  extract_json_blocks()  →  process_block(block, state, card_map)
                                              │
                                   atualiza dict `state` in-place
                                   retorna list[tuple] de eventos
                                              │
                                        format_event() → print / append --save
```

`process_block` concentra tudo (substitui `apply_game_state_message` +
`process_annotations` do spec original) em uma função com `if/elif` por tipo
de mensagem, com `try/except (KeyError, IndexError)` em cada ramo — mantém a
recomendação do spec de tolerar campos ausentes, sem precisar de helpers
extras (`get_detail` vira `dict.get` direto).

---

## 5. Itens em aberto

- [ ] Confirmar nome real da rede docker do `mtg-collection-manager` (`docker network ls` com o stack rodando)
- [ ] Confirmar path exato de `Player.log` no host (variável `MTGA_LOG_DIR`)
- [ ] Confirmar "Detailed Logs (Plugin Support)" ativo no Arena
- [ ] Mapeamento `zone_src`/`zone_dest` → PLAY/DRAW (igual ao plano anterior — fica para quando codarmos o `parser.py`)

---

## 6. Status

- [ ] Endpoint `/api/cards/arena-map` na API existente
- [ ] `card_db.py` (`load_card_map`)
- [ ] `log_reader.py` (`tail_log`, `extract_json_blocks`)
- [ ] `parser.py` (`process_block`, MATCH_START/GAME_END → turno/vida → jogadas/dano)
- [ ] `formatter.py` (`format_event`)
- [ ] `main.py` + `--save`
- [ ] `Dockerfile` + `docker-compose.yml`
