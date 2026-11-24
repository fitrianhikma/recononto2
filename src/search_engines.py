"""PHASE 2.2 - pemetaan parameter pencarian PER MESIN (berdasarkan hostname).

Sebelumnya himpunan kunci {q, query, p, text, wd} diterapkan ke semua mesin, sehingga URL pengalihan mesin pencari
(path /ck/a dengan parameter p=<hash>) terbaca sebagai pencarian dengan "kueri" berupa hash. Kini tiap mesin hanya
dihitung lewat kunci miliknya; kunci lain pada host yang sama diabaikan. Daftar mesin tidak berubah.
Dipakai bersama oleh 02_preprocess.py (deteksi) dan 03_build_rdf.py (ekstraksi kueri): satu sumber kebenaran.
"""
import re
from urllib.parse import parse_qs, urlsplit

ENGINE_PARAM = {"google": "q", "bing": "q", "duckduckgo": "q", "ecosia": "q", "yahoo": "p", "yandex": "text", "baidu": "wd"}
SEARCH_HOST = re.compile(r"(^|\.)(" + "|".join(ENGINE_PARAM) + r")\.[a-z.]+$")


def engine_of(url: str):
    """-> nama mesin (kunci ENGINE_PARAM) bila hostname URL adalah mesin pencari yang dikenal, selain itu None."""
    try:
        host = (urlsplit(url).hostname or "").lower()
    except ValueError:
        return None
    m = SEARCH_HOST.search(host)
    return m.group(2) if m else None


def search_query(url: str) -> str:
    """Nilai kueri pencarian menurut parameter milik mesin; "" bila bukan mesin dikenal / parameter tidak ada / kosong."""
    eng = engine_of(url)
    if not eng:
        return ""
    try:
        q = parse_qs(urlsplit(url).query)
    except ValueError:
        return ""
    vals = q.get(ENGINE_PARAM[eng])
    return vals[0] if vals and vals[0] else ""


def is_search_url(url: str) -> bool:
    """Benar bila hostname mesin dikenal DAN parameter miliknya ada pada query string (nilai boleh kosong, seperti perilaku lama)."""
    eng = engine_of(url)
    if not eng:
        return False
    try:
        return ENGINE_PARAM[eng] in parse_qs(urlsplit(url).query)
    except ValueError:
        return False
