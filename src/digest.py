"""Konfigurasi digest (Phase 6B). Semua konstanta aturan seleksi di SATU berkas; aturan ditetapkan sebelum mengukur cakupan ground truth.
Label: seluruhnya OPERASIONALISASI PENELITIAN (tidak ada definisi literatur untuk digest). Bobot tipe event: src/digest_weights.csv.

Digabung dari digest_config.py (konstanta) + digest_core.py (inti digest) saat refactoring folder (lihat docs/REFERENCE.md (bagian 4)).
Tidak ada isi fungsi atau nilai konstanta yang diubah; `dc` dipertahankan sebagai cara mengakses konstanta (dulu `import digest_config as dc`),
kini referensi-diri modul ini supaya pemanggil tidak perlu berubah selain baris impor.

Inti digest (kode lama 06_build_digest.py). Aturan seleksi, bobot, anggaran, dan format baris TIDAK diubah.
Perubahan V1 (hanya penyaringan masukan): build(..., source_files=...) membatasi event pada berkas events tertentu (unit=task);
source_files=None = perilaku lama persis (unit=scenario). graph=... memungkinkan graf dibaca sekali untuk banyak unit.
Driver: 08_digest.py.

PHASE 6B - Digest dinamis per skenario (evidence untuk LLM). Deterministik; tidak ada bukti spesifik skenario di kode.
Input : rdf/scenarioN.nt, results/correlation/scenarioN/pairs.csv (pasangan R1 diambil dari sini, TIDAK dihitung ulang)
Output: results/digest/scenarioN/{digest.txt, digest_evidence.json, digest_report.json}
Aturan seleksi: docs/PHASE6A_DESIGN.md §2; konstanta: di modul ini; bobot tipe: src/digest_weights.csv.
Skor korelasi bukan probabilitas dan bukan bukti kausal.
"""
import collections, csv, hashlib, os, re, sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config
from rdf_nt import ORD2I, RDF_TYPE, parse_nt_line

# --- konstanta (dulu digest_config.py), nilai tidak diubah ---
BULK_SHARE = 0.02        # tipe dengan porsi > 2% event kanonik tidak diitemkan, hanya diringkas (aturan berbasis data)
PER_TYPE_MAX = 3         # maksimum baris yang diitemkan per tipe event
CHAR_BUDGET = 3800       # anggaran karakter digest (~950 token, chars/4); HARUS diverifikasi dengan prompt_eval_count Ollama di VM
TAIL_RESERVE = 700       # karakter yang disisihkan untuk baris penutup (Not itemised, Bulk) saat pengisian greedy
EK_MAX = 6               # maksimum event terkait aturan pakar R1 yang selalu dimasukkan
LINE_OVERHEAD = 70       # perkiraan karakter tetap per baris bukti (ID, waktu, parser, tipe) untuk pengisian greedy
TOP_CLASSES = 6          # jumlah kelas event terbanyak yang ditulis di baris "Event classes"
BULK_LINES = 2           # jumlah kelas massal yang diringkas
BULK_FREQUENT = 2        # jumlah objek tersering per kelas massal
NOT_ITEMISED_MAX = 8     # jumlah tipe maksimum di baris "Not itemised"
LABEL_PARTS = 3          # bagian maksimum per label bukti
LABEL_TEXT_MAX = 80      # panjang maksimum teks URL/kueri/nama berkas pada label
PATH_COMPONENTS = 2      # komponen terakhir path/registry yang ditulis
PROVIDER_MAX = 34        # panjang maksimum nama provider setelah awalan Microsoft-Windows- dibuang

dc = sys.modules[__name__]  # kompatibilitas: pemanggil lama memakai 'dc.CHAR_BUDGET' dst. (dulu modul digest_config terpisah)

WEIGHTS_PATH = config.DIGEST_WEIGHTS


def load_weights(path=WEIGHTS_PATH) -> dict:
    with open(path, newline="", encoding="utf-8") as f:
        return {r["event_type"]: int(r["weight"]) for r in csv.DictReader(f)}


def us(s: str) -> int:
    fmt = "%Y-%m-%dT%H:%M:%S.%f%z" if "." in s else "%Y-%m-%dT%H:%M:%S%z"
    d = datetime.strptime(s.replace("Z", "+0000"), fmt)
    return int(d.replace(microsecond=0).timestamp()) * 1_000_000 + d.microsecond


def load_graph(nt_path):
    """-> (ev, ent): ev[iri][prop] = [nilai...] untuk Event; ent[iri][prop] = nilai pertama untuk entitas lain."""
    ev = collections.defaultdict(lambda: collections.defaultdict(list)); ent = collections.defaultdict(dict); event_iris = set()
    with open(nt_path, encoding="utf-8", newline="") as f:
        for line in f:
            if not line.strip(): continue
            s, p, o = parse_nt_line(line)
            if p == RDF_TYPE:
                if o[1] == ORD2I + "Event": event_iris.add(s)
                continue
            if not p.startswith(ORD2I): continue
            name = p[len(ORD2I):]
            if "/event/" in s: ev[s][name].append(o[1])
            else: ent[s].setdefault(name, o[1])
    return {k: v for k, v in ev.items() if k in event_iris}, ent


def g1(e, k, d=""):
    v = e.get(k); return v[0] if v else d


def short_prov(p): return re.sub(r"^Microsoft-Windows-", "", p)[:dc.PROVIDER_MAX]


def short_path(x, n=dc.PATH_COMPONENTS):
    parts = re.split(r"[\\/]", x.strip("\\/")); return ("..." if len(parts) > n else "") + "\\".join(parts[-n:])


def label(k, ev, ent) -> str:
    parts = []
    for o in ev[k].get("hasObject", []):
        x = ent.get(o, {})
        for a in ("hasSearchQuery", "hasURL", "hasFileName", "hasFilePath", "hasRegistryKey", "hasDomain"):
            if a in x:
                v = x[a]; v = short_path(v) if a in ("hasFilePath", "hasRegistryKey") else v[:dc.LABEL_TEXT_MAX]; parts.append(v); break
    if "hasEventID" in ev[k]: parts.append(f"{short_prov(g1(ev[k], 'hasProvider'))} id={g1(ev[k], 'hasEventID')}")
    for s_ in ev[k].get("hasSubject", []):
        n = ent.get(s_, {}).get("hasAccountName") or ent.get(s_, {}).get("hasSID", "")
        if n: parts.append(f"acct={n}")
    if g1(ev[k], "hasEventType") in ("UserLogon", "UserLogonFailed") and g1(ev[k], "hasLogonType"): parts.append(f"logon_type={g1(ev[k], 'hasLogonType')}")     # Phase 7B patch
    return "; ".join(parts[:dc.LABEL_PARTS])


def read_ek_pairs(pairs_path) -> list:
    """IRI event dari pasangan aturan pakar R1 (kolom ek == 1) menurut urutan berkas; tanpa duplikat."""
    out = []
    if not pairs_path or not Path(pairs_path).exists(): return out
    with open(pairs_path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["ek"] == "1" and "R1" in r["rules_hit"].split("|"):
                for x in (r["event_a"], r["event_b"]):
                    if x not in out: out.append(x)
    return out


def ek_to_unit_canonical(pair_iris, hash_of, canon) -> list:
    """MIN-01: pasangan R1 memakai IRI kanonik GLOBAL (correlation.py), sedangkan `canon` digest kanonik PER UNIT. Event identik (row_hash sama)
    yang IRI-nya ada di berkas lain tidak boleh hilang: IRI pasangan -> row_hash (graf lengkap) -> IRI kanonik unit. Urutan dipertahankan, tanpa duplikat;
    event yang row_hash-nya tidak ada di unit dilewati (perilaku lama)."""
    out = []
    for iri in pair_iris:
        k = canon.get(hash_of.get(iri))
        if k is not None and k not in out: out.append(k)
    return out


def pick(vs, cap):                      # <= cap+2 grup: semua; selain itu cap grup tersebar merata menurut waktu
    if len(vs) <= cap + 2: return vs
    step = (len(vs) - 1) / (cap - 1); return [vs[round(i * step)] for i in range(cap)]


def build(nt_path, pairs_path=None, weights=None, source_files=None, graph=None) -> dict:
    W = weights or load_weights()
    ev, ent = graph if graph is not None else load_graph(nt_path)
    hash_of = {k: v["hasRowHash"][0] for k, v in ev.items() if "hasTimestamp" in v}     # graf LENGKAP: IRI mana pun -> row_hash (sebelum penyaringan unit)
    if source_files is not None:                                   # V1 unit=task: hanya event dari berkas events tugas ini
        ev = {k: v for k, v in ev.items() if g1(v, "hasSourceFile") in source_files}
    canon = {}
    for k in sorted(ev):
        if "hasTimestamp" in ev[k]: canon.setdefault(ev[k]["hasRowHash"][0], k)
    T = {k: us(ev[k]["hasTimestamp"][0]) for k in canon.values()}
    ids = sorted(canon.values(), key=lambda k: (T[k], k))
    undated = sum(1 for k in ev if "hasTimestamp" not in ev[k]); N = len(ids)
    if N == 0: raise ValueError("tidak ada event dengan timestamp valid")
    by = collections.defaultdict(list)
    for k in ids: by[g1(ev[k], "hasEventType")].append(k)
    bulk = {t for t, v in by.items() if len(v) / N > dc.BULK_SHARE}
    ek = ek_to_unit_canonical(read_ek_pairs(pairs_path), hash_of, canon)[:dc.EK_MAX]
    ek = sorted(ek, key=lambda k: (T[k], k))
    head = [f"Scope: {N} distinct events with valid time ({ev[ids[0]]['hasTimestamp'][0][:19]}Z to {ev[ids[-1]]['hasTimestamp'][0][:19]}Z); {undated} rows without valid time.",
            "Event classes (count): " + ", ".join(f"{t} {len(v)}" for t, v in sorted(by.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:dc.TOP_CLASSES]) + "."]
    weighted = sorted((t for t in by if t not in bulk and W.get(t, 0) > 0), key=lambda t: (-W[t], len(by[t]), t))
    groups = collections.OrderedDict()
    for t in weighted:
        for k in by[t]:
            lab = label(k, ev, ent)
            if lab: groups.setdefault((t, lab), []).append(k)          # bukti berlabel kosong tidak diitemkan; jumlahnya tetap di baris "Not itemised (counts)"
    queues = collections.defaultdict(list)
    for key, v in groups.items(): queues[key[0]].append((key, v))
    order = weighted
    chosen = list(ek); counts = {}; used = sum(len(x) for x in head)
    def line_len(k): return dc.LINE_OVERHEAD + len(label(k, ev, ent))
    for t in order:
        for key, v in pick(queues.get(t, []), dc.PER_TYPE_MAX):
            k = v[0]
            if k in chosen: continue
            if used + line_len(k) > dc.CHAR_BUDGET - dc.TAIL_RESERVE: continue
            chosen.append(k); counts[k] = len(v); used += line_len(k)

    def render(sel):
        sel = sorted(sel, key=lambda k: (T[k], k)); lines = list(head); evid = []
        for n, k in enumerate(sel, 1):
            c = counts.get(k, 1); suf = f" (x{c})" if c > 1 else ""; tag = " [R1]" if k in ek else ""
            lab = label(k, ev, ent); eid = f"E{n:02d}"
            lines.append(f"[{eid}] {ev[k]['hasTimestamp'][0][11:19]} {g1(ev[k], 'hasParser')} {g1(ev[k], 'hasEventType')}: {lab}{suf}{tag}")
            evid.append({"id": eid, "event_iri": k, "row_hash": g1(ev[k], "hasRowHash"), "source_file": g1(ev[k], "hasSourceFile"), "row_in_file": int(g1(ev[k], "hasRowInFile", "0")),
                         "timestamp": ev[k]["hasTimestamp"][0], "event_type": g1(ev[k], "hasEventType"), "parser": g1(ev[k], "hasParser"), "label": lab,
                         "group_count": c, "r1": k in ek})
        omitted = []
        for t in order:
            shown = sum(1 for k in sel if g1(ev[k], "hasEventType") == t); rest = len(by[t]) - shown
            if rest > 0: omitted.append(f"{t} +{rest}")
        if omitted: lines.append("Not itemised (counts): " + ", ".join(omitted[:dc.NOT_ITEMISED_MAX]) + ".")
        for t in sorted(bulk, key=lambda t: (-len(by[t]), t))[:dc.BULK_LINES]:
            c = collections.Counter(label(k, ev, ent).split(";")[0] for k in by[t] if label(k, ev, ent))
            top = sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))[:dc.BULK_FREQUENT]
            lines.append(f"Bulk {t}: {len(by[t])} events; frequent: " + ", ".join(f"{a} ({n})" for a, n in top) + ".")
        return lines, evid

    dropped = []                                     # perilaku bila melebihi anggaran: buang bobot terendah dulu (EK tidak pernah dibuang), lalu laporkan
    lines, evid = render(chosen)
    while len("\n".join(lines)) > dc.CHAR_BUDGET:
        cand = [k for k in chosen if k not in ek]
        if not cand: break
        victim = min(reversed(cand), key=lambda k: W.get(g1(ev[k], "hasEventType"), 0))      # bobot terendah; seri: yang terakhir dipilih
        chosen.remove(victim); dropped.append({"event_iri": victim, "event_type": g1(ev[victim], "hasEventType"), "weight": W.get(g1(ev[victim], "hasEventType"), 0)})
        lines, evid = render(chosen)
    text = "\n".join(lines) + "\n"
    not_itemised = {}
    for t in order:
        rest = len(by[t]) - sum(1 for k in chosen if g1(ev[k], "hasEventType") == t)
        if rest > 0: not_itemised[t] = rest
    body = len(text) - 1      # tanpa newline penutup (sebanding dengan prototipe 6A)
    report = {"chars": body, "approx_tokens_chars_div4": body // 4, "lines": len(lines), "evidence_items": len(evid), "r1_items": len(ek),
              "canonical_events": N, "rows_without_valid_time": undated, "bulk_types": sorted(bulk), "not_itemised_counts": not_itemised,
              "budget": dc.CHAR_BUDGET, "budget_dropped": dropped, "over_budget": body > dc.CHAR_BUDGET,
              "weights_sha256": hashlib.sha256(WEIGHTS_PATH.read_bytes()).hexdigest() if WEIGHTS_PATH.exists() else None,
              "digest_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}
    return {"text": text, "evidence": evid, "report": report}


def write_atomic(path: Path, data: str):
    path.parent.mkdir(parents=True, exist_ok=True); tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(data, encoding="utf-8", newline="\n"); os.replace(tmp, path)
    finally:
        if tmp.exists(): tmp.unlink()
