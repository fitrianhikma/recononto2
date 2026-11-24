"""Registri tugas dan unit (baru V1). Ground truth resmi hanya DIBACA; tidak ada ground truth yang dibuat atau diubah.

Tugas = satu berkas ground truth resmi:
  scenario1 -> tasks/event-summarization/ground-truth-single/*.json (14)  [ground-truth-multiple dipakai sebagai referensi tambahan]
  scenario2 -> tasks/keyword-analysis/ground-truth/*.json (7)
  scenario3 -> tasks/grep/ground-truth/*.txt (5)
Berkas events tugas = <nama tugas>.csv. Berkas events tanpa ground truth (mis. 8-firefox-install.csv) tidak menjadi tugas,
tetapi tetap ikut preprocessing, RDF, korelasi, dan unit=scenario (perilaku lama).

Unit:
  task     : satu unit per tugas; digest hanya dari berkas events tugas itu.        (26 unit)
  scenario : satu unit per skenario; digest dari semua berkas events (pipeline lama). (3 unit)

Identitas butir ground truth (untuk semantik himpunan, keputusan (c)):
  S1: (tipe event, date_time_min sampai detik, evidence_source ternormalisasi)
  S2: (datetime sampai mikrodetik, message ternormalisasi)
  S3: baris CSV utuh
"""
import csv, json, re
from pathlib import Path

import config

GT_DIRS = {"scenario1": ("event-summarization/ground-truth-single", ".json"),
           "scenario2": ("keyword-analysis/ground-truth", ".json"),
           "scenario3": ("grep/ground-truth", ".txt")}
S1_MULTIPLE = "event-summarization/ground-truth-multiple"


def list_tasks(scenario: str, tasks_dir=None) -> list:
    config.check_scenario(scenario); base = Path(tasks_dir or config.TASKS_DIR); sub, ext = GT_DIRS[scenario]
    out = []
    for p in sorted((base / sub).glob(f"*{ext}"), key=lambda p: _order(p.stem)):
        d = {"scenario": scenario, "task": p.stem, "source_file": p.stem + ".csv", "gt_path": str(p)}
        if scenario == "scenario1":
            m = base / S1_MULTIPLE / p.name; d["gt_multiple_path"] = str(m) if m.exists() else None
        out.append(d)
    return out


def _order(stem: str):
    m = re.match(r"^(\d+)-", stem); return (0, int(m.group(1)), stem) if m else (1, 0, stem)


def units(scenario: str, unit: str, tasks_dir=None) -> list:
    ts = list_tasks(scenario, tasks_dir)
    if unit == "task":
        return [{"scenario": scenario, "unit": "task", "unit_id": t["task"], "tasks": [t], "source_files": [t["source_file"]]} for t in ts]
    if unit == "scenario":
        return [{"scenario": scenario, "unit": "scenario", "unit_id": "all", "tasks": ts, "source_files": None}]
    raise ValueError(unit)


# ---------------------------------------------------------------- ground truth: baca + identitas
def read_gt(task: dict, which: str = "single") -> list:
    """S1 -> list item JSON (urutan kunci berkas, sama seperti evaluator lama); S2 -> list item JSON; S3 -> list baris tak kosong."""
    s = task["scenario"]
    path = task["gt_path"] if which == "single" else task.get("gt_multiple_path")
    if not path: return []
    if s == "scenario1": return list(json.loads(Path(path).read_text(encoding="utf-8")).values())
    if s == "scenario2": return json.loads(Path(path).read_text(encoding="utf-8"))
    return [l.rstrip("\r") for l in Path(path).read_text(encoding="utf-8", errors="replace").splitlines() if l.strip()]


def norm_text(s: str) -> str:
    """Spasi diringkas; deret backslash -> satu backslash (GT memadatkan escape secara tidak konsisten)."""
    return re.sub(r"\\+", r"\\", " ".join((s or "").split()))


def _dt(s: str, n: int) -> str:
    m = re.match(r"^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})(\.\d+)?", s or "")
    if not m: return s or ""
    return f"{m.group(1)}T{m.group(2)}" + (("." + (m.group(3) or ".0")[1:].ljust(6, "0")[:6]) if n > 19 else "")


def identity(scenario: str, item) -> tuple:
    if scenario == "scenario1": return (item.get("type", ""), _dt(item.get("date_time_min", ""), 19), norm_text(item.get("evidence_source", "")))
    if scenario == "scenario2": return (_dt(item.get("datetime", ""), 26), norm_text(item.get("message", "")))
    return (item,)


def group_items(scenario: str, items: list, hashes: list = None) -> list:
    """-> [{identity, mult, hashes}] menurut urutan kemunculan pertama. hashes (opsional) = per item dari pemetaan lama (gt_s1/gt_s2/gt_s3)."""
    out, pos = [], {}
    for i, it in enumerate(items):
        k = identity(scenario, it); h = set(hashes[i]) if hashes is not None else set()
        if k in pos: g = out[pos[k]]; g["mult"] += 1; g["hashes"] |= h
        else: pos[k] = len(out); out.append({"identity": k, "mult": 1, "hashes": h, "item": it})
    return out


def s1_reference_lines(items: list) -> list:
    """Referensi teks S1 (BLEU/ROUGE): satu baris per TEKS unik '<HH:MM:SS> <type>: <description>', urut waktu lalu tipe.
    Kolom evidence_source, supporting, plugin, files, keys TIDAK dipakai (bukan bahasa laporan), sehingga deduplikasi juga tidak
    memakainya: butir yang hanya berbeda evidence_source menghasilkan baris yang sama dan dihitung satu. Pembanding mengabaikan
    huruf besar/kecil dan spasi (tokenisasi BLEU/ROUGE juga begitu); teks kemunculan pertama dipertahankan.
    identity()/group_items() (P/R/F1) sengaja tidak memakai aturan ini."""
    seen, rows = set(), []
    for it in items:
        t = _dt(it.get("date_time_min", ""), 19); line = f"{t[11:19]} {it.get('type', '')}: {it.get('description', '')}".strip()
        k = (t, norm_text(line).casefold())
        if k in seen: continue
        seen.add(k); rows.append((t, it.get("type", ""), line))
    return [r[2] for r in sorted(rows, key=lambda r: (r[0], r[1]))]


def raw_rows_for_mapping(events_dir, source_files=None) -> list:
    """Baris dalam bentuk kolom CSV terproses lama (source_file, datetime_raw, message, parser, row_hash) langsung dari berkas events
    mentah, untuk audit stage 01 sebelum preprocessing. Pembacaan memakai events_reader lama (cacat header ditangani sama)."""
    import events_reader as er
    out = []
    for fp in er.list_event_files(events_dir):
        if source_files is not None and fp.name not in source_files: continue
        rows, _ = er.read_events_file(fp)
        for i, c in enumerate(rows, 1):
            out.append({"source_file": fp.name, "row_in_file": i, "datetime_raw": c[0], "message": c[4], "parser": c[5], "row_hash": er.row_hash(c), "cols": c})
    return out


def read_processed_rows(scenario: str, root=None) -> list:
    p = config.scenario_paths(scenario, root)["processed_dir"] / config.OFFICIAL_PROCESSED
    if not p.exists(): raise FileNotFoundError(f"{p} belum ada: jalankan stage 02")
    csv.field_size_limit(1 << 30)
    with open(p, newline="", encoding="utf-8") as f: return list(csv.DictReader(f))
