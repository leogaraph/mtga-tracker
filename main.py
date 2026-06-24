import argparse
import datetime
import os

from card_db import load_card_map, post_log, post_match_end, post_match_start
from formatter import format_event
from log_reader import extract_json_blocks, read_log, tail_log
from parser import process_block

DEFAULT_LOG = os.environ.get("LOG_PATH") or os.path.expandvars(
    r"%USERPROFILE%\AppData\LocalLow\Wizards Of The Coast\MTGA\Player.log"
)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", default=DEFAULT_LOG, help="Caminho do Player.log")
    ap.add_argument("--api", default=os.environ.get("API_URL", "http://localhost:3001"), help="URL do mtg_api")
    ap.add_argument("--api-token", default=os.environ.get("API_TOKEN"), help="Token de API (gere com POST /api/auth/api-token, ver README) — necessario para registrar partidas, que agora sao por usuario")
    ap.add_argument("--save", action="store_true", help="Salva eventos em arena_log_YYYY-MM-DD.txt")
    ap.add_argument("--history", action="store_true", help="Le o Player.log inteiro do inicio (importa partidas passadas) e sai")
    args = ap.parse_args()

    if not args.api_token:
        print("[!] API_TOKEN nao configurado — partidas serao detectadas mas NAO registradas na API.")
        print("    Gere um token com POST /api/auth/api-token e configure API_TOKEN no .env (ver README).")

    card_map = load_card_map(args.api, args.api_token)
    state = {"match_id": "", "turn": 0, "phase": "", "players": {}, "objects": {}, "zones": {}}

    out = None
    if args.save:
        out = open(f"arena_log_{datetime.date.today()}.txt", "a", encoding="utf-8")

    lines = read_log(args.log) if args.history else tail_log(args.log)

    if args.history:
        post_log(args.api, "Sincronização iniciada: lendo Player.log...", args.api_token)

    api_match_id = None
    for block in extract_json_blocks(lines):
        for event in process_block(block, state, card_map):
            if args.history and event[2] not in ("MATCH_START", "GAME_END"):
                continue
            line = format_event(event)
            print(line)
            if out:
                out.write(line + "\n")
                out.flush()
            if event[2] == "MATCH_START":
                api_match_id = post_match_start(args.api, state, args.api_token)
                if args.history:
                    post_log(args.api, line, args.api_token)
            elif event[2] == "GAME_END":
                post_match_end(args.api, api_match_id, state, state.get("result", "draw"), args.api_token)
                if args.history:
                    post_log(args.api, line, args.api_token)

    if args.history:
        post_log(args.api, "Sincronização concluída.", args.api_token)


if __name__ == "__main__":
    main()
