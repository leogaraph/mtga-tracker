import json
import os
import re
import time

HEADER = "[UnityCrossThreadLogger]"
TS_RE = re.compile(r"^(\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2})")


def tail_log(path):
    """Segue o Player.log a partir do final, yield linha a linha."""
    while not os.path.exists(path):
        time.sleep(5)
    f = open(path, encoding="utf-8-sig")
    f.seek(0, os.SEEK_END)
    while True:
        line = f.readline()
        if not line:
            time.sleep(0.2)
            continue
        yield line


def read_log(path):
    """Lê o Player.log inteiro do início ao fim, yield linha a linha (sem seguir)."""
    with open(path, encoding="utf-8-sig") as f:
        for line in f:
            yield line


def extract_json_blocks(lines):
    """Acumula linhas entre headers [UnityCrossThreadLogger] e tenta parsear
    o bloco como JSON. Blocos sem '{' ou com JSON inválido são descartados."""
    buf = ""
    for line in lines:
        if line.startswith(HEADER):
            block = _try_parse(buf)
            if block is not None:
                yield block
            buf = line[len(HEADER):]
        else:
            buf += line
    block = _try_parse(buf)
    if block is not None:
        yield block


def _try_parse(buf):
    start = buf.find("{")
    if start == -1:
        return None
    try:
        block = json.loads(buf[start:])
    except ValueError:
        return None
    if isinstance(block, dict):
        m = TS_RE.match(buf)
        block["_ts"] = m.group(1) if m else None
    return block
