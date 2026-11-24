"""Pembaca file resmi timeline/events/*.csv (Phase 2.1).

Menangani 3 cacat format resmi dan MELAPORKANNYA (tidak ada baris data yang hilang):
  1. header menyatu dengan baris data pertama      -> info['header_fused']
  2. header diulang sebagai baris data pertama     -> info['duplicate_header_row'] (baris itu BUKAN event)
  3. pemisah datetime spasi (S1)                   -> datetime_raw disimpan apa adanya (normalisasi hanya di 02_preprocess)
Jumlah field != 8 -> ValueError (tidak dibuang diam-diam).
"""
import csv, hashlib, io, re
from pathlib import Path

csv.field_size_limit(1 << 30)
COLS = ["datetime", "timestamp_desc", "source", "source_long", "message", "parser", "display_name", "tag"]
HEADER = ",".join(COLS)


def file_order_key(p) -> tuple:
    """Nama berawalan angka (mis. '10-xxx.csv') diurut numerik lebih dulu, lalu sisanya alfabet."""
    b = Path(p).name
    m = re.match(r"^(\d+)-", b)
    return (0, int(m.group(1)), b) if m else (1, 0, b)


def row_hash(cols) -> str:
    """SHA-1 dari 8 kolom mentah digabung \\x1f. Untuk pengelompokan duplikat; BUKAN untuk menghapus."""
    return hashlib.sha1("\x1f".join(cols).encode("utf-8", "surrogatepass")).hexdigest()


def read_events_file(path) -> tuple:
    """-> (rows, info). rows = list[list[str]] berisi 8 kolom mentah."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        text = f.read()
    first, sep, rest = text.partition("\n")
    info = {"header_fused": False, "duplicate_header_row": False}
    if first.rstrip("\r") == HEADER:
        text = rest
    elif first.startswith(HEADER):
        info["header_fused"] = True
        text = first[len(HEADER):] + sep + rest          # sisa baris pertama = baris data pertama
    else:
        raise ValueError(f"{Path(path).name}: header tidak dikenal: {first[:80]!r}")
    rows = list(csv.reader(io.StringIO(text, newline="")))
    if rows and rows[0] == COLS:
        info["duplicate_header_row"] = True
        rows = rows[1:]
    bad = [i for i, r in enumerate(rows, 1) if len(r) != len(COLS)]
    if bad:
        raise ValueError(f"{Path(path).name}: {len(bad)} baris dengan jumlah field != {len(COLS)}, contoh baris data {bad[:3]}")
    return rows, info


def list_event_files(events_dir) -> list:
    return sorted(Path(events_dir).glob("*.csv"), key=file_order_key)


def read_scenario_events(events_dir) -> tuple:
    """-> (records, file_infos). Urutan: file (file_order_key) lalu baris. Tiap record punya source_file, row_in_file (1-based), row_hash."""
    files = list_event_files(events_dir)
    if not files:
        raise FileNotFoundError(str(events_dir))
    records, infos = [], []
    for fp in files:
        rows, info = read_events_file(fp)
        sha = hashlib.sha256(fp.read_bytes()).hexdigest()
        infos.append({"file": fp.name, "rows": len(rows), "sha256": sha, **info})
        for i, r in enumerate(rows, 1):
            records.append({"source_file": fp.name, "row_in_file": i, "row_hash": row_hash(r), "cols": r})
    return records, infos
