# Integração Arena Tracker ↔ MTG Collection Manager

## Sobreposições encontradas

| O que já existe | Onde | Como aproveitar |
|---|---|---|
| `cards.arena_id` | `db/schema.sql:25` | já cobre o lookup grpId → nome (endpoint `/api/cards/arena-map`, do plano v2) |
| `decks.platform ENUM('arena','mtgo','physical','all')` | `db/schema.sql:213` | decks marcados `'arena'` são candidatos a "qual deck eu joguei" |
| `deck_cards` (deck_id, card_id, board) | `db/schema.sql:221-230` | dá o **conjunto de arena_ids do deck** → permite detectar qual deck foi jogado comparando com a hand/deck list que o Arena manda no início da partida |
| API Express modular, mysql2/promise pool | `api/index.js` | só somar rotas novas, sem mexer nas existentes |
| UI React com páginas (`DecksList`, `DeckView`, `CollectionView`) | `ui/src/pages/` | somar uma 4ª página "Partidas" |
| **Não existe**: tabela de partidas/histórico, eventos de jogo, websocket | — | é o que falta criar |

Conclusão: a peça que falta é **histórico de partidas + resultado por deck**.
Log de eventos turno-a-turno (o que o `mtga-tracker` imprime ao vivo) é
interessante, mas **não precisa ir pro banco** — pode ficar só no
console/arquivo `--save` do tracker, sem custo de armazenamento.
O banco guarda só o **resumo** de cada partida.

---

## Arquitetura proposta

```
Player.log (host)
     │
     ▼
mtga_tracker (container novo, sem alterar nada existente)
     │  - imprime eventos ao vivo (turno/fase/vida/jogadas) -- como já planejado
     │  - ao detectar MATCH_START → POST /api/matches
     │  - ao detectar GAME_END     → PATCH /api/matches/:id
     ▼
mtg_api (existente, +3 rotas novas)
     │
     ▼
mtg_collection (mysql, +1 tabela nova: matches)
     │
     ▼
mtg_ui (existente, +1 página: "Partidas")
```

Tudo aditivo: nenhuma rota, tabela, container ou variável existente muda.

---

## 1. Schema — uma tabela nova

```sql
-- db/schema.sql (append)
CREATE TABLE IF NOT EXISTS matches (
  id              INT AUTO_INCREMENT PRIMARY KEY,
  arena_match_id  VARCHAR(64) UNIQUE,         -- matchId do log, evita duplicar
  deck_id         INT NULL,                   -- FK decks.id, NULL se não detectado
  opponent_name   VARCHAR(128),
  started_at      DATETIME,
  ended_at        DATETIME NULL,
  result          ENUM('win','loss','draw','in_progress') DEFAULT 'in_progress',
  FOREIGN KEY (deck_id) REFERENCES decks(id)
);
```

Nada de `match_events` por enquanto — turno-a-turno fica no log local do
tracker (`--save`), não no MySQL. Se um dia quisermos replay/timeline no
banco, é fácil somar depois sem afetar o resto.

---

## 2. API — 3 rotas novas em `index.js`

```js
// POST /api/matches  { arena_match_id, opponent_name, started_at, deck_arena_ids }
// - tenta detectar deck_id: compara deck_arena_ids (set de arena_id da partida)
//   com deck_cards de decks WHERE platform='arena', pega o de maior overlap (>80%)
// - INSERT, retorna { id, deck_id }

// PATCH /api/matches/:id  { result, ended_at }
// - UPDATE simples

// GET /api/matches?deck_id=&limit=
// - histórico para a UI, com JOIN em decks pra trazer nome/cor do deck
```

Detecção de deck = uma query SQL (`GROUP BY deck_id`, conta interseção de
`arena_id`) + escolher o maior. Sem libs novas.

---

## 3. Tracker — o que muda no `mtga-tracker` (do PLAN.md v2)

- `main.py`: ao receber evento `MATCH_START`, faz `POST /api/matches`
  (inclui a lista de `arena_id` dos cards do deck do jogador, se o log
  tiver — ver nota abaixo). Guarda o `id` retornado.
- Ao receber `GAME_END`, faz `PATCH /api/matches/:id` com `result` e
  `ended_at`.
- Ambas chamadas via `urllib.request` (stdlib), igual `load_card_map`.
- Falha de rede na API → loga aviso e segue (não trava o tracker ao vivo).

**Nota sobre detecção de deck**: o Arena manda a deck list (grpIds) em
mensagens de `DeckSubmission`/`Event_Join` no log. Se essa mensagem não
aparecer ou não for confiável, fallback simples: `deck_id = null` e o
usuário associa manualmente depois na UI (dropdown "deck usado" na tela de
Partidas). Não bloqueia o resto.

---

## 4. UI — 1 página nova: "Partidas"

- `ui/src/pages/MatchesView.jsx`: tabela com data, deck, oponente,
  resultado (W/L/D), duração — busca de `GET /api/matches`.
- Em `DecksList.jsx`: badge opcional de win-rate por deck
  (`GET /api/decks/:id` já retorna stats; somar `wins`/`losses` agregados
  via `GET /api/matches?deck_id=`).
- Sem websocket/realtime no v1 — a UI só mostra histórico após o jogo
  terminar (refresh manual ou polling simples, igual `SyncButton.jsx` já
  faz com `/api/sync/progress`).

---

## 5. Ordem de implementação

1. Migration: adicionar tabela `matches` (script idempotente, não recria o DB)
2. API: rota `/api/cards/arena-map` (do plano v2) + 3 rotas de `matches`
3. Tracker: pipeline do PLAN.md v2 (fases 1–7) + chamadas POST/PATCH em MATCH_START/GAME_END
4. UI: página "Partidas" + badge de win-rate

## 6. Confirmado contra `Player.log` real (2026-06-10)

Inspecionei o `Player.log` do usuário e os 3 itens em aberto estão resolvidos:

- **`arena_match_id`**: `matchGameRoomStateChangedEvent.gameRoomInfo.gameRoomConfig.matchId`
  (ex: `"903d62fc-92b6-495b-a536-da601be938ba"`). Presente tanto no evento
  `stateType: "MatchGameRoomStateType_Playing"` (início) quanto no
  `"MatchGameRoomStateType_MatchCompleted"` (fim).

- **Resultado da partida**: o mesmo evento de fim traz
  `finalMatchResult.resultList`, com um item `scope: "MatchScope_Match"` e
  `winningTeamId`. Comparar com o `teamId` do jogador (presente no array
  `players`/`reservedPlayers` do evento `Playing`, junto com `playerName`)
  → dá `win`/`loss` direto, sem precisar do `gameInfo.stage` separado.
  (`gameInfo.stage == "GameStage_GameOver"` + `matchState ==
  "MatchState_MatchComplete"` também aparece, mas é redundante — usar o
  `matchGameRoomStateChangedEvent` como fonte única simplifica o
  `process_block`.)

- **Deck list (para detecção automática)**: aparece **antes** do match,
  num bloco com `"CourseDeckSummary"` + `"CourseDeck": { "MainDeck": [
  {"cardId": 75452, "quantity": 2}, ... ] }`. `cardId` = `arena_id`. O
  tracker guarda esse `MainDeck` (lista de `{cardId, quantity}`) em memória
  e envia como `deck_arena_ids` no `POST /api/matches` quando o
  `matchGameRoomStateChangedEvent` (Playing) chegar.

## 7. Em aberto

- [ ] Critério de overlap para detecção automática de deck (sugestão: 80%
      dos `cardId` do `MainDeck` precisam bater com `deck_cards.card_id`
      → `cards.arena_id` de um deck `platform='arena'`)
- [ ] Confirmar `playerName` do log bate com algum identificador salvo no
      `mtg_collection` (hoje não há — `opponent_name` fica só informativo)
