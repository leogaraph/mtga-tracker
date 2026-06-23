import json
import urllib.request
from datetime import datetime, timezone


def _parse_log_ts(ts):
    """Converte 'dd/mm/yyyy HH:MM:SS' (timestamp do Player.log) para ISO 8601 UTC.
    Sem timestamp, usa o horário atual."""
    if not ts:
        return datetime.now(timezone.utc).isoformat()
    return datetime.strptime(ts, "%d/%m/%Y %H:%M:%S").isoformat()


def load_card_map(api_url):
    """Busca {arena_id: nome} do mtg_api existente. Endpoint publico (sem
    auth) — catalogo global de cartas, nao depende de usuario. Em caso de
    erro de rede/endpoint ausente, retorna {} (formatter cai no fallback
    #grpId)."""
    try:
        with urllib.request.urlopen(f"{api_url}/api/cards/arena-map", timeout=5) as resp:
            data = json.load(resp)
        return {int(k): v for k, v in data.items()}
    except Exception:
        return {}


def _request(url, payload, method, api_token=None):
    try:
        headers = {"Content-Type": "application/json"}
        if api_token:
            headers["Authorization"] = f"Bearer {api_token}"
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method=method,
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        if e.code == 401:
            print("[!] API_TOKEN ausente/invalido — partida nao registrada. "
                  "Gere um token com POST /api/auth/api-token e configure API_TOKEN no .env.")
        return {}
    except Exception:
        return {}


def post_match_start(api_url, state, api_token=None):
    """Registra início de partida. Retorna o id da partida no banco (ou None)."""
    payload = {
        "arena_match_id": state.get("match_id", ""),
        "opponent_name": state.get("opponent_name", ""),
        "started_at": _parse_log_ts(state.get("started_at")),
        "deck_arena_ids": state.get("deck_arena_ids", []),
        "event_name": state.get("event_name", ""),
        "commander_name": state.get("commander_name", ""),
    }
    return _request(f"{api_url}/api/matches", payload, "POST", api_token).get("id")


def post_match_end(api_url, match_db_id, state, result, api_token=None):
    """Atualiza resultado/encerramento da partida."""
    if not match_db_id:
        return
    payload = {
        "result": result,
        "ended_at": _parse_log_ts(state.get("ended_at")),
        "total_turns": state.get("total_turns"),
        "on_play": state.get("on_play"),
    }
    _request(f"{api_url}/api/matches/{match_db_id}", payload, "PATCH", api_token)


def post_log(api_url, message):
    """Registra uma linha de progresso, exibida na UI ao clicar em 'Sincronizar'.
    Endpoint publico (sem auth) — so texto de log, sem dado sensivel."""
    _request(f"{api_url}/api/sync-log", {"message": message}, "POST")
