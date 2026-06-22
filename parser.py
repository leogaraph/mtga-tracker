CATEGORY_EVENTS = {
    "Draw": "DRAW",
    "PlayLand": "PLAY",
    "CastSpell": "PLAY",
}


def get_detail(details, key):
    for d in details or []:
        if d.get("key") == key:
            for vk, v in d.items():
                if vk.startswith("value"):
                    return v[0]
    return None


def _player_name(state, seat_id):
    return state["players"].get(seat_id, {}).get("name", f"Jogador {seat_id}")


def _card_name(state, card_map, instance_id):
    grp_id = state["objects"].get(instance_id, {}).get("grpId")
    return card_map.get(grp_id, f"#{grp_id}")


def _target_name(state, card_map, target_id):
    if target_id in state["players"]:
        return _player_name(state, target_id)
    return _card_name(state, card_map, target_id)


def _process_annotation(ann, state, card_map):
    ann_type = (ann.get("type") or [""])[0]
    details = ann.get("details", [])
    affected = ann.get("affectedIds") or []
    turn, phase = state["turn"], state["phase"]

    if ann_type == "AnnotationType_ZoneTransfer" and affected:
        event_type = CATEGORY_EVENTS.get(get_detail(details, "category"))
        if not event_type:
            return []
        instance_id = affected[0]
        owner = state["objects"].get(instance_id, {}).get("ownerSeatId")
        if not owner:
            zone_dest = get_detail(details, "zone_dest")
            owner = state["zones"].get(zone_dest, {}).get("ownerSeatId", 0)
        player = _player_name(state, owner)
        if event_type == "DRAW":
            return [(turn, phase, "DRAW", f"{player} comprou carta")]
        card = _card_name(state, card_map, instance_id)
        return [(turn, phase, "PLAY", f"{player} jogou: {card}")]

    if ann_type == "AnnotationType_DamageDealt" and affected:
        amount = get_detail(details, "damage")
        targets = ", ".join(_target_name(state, card_map, t) for t in affected)
        return [(turn, phase, "DAMAGE", f"{targets} sofreu {amount} de dano")]

    return []


def _apply_game_state_message(gsm, state, card_map):
    events = []

    turn_info = gsm.get("turnInfo", {})
    if "turnNumber" in turn_info:
        state["turn"] = turn_info["turnNumber"]
    new_phase = turn_info.get("phase")
    if new_phase:
        new_phase = new_phase.replace("Phase_", "")
        if new_phase != state["phase"]:
            state["phase"] = new_phase
            active = _player_name(state, turn_info.get("activePlayer", 0))
            events.append((state["turn"], state["phase"], "PHASE", f"{active} — {state['phase']}"))

    if state.get("on_play") is None and state["turn"] == 1 and "activePlayer" in turn_info:
        state["on_play"] = turn_info["activePlayer"] == state.get("my_seat")

    for p in gsm.get("players", []):
        seat = p.get("systemSeatNumber")
        player = state["players"].get(seat)
        if player is None:
            continue
        new_life = p.get("lifeTotal")
        old_life = player.get("life")
        if new_life is not None and old_life is not None and new_life != old_life:
            events.append((state["turn"], state["phase"], "LIFE",
                            f"{player['name']}: {old_life} -> {new_life} ({new_life - old_life:+d})"))
        if new_life is not None:
            player["life"] = new_life

    for obj in gsm.get("gameObjects", []):
        instance_id = obj.get("instanceId")
        if instance_id is not None:
            state["objects"][instance_id] = {
                "grpId": obj.get("grpId"),
                "zoneId": obj.get("zoneId"),
                "ownerSeatId": obj.get("ownerSeatId"),
            }

    for zone in gsm.get("zones", []):
        zone_id = zone.get("zoneId")
        if zone_id is not None:
            state["zones"][zone_id] = {"ownerSeatId": zone.get("ownerSeatId")}

    for instance_id in gsm.get("diffDeletedInstanceIds", []):
        state["objects"].pop(instance_id, None)

    for ann in gsm.get("annotations", []):
        events += _process_annotation(ann, state, card_map)

    return events


def process_block(block, state, card_map):
    """Roteador principal. Atualiza `state` in-place e retorna lista de
    eventos (turn, phase, event_type, description). Tolera campos ausentes."""
    events = []

    try:
        state["client_id"] = block["authenticateResponse"]["clientId"]
    except (KeyError, TypeError):
        pass

    try:
        state["event_name"] = block["Course"]["InternalEventName"]
    except (KeyError, TypeError):
        pass

    try:
        main_deck = block["CourseDeck"]["MainDeck"]
        state["deck_arena_ids"] = list({c["cardId"] for c in main_deck})
    except (KeyError, TypeError):
        pass

    try:
        command_zone = block["CourseDeck"]["CommandZone"]
        commander_id = command_zone[0]["cardId"]
        state["commander_name"] = card_map.get(commander_id, f"#{commander_id}")
    except (KeyError, IndexError, TypeError):
        pass

    try:
        room = block["matchGameRoomStateChangedEvent"]["gameRoomInfo"]
        state_type = room.get("stateType")

        if state_type == "MatchGameRoomStateType_Playing":
            cfg = room["gameRoomConfig"]
            state["match_id"] = cfg.get("matchId", "")
            state["started_at"] = block.get("_ts")
            state["on_play"] = None
            state["players"] = {
                p["systemSeatId"]: {
                    "name": p.get("playerName", "").strip(),
                    "life": None,
                    "team_id": p.get("teamId"),
                    "user_id": p.get("userId"),
                }
                for p in cfg.get("reservedPlayers", [])
            }
            my_seat = next((s for s, p in state["players"].items() if p["user_id"] == state.get("client_id")), None)
            state["my_seat"] = my_seat
            state["my_team_id"] = state["players"].get(my_seat, {}).get("team_id")
            state["opponent_name"] = next(
                (p["name"] for s, p in state["players"].items() if s != my_seat), ""
            )
            names = " vs ".join(p["name"] for p in state["players"].values())
            events.append((0, "", "MATCH_START", f"Partida iniciada: {names}"))

        elif state_type == "MatchGameRoomStateType_MatchCompleted":
            state["ended_at"] = block.get("_ts")
            state["total_turns"] = state["turn"]
            result = room.get("finalMatchResult", {})
            for r in result.get("resultList", []):
                if r.get("scope") == "MatchScope_Match":
                    winning_team = r.get("winningTeamId")
                    my_team = state.get("my_team_id")
                    if my_team is None:
                        state["result"] = "draw"
                    else:
                        state["result"] = "win" if winning_team == my_team else "loss"
                    events.append((
                        state["turn"], state["phase"], "GAME_END",
                        f"Partida encerrada — resultado: {state['result']} ({r.get('reason', '')})",
                    ))
    except (KeyError, IndexError, TypeError):
        pass

    try:
        for msg in block["greToClientEvent"]["greToClientMessages"]:
            if msg.get("type") in ("GREMessageType_GameStateMessage", "GREMessageType_QueuedGameStateMessage"):
                events += _apply_game_state_message(msg.get("gameStateMessage", {}), state, card_map)
    except (KeyError, IndexError, TypeError):
        pass

    return events
