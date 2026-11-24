"""Pustaka klasifikasi (bagian pustaka dari 02_preprocess.py lama, baris 1-241, TIDAK diubah). Dipakai oleh 02_preprocess.py.

PHASE 2 - Preprocessing: klasifikasi event + status timestamp + kolom turunan.

Streaming (csv stdlib), memori konstan. Tidak ada dedup, tidak ada filter, tidak ada baris dibuang.
Aturan klasifikasi = tabel data src/event_rules.csv (first-match). Rancangan: reports/phase2a/PHASE2A_DESIGN.md.

    python3 src/02_preprocess.py --scenario 1 --max-rows 50000     # sampel -> *_sample50000.*
    python3 src/02_preprocess.py --scenario all                    # penuh
"""
import calendar, csv, hashlib, re, sys
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config
import evtx_fields
import search_engines

OUT_COLUMNS = ["row_id", "datetime_raw", "timestamp_clean", "timestamp_status", "timestamp_desc", "event_type", "rule_id",
               "source", "source_long", "parser", "url", "host", "page_title", "app_name", "registry_key", "file_path",
               "message", "display_name"]
VERBATIM = ["timestamp_desc", "source", "source_long", "parser", "message", "display_name"]   # harus identik dengan raw
DERIVED = ["url", "host", "page_title", "app_name", "registry_key", "file_path"]
UNCLASSIFIED = "Unclassified"
TS_STATUSES = ["valid", "zero_date", "filetime_zero", "not_a_time", "out_of_range", "unparseable"]

# ---------------------------------------------------------------- timestamp
ISO_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(\.\d+)?(Z|[+-]\d{2}:\d{2})?$")
RANGE_LO, RANGE_HI = "1970-01-01T00:00:00", "2106-02-07T06:28:15"   # [0, 2^32-1) detik sejak epoch; batas atas = sentinel 0xFFFFFFFF


def normalize_dt(dt: str) -> str:
    """Pemisah tanggal-waktu spasi (file events S1) -> 'T' (posisi ke-11). Hanya untuk status dan timestamp_clean;
    datetime_raw tidak pernah diubah. Pada input ber-'T' (timeline.csv) fungsi ini identitas."""
    return dt[:10] + "T" + dt[11:] if len(dt) > 10 and dt[10] == " " else dt


def timestamp_status(dt: str, ts_desc: str) -> str:
    dt = normalize_dt(dt)
    m = ISO_RE.match(dt)
    if not m:
        return "unparseable"
    if dt.startswith("0000-00-00"):
        return "zero_date"
    if dt.startswith("1601-01-01T00:00:00"):
        return "filetime_zero"
    y, mo, d, hh, mi, ss = (int(m.group(i)) for i in range(1, 7))
    if y < 1 or not 1 <= mo <= 12 or hh > 23 or mi > 59 or ss > 59 or not 1 <= d <= calendar.monthrange(y, mo)[1]:
        return "unparseable"
    if ts_desc == "Not a time":
        return "not_a_time"
    if not (RANGE_LO <= dt < RANGE_HI):
        return "out_of_range"
    return "valid"


# ---------------------------------------------------------------- ekstraksi kolom turunan
SCHEMES = ("http://", "https://", "file://")
# Phase 2.2: deteksi pencarian dipindah ke src/search_engines.py (pemetaan parameter per mesin berdasarkan hostname)
RE = {
    "chrome_title": re.compile(r"^\S+ \((.*?)\) \[count:"),
    "bookmark": re.compile(r"^Bookmark URL (.*?) \(((?:https?|file)://\S*)\)"),          # format Plaso: Bookmark URL <judul> (<url>) visit count N
    "msie_url": re.compile(r"^URL: (?::\d+: [^@\s]*@)?(\S+)"),                          # buang awalan ':YYYYMMDDYYYYMMDD: User@'
    "prefetch2": re.compile(r"^Prefetch \[(.+?)\] was executed"),
    "typed_url": re.compile(r"\burl\d+: (\S+)"),
    "prefetch": re.compile(r"Origin: (.+?)-[0-9A-Fa-f]{8}\.pf"),
    "bam": re.compile(r"^(.*?) \[S-1-"),
    "userassist": re.compile(r"Value name: (.*?) Count: "),
    "pca": re.compile(r"^\[(.+?)\] was executed"),
    "amcache": re.compile(r"^path: (.*?) [a-z_]+: "),
    "regkey": re.compile(r"^\[(.*?)\]"),
    "filestat": re.compile(r"^\w+:(.*?)(?: Type: \S+)?\Z", re.S),
    "usn": re.compile(r"^(.*?) File reference:"),
    "shell": re.compile(r"Shell item path: (.*?)(?: Origin:|\Z)", re.S),
    "lnk": re.compile(r"env location: (.*?)(?: Working dir:| Icon location:|\Z)", re.S),
}
_PARSER_RE = {
    "chrome_hist": re.compile(r"^sqlite/chrome_\d+_history$"), "cookie": re.compile(r"^sqlite/(chrome|firefox)_\d+_cookies$"),
    "lnk": re.compile(r"^(custom_destinations/|olecf/olecf_automatic_destinations/)?lnk$"),
}
_EXACT = {"sqlite/firefox_history": "ff_hist", "chrome_cache": "chrome_cache", "esedb/msie_webcache": "msie",
          "winreg/windows_typed_urls": "typed_urls", "prefetch": "prefetch", "winreg/bam": "bam", "winreg/userassist": "userassist",
          "winpca_dic": "pca", "winreg/amcache": "amcache", "filestat": "filestat", "usnjrnl": "usn"}
_FAMILY = {}


def family(parser: str) -> frozenset:
    f = _FAMILY.get(parser)
    if f is None:
        tags = set()
        if parser in _EXACT: tags.add(_EXACT[parser])
        for k, rx in _PARSER_RE.items():
            if rx.search(parser): tags.add(k)
        if parser.endswith("/shell_items"): tags.add("shell")
        elif parser.startswith("winreg/"): tags.add("registry")
        f = _FAMILY[parser] = frozenset(tags)
    return f


def _first_token_url(message: str) -> str:
    i = message.find(" ")
    t = message if i < 0 else message[:i]
    return t if t.startswith(SCHEMES) else ""


def extract_url(parser: str, message: str) -> str:
    fam = family(parser)
    if not fam:
        return ""
    if "chrome_hist" in fam or "cookie" in fam:
        return _first_token_url(message)
    if "ff_hist" in fam:
        m = RE["bookmark"].match(message)
        return m.group(2) if m else _first_token_url(message)
    if "chrome_cache" in fam:
        if not message.startswith("Original URL: "): return ""
        t = message[14:].split()
        if t and t[0].startswith(SCHEMES): return t[0]
        return t[-1] if t and "_dk_" in t[0] and t[-1].startswith(SCHEMES) else ""     # kunci cache ganda: URL asli = token terakhir
    if "msie" in fam:
        m = RE["msie_url"].match(message)
        return m.group(1) if m and m.group(1).startswith(SCHEMES) else ""
    if "typed_urls" in fam:
        m = RE["typed_url"].search(message); return m.group(1) if m else ""
    return ""


def host_of(url: str) -> str:
    if not url:
        return ""
    try:
        h = urlsplit(url).hostname
    except ValueError:
        return ""
    return h.lower() if h else ""


def _basename(p: str) -> str:
    return re.split(r"[\\/]", p)[-1]


def extract_fields(parser: str, message: str) -> tuple:
    """-> (url, host, page_title, app_name, registry_key, file_path). Kosong bila pola tidak cocok (tidak menebak)."""
    if parser == "winevtx": return ("", "", "", evtx_fields.evtx_app_name(message), "", "")      # Phase 2.3 (src/evtx_fields.py)
    fam = family(parser)
    if not fam:
        return ("", "", "", "", "", "")
    url = extract_url(parser, message); title = app = key = path = ""
    if "chrome_hist" in fam:
        m = RE["chrome_title"].match(message); title = m.group(1) if m else ""
    if "ff_hist" in fam:
        m = RE["bookmark"].match(message); title = m.group(1) if m else ""
    if "prefetch" in fam:
        m = RE["prefetch"].search(message) or RE["prefetch2"].match(message); app = m.group(1) if m else ""
    if "bam" in fam:
        m = RE["bam"].match(message); app = m.group(1) if m else ""
    if "userassist" in fam:
        m = RE["userassist"].search(message); app = m.group(1) if m else ""
    if "pca" in fam:
        m = RE["pca"].match(message)
        if m: path = m.group(1); app = _basename(path)
    if "amcache" in fam:
        m = RE["amcache"].match(message)
        if m: path = m.group(1); app = _basename(path)
    if "registry" in fam or "typed_urls" in fam:
        m = RE["regkey"].match(message); key = m.group(1) if m else ""
    if "filestat" in fam:
        m = RE["filestat"].match(message); path = m.group(1) if m else ""
    if "usn" in fam:
        m = RE["usn"].match(message); path = m.group(1) if m else ""
    if "shell" in fam:
        m = RE["shell"].search(message); path = m.group(1) if m else ""
    if "lnk" in fam:
        m = RE["lnk"].search(message); path = m.group(1) if m else ""
    return (url, host_of(url), title, app, key, path)


# ---------------------------------------------------------------- classifier (tabel data, first-match)
USN_RE = re.compile(r"USN_REASON_([A-Z_]+)")
EVTX_ID, EVTX_SRC = evtx_fields.EVTX_ID, evtx_fields.EVTX_SRC
_KINDS = {"exact", "prefix", "suffix", "regex"}
_CONDS = {"none", "ts_desc_in", "ts_desc_in+url_search", "usn_any", "evtx_pair"}


def is_search(parser: str, message: str) -> bool:
    url = extract_url(parser, message)
    return bool(url) and search_engines.is_search_url(url)


class Rule:
    def __init__(self, d: dict):
        self.rule_id, self.event_type = d["rule_id"], d["event_type"]
        kind, pat = d["parser_kind"], d["parser_pattern"]
        if kind not in _KINDS: raise ValueError(f"{self.rule_id}: parser_kind {kind!r}")
        self._pm = {"exact": lambda s: s == pat, "prefix": lambda s: s.startswith(pat), "suffix": lambda s: s.endswith(pat),
                    "regex": re.compile(pat).search}[kind]
        self.cond_kind, val = d["cond_kind"], d["cond_value"]
        if self.cond_kind not in _CONDS: raise ValueError(f"{self.rule_id}: cond_kind {self.cond_kind!r}")
        self.values = frozenset(val.split("|")) if self.cond_kind in ("ts_desc_in", "ts_desc_in+url_search", "usn_any") else frozenset()
        if self.cond_kind == "evtx_pair":
            self.provider, ids = val.rsplit(":", 1); self.ids = frozenset(ids.split(","))

    def parser_match(self, parser): return bool(self._pm(parser))

    def cond(self, parser, ts_desc, message) -> bool:
        k = self.cond_kind
        if k == "none": return True
        if k == "ts_desc_in": return ts_desc in self.values
        if k == "ts_desc_in+url_search": return ts_desc in self.values and is_search(parser, message)
        if k == "usn_any": return bool(self.values.intersection(USN_RE.findall(message)))
        mi, ms = EVTX_ID.match(message), EVTX_SRC.search(message)          # evtx_pair
        return bool(mi and ms and ms.group(1) == self.provider and mi.group(1) in self.ids)


class Classifier:
    def __init__(self, path=None):
        with open(path or config.RULES_PATH, newline="", encoding="utf-8") as f:
            self.rules = [Rule(d) for d in csv.DictReader(f)]
        ids = [r.rule_id for r in self.rules]
        if len(ids) != len(set(ids)): raise ValueError("rule_id tidak unik")
        self.event_types = {r.event_type for r in self.rules} | {UNCLASSIFIED}
        self.rule_ids = set(ids)
        self._cache = {}

    def classify(self, parser, ts_desc, message):
        rs = self._cache.get(parser)
        if rs is None:
            rs = self._cache[parser] = [r for r in self.rules if r.parser_match(parser)]
        for r in rs:
            if r.cond(parser, ts_desc, message):
                return r.event_type, r.rule_id
        return UNCLASSIFIED, ""


# ---------------------------------------------------------------- pipeline
def sha256_file(path: Path, block=1 << 24) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(block), b""): h.update(b)
    return h.hexdigest()

