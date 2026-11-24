"""Phase 2.3 - bidang turunan dari event Windows EVTX (winevtx): nama proses dari Strings[0] untuk (provider, Event ID) tertentu.
Dipisah dari 02_preprocess.py agar modul klasifikasi tetap bebas literal nama berkas (tes statis test_phase2). Ekstensi executable adalah SATU konstanta di sini
(pola generik yang diwajibkan spesifikasi), bukan bukti spesifik skenario. Pola tidak cocok -> kosong; tidak menebak."""
import ast, re

EVTX_ID = re.compile(r"^\[(\d+) /")                     # Event ID pada awal pesan
EVTX_SRC = re.compile(r"Source Name: (.*?) Strings:")    # provider
EVTX_APP_PAIRS = {("Microsoft-Windows-Shell-Core", "9707")}      # (provider, Event ID) yang `Strings[0]`-nya adalah baris perintah proses
EXECUTABLE_SUFFIX = ".exe"
_STRINGS = re.compile(r"Strings: (\[.*\]) Computer Name:", re.S)
_HEAD = re.compile(r"^\s*\"?((?:[A-Za-z]:\\|\\\\)?[^\"\r\n]*?" + re.escape(EXECUTABLE_SUFFIX) + r")(?=[\"\s]|$)", re.I)


def evtx_app_name(message: str) -> str:
    """Teks Strings[0] sampai dan termasuk ekstensi executable (huruf asli), tanpa tanda kutip dan argumen sesudahnya; path penuh bila ada. Kosong bila pola tidak cocok."""
    mi, ms = EVTX_ID.match(message), EVTX_SRC.search(message)
    if not (mi and ms and (ms.group(1), mi.group(1)) in EVTX_APP_PAIRS): return ""
    m = _STRINGS.search(message)
    if not m: return ""
    try: items = ast.literal_eval(m.group(1))
    except (ValueError, SyntaxError): return ""
    if not isinstance(items, list) or not items or not isinstance(items[0], str): return ""
    h = _HEAD.match(items[0]); return h.group(1) if h else ""
