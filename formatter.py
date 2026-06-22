RESET = "\033[0m"

COLORS = {
    "MATCH_START": "\033[1;33m",  # amarelo bold
    "GAME_END": "\033[1;33m",     # amarelo bold
    "PLAY": "\033[32m",           # verde
    "DRAW": "\033[90m",           # cinza
    "LIFE": "\033[31m",           # vermelho
    "PHASE": "\033[36m",          # ciano
    "DAMAGE": "\033[31m",         # vermelho
}


def format_event(event):
    turn, phase, event_type, description = event
    color = COLORS.get(event_type, "")
    if turn or phase:
        tag = f"T{turn} {phase}".strip()
    else:
        tag = event_type
    return f"{color}[{tag:<10}] {description}{RESET}"
