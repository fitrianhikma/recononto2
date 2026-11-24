"""Parameter korelasi event (Phase 5B v2). Mengikuti ORD2I (Chabot et al., 2015): skor = rata-rata (CorrT, CorrS, CorrO); aturan pakar terpenuhi -> skor maksimal.

Nilai-nilai di bawah adalah OPERASIONALISASI PENELITIAN, BUKAN definisi Chabot, kecuali yang diberi catatan literatur.
Chabot (2015) memberi: rata-rata tiga skor berbobot sama, ambang 0,5 (dapat diubah pengguna), EK -> maksimal, dan skor objek-dekat 0,25 pada Tabel 2.

Digabung dari correlation_config.py (konstanta) + correlation_core.py (inti korelasi) saat refactoring folder (lihat docs/REFERENCE.md (bagian 4)).
Tidak ada isi fungsi atau nilai konstanta yang diubah; `cc` dipertahankan sebagai cara mengakses konstanta (dulu `import correlation_config as cc`),
kini sebagai referensi-diri modul ini supaya pemanggil (07_correlate.py, 09_prompts.py) tidak perlu berubah selain baris impor.

Inti korelasi event (Phase 5B v2): pemuat .nt ringan, event kanonik, kandidat dari indeks, skor gaya ORD2I (Chabot et al., 2015).

skor = 1,0 bila aturan pakar (R1) terpenuhi; selain itu rata-rata (CorrT + CorrS + CorrO) / 3 (bobot sama).

KELENGKAPAN KANDIDAT (bukti untuk bobot sama, TAU >= 0,5):
  skor >= TAU berarti T + S + O >= 3*TAU >= 1,5 (tanpa EK).
  - Bila S = 0 (tidak ada subjek bersama): T + O >= 1,5 dengan T <= 1 dan O <= 1 -> O >= 0,5. NEAR_OBJECT_SCORE (0,25) tidak cukup, jadi himpunan objek
    HARUS berpotongan; lalu T >= 1,5 - O >= 0,5, yaitu dt <= 2 detik.   => sumber A (objek bersama dan dt <= T_CANDIDATE_MAX_S) mencakup semuanya.
  - Bila S > 0: kedua event berbagi subjek.                                  => sumber B (semua pasangan berbagi subjek) mencakup semuanya.
  - Bila EK: skor = 1,0.                                                     => sumber C (indeks nama executable) mencakup semuanya.
Bila TAU < 0,5 atau bobot diubah, argumen ini tidak berlaku: check_parameters() menolak berjalan.
Tidak ada enumerasi pasangan berdasar waktu saja. Skor hanya mengurutkan dan menyaring pasangan."""
import calendar, re
from collections import Counter, defaultdict
from itertools import combinations

from rdf_nt import ORD2I, RDF_TYPE, parse_nt_line

# --- konstanta (dulu correlation_config.py), nilai tidak diubah ---
NEAR_OBJECT_SCORE = 0.25    # operasionalisasi penelitian, bukan definisi Chabot (nilai 0,25 dari contoh Tabel 2, Chabot 2015): objek berbeda tetapi hostname/direktori sama
TAU = 0.5                   # ambang skor: literatur (Chabot 2015) memakai 0,5; operasionalisasi penelitian bila diubah. JANGAN < 0,5 (pembangkitan kandidat tidak lagi lengkap)
R1_WINDOW_S = 60.0          # operasionalisasi penelitian, bukan definisi Chabot: jendela aturan pakar R1 (inklusif, |dt|)
T_CANDIDATE_MAX_S = 2.0     # operasionalisasi penelitian, bukan definisi Chabot: turunan dari TAU=0,5 dan bobot sama (CorrT >= 0,5 <=> dt <= 2 detik)
WEIGHTS = (1.0, 1.0, 1.0)   # bobot (T, S, O) sama; program menolak berjalan bila diubah (pembangkitan kandidat bergantung padanya)
SENSITIVITY_THRESHOLDS = (0.5, 0.6, 0.7, 0.8, 0.9, 1.0)    # analisis sensitivitas, bukan definisi Chabot
SCORE_EPS = 1e-12           # toleransi pembulatan float pada perbandingan skor >= ambang

import sys as _sys
cc = _sys.modules[__name__]  # kompatibilitas: pemanggil lama memakai 'cc.TAU' dst. (dulu modul correlation_config terpisah)

O = lambda n: ORD2I + n
_NEED = {"hasTimestamp", "hasRowHash", "hasEventType", "hasParser", "hasSourceFile", "hasRowInFile", "hasObject", "hasSubject",
         "hasFileName", "hasFilePath", "hasRegistryKey", "hasURL", "hasAccountName", "hasDomain"}
_LABEL_PROPS = ("hasFilePath", "hasFileName", "hasRegistryKey", "hasURL", "hasAccountName", "hasDomain")
_TS = re.compile(r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?Z$")


def ts_us(s: str) -> int:
    m = _TS.match(s)
    if not m: raise ValueError(f"hasTimestamp bukan xsd:dateTime UTC: {s!r}")
    y, mo, d, h, mi, se = (int(m.group(i)) for i in range(1, 7))
    return calendar.timegm((y, mo, d, h, mi, se)) * 1_000_000 + int((m.group(7) or "0").ljust(6, "0")[:6])


def exe_basename(name: str) -> str:
    return re.split(r"[\\/]", name)[-1].lower()


def _host(url: str) -> str:
    """hostname dari URL berskema (huruf kecil); kosong bila tidak ada (mis. file:///)."""
    return url.split("://", 1)[-1].split("/", 1)[0].lower() if "://" in url else ""


def _dir(path: str) -> str:
    p = path.replace("/", "\\").lower()
    return p.rsplit("\\", 1)[0] if "\\" in p else ""


class Event:
    __slots__ = ("iri", "t", "parser", "etype", "source_file", "row", "hash", "copies", "objs", "subs", "exes")


def load_events(nt_path) -> dict:
    """-> {"events": [Event] terurut (t, iri), "labels": {iri_entitas: teks}, "stats": {...}}. Satu skenario per panggilan."""
    props, objs, subs, event_iris = defaultdict(dict), defaultdict(list), defaultdict(list), set()
    with open(nt_path, encoding="utf-8", newline="") as f:
        for line in f:
            s_end = line.index(" "); p_end = line.index(" ", s_end + 1); pred = line[s_end + 2:p_end - 1]
            if pred == RDF_TYPE:
                if line.rstrip().endswith(f"<{O('Event')}> ."): event_iris.add(line[1:s_end - 1])
            elif pred.startswith(ORD2I) and pred[len(ORD2I):] in _NEED:
                s, p, o = parse_nt_line(line); name = p[len(ORD2I):]
                if name == "hasObject": objs[s].append(o[1])
                elif name == "hasSubject": subs[s].append(o[1])
                else: props[s].setdefault(name, o[1])
    valid = sorted(i for i in event_iris if "hasTimestamp" in props[i])
    by_hash, copies = {}, Counter()
    for iri in valid:
        h = props[iri]["hasRowHash"]; copies[h] += 1; by_hash.setdefault(h, iri)           # kemunculan pertama menurut urutan IRI
    events = []
    for h, iri in by_hash.items():
        p, e = props[iri], Event()
        e.iri, e.t, e.parser, e.etype, e.source_file, e.row, e.hash, e.copies = iri, ts_us(p["hasTimestamp"]), p["hasParser"], p["hasEventType"], p["hasSourceFile"], int(p["hasRowInFile"]), h, copies[h]
        e.objs, e.subs = frozenset(objs[iri]), frozenset(subs[iri])
        e.exes = frozenset(x for x in (exe_basename(props[o]["hasFileName"]) for o in e.objs if "hasFileName" in props.get(o, {})) if x)
        events.append(e)
    events.sort(key=lambda e: (e.t, e.iri))
    used = set().union(*(e.objs | e.subs for e in events)) if events else set()
    labels = {o: next((props[o][k] for k in _LABEL_PROPS if k in props.get(o, {})), o.rsplit("/", 1)[-1]) for o in used}
    facets = {o: (_host(props[o].get("hasURL", "")), _dir(props[o].get("hasFilePath", ""))) for o in used}      # (hostname, direktori) untuk 'objek dekat'
    stats = {"event_individuals": len(event_iris), "valid_timestamp_rows": len(valid), "canonical_events": len(events), "duplicate_copies_excluded": len(valid) - len(events),
             "rows_without_valid_timestamp": len(event_iris) - len(valid), "canonical_with_2plus_objects": sum(1 for e in events if len(e.objs) >= 2)}
    return {"events": events, "labels": labels, "facets": facets, "stats": stats}


# ---------------------------------------------------------------- fungsi korelasi (ORD2I 2015, operasionalisasi)
def check_parameters(tau=cc.TAU, weights=cc.WEIGHTS):
    """Menolak berjalan bila argumen kelengkapan kandidat tidak lagi berlaku."""
    if tau < 0.5: raise ValueError(f"TAU={tau} < 0,5: pembangkitan kandidat tidak lagi lengkap (lihat docstring modul)")
    if tuple(weights) != (1.0, 1.0, 1.0): raise ValueError(f"bobot {tuple(weights)} != (1,1,1): pembangkitan kandidat tidak lagi lengkap")


def corr_t(dt_us: int) -> float:
    """dt = 0 -> 1,0; dt > 0 -> min(1, 1/dt_detik) (bentuk 1/dt: Chabot 2014, selaras Tabel 2 2015; satuan detik = implementasi)."""
    return 1.0 if dt_us == 0 else min(1.0, 1_000_000 / dt_us)


def set_ratio(a: frozenset, b: frozenset) -> float:
    """|A n B| / max(|A|,|B|); 0 bila salah satu kosong."""
    return len(a & b) / max(len(a), len(b)) if a and b else 0.0


def near_objects(a: frozenset, b: frozenset, facets: dict) -> bool:
    """Ada sepasang objek (berbeda) dengan hostname URL sama (tak kosong) atau direktori sama (tak kosong)."""
    for x in a:
        hx, dx = facets.get(x, ("", ""))
        for y in b:
            hy, dy = facets.get(y, ("", ""))
            if (hx and hx == hy) or (dx and dx == dy): return True
    return False


def corr_o(e, x, facets, near_score=cc.NEAR_OBJECT_SCORE) -> float:
    if e.objs & x.objs: return set_ratio(e.objs, x.objs)
    return near_score if e.objs and x.objs and near_objects(e.objs, x.objs, facets) else 0.0


def ek_r1(e, x, dt_us, window_s=cc.R1_WINDOW_S) -> int:
    """R1 (ekstensi penelitian, bukan aturan Chabot): executable (basename) sama pada dua event berparser BERBEDA dalam |dt| <= window_s (inklusif)."""
    return 1 if (e.exes & x.exes) and e.parser != x.parser and abs(dt_us) <= window_s * 1_000_000 else 0


def components(e, x, facets):
    dt = x.t - e.t
    return dt, corr_t(dt), set_ratio(e.subs, x.subs), corr_o(e, x, facets), ek_r1(e, x, dt)


def score_of(ct, cs, co, ek) -> float:
    return 1.0 if ek else (ct + cs + co) / 3.0


def _pair_keys(index: dict, n: int, events=None, max_dt_us=None) -> set:
    out = set()
    for lst in index.values():
        if max_dt_us is None:
            for i, j in combinations(lst, 2): out.add(i * n + j)                          # lst menaik -> i < j (e lebih awal)
        else:
            j = 0
            for a in range(len(lst)):
                while events[lst[a]].t - events[lst[j]].t > max_dt_us: j += 1
                for b in range(j, a): out.add(lst[b] * n + lst[a])
    return out


def r1_pair_keys(events, window_s=cc.R1_WINDOW_S) -> set:
    n, idx, out, w = len(events), defaultdict(list), set(), window_s * 1_000_000
    for i, e in enumerate(events):
        for x in e.exes: idx[x].append(i)
    for lst in idx.values():
        j = 0
        for a in range(len(lst)):
            while events[lst[a]].t - events[lst[j]].t > w: j += 1
            for b in range(j, a):
                if events[lst[a]].parser != events[lst[b]].parser: out.add(lst[b] * n + lst[a])
    return out


def window_pair_counts(events, windows=(0, 1, 2, 5, 60)) -> dict:
    """INFORMASI: jumlah pasangan dalam jendela waktu, tanpa enumerasi (dua pointer). Bukan kandidat korelasi."""
    T, out = [e.t for e in events], {}
    for w in windows:
        j = tot = 0
        for i in range(len(T)):
            while T[i] - T[j] > w * 1_000_000: j += 1
            tot += i - j
        out[f"pairs_within_{w}s"] = tot
    return out


def correlate(events, labels=None, facets=None, tau=cc.TAU, weights=cc.WEIGHTS, thresholds=cc.SENSITIVITY_THRESHOLDS, top_n=20) -> dict:
    """-> {"rows", "counts", "sensitivity", "ablation", "top", "descriptive"}. Kandidat hanya dari sumber A (objek bersama, dt <= T_CANDIDATE_MAX_S),
    B (subjek bersama), C (R1)."""
    check_parameters(tau, weights)
    n, eps, facets, labels = len(events), cc.SCORE_EPS, facets or {}, labels or {}
    oi, si = defaultdict(list), defaultdict(list)
    for i, e in enumerate(events):
        for o in e.objs: oi[o].append(i)
        for s in e.subs: si[s].append(i)
    pA = _pair_keys(oi, n, events, int(cc.T_CANDIDATE_MAX_S * 1_000_000)); pB = _pair_keys(si, n); pC = r1_pair_keys(events)
    union = pA | pB | pC
    rows, restating, nonrest = [], 0, 0
    sens, abl, src, drivers, pp = {str(t): 0 for t in thresholds}, Counter(), Counter(), Counter(), Counter()
    for key in union:
        i, j = divmod(key, n); e, x = events[i], events[j]
        dt, ct, cs, co, ek = components(e, x, facets)
        if e.objs & x.objs and dt == 0: restating += 1; continue                          # restating: objek sama DAN timestamp sama
        nonrest += 1; score = score_of(ct, cs, co, ek)
        for t in thresholds:
            if score >= t - eps: sens[str(t)] += 1
        if ct >= tau - eps: abl["only_T"] += 1                                            # ablasi: rata-rata HANYA komponen terhitung (bobot dinormalisasi ulang)
        if cs >= tau - eps: abl["only_S"] += 1
        if co >= tau - eps: abl["only_O"] += 1
        if ek: abl["only_EK"] += 1                                                        # hanya EK: skor 1,0 bila EK, selain itu 0
        if score >= tau - eps:
            rows.append((e.iri, x.iri, dt / 1_000_000, ct, cs, co, ek, score, "R1" if ek else ""))
            for tag, ps in (("A", pA), ("B", pB), ("C", pC)):
                if key in ps: src[tag] += 1
            drivers[("EK" if ek else "") + ("S" if cs else "") + ("O" if co else "")] += 1
            if co == cc.NEAR_OBJECT_SCORE: drivers["eligible_via_NEAR_object"] += 1
            pp[tuple(sorted((e.parser, x.parser)))] += 1
    rows.sort(key=lambda r: (-round(r[7], 9), r[0], r[1]))
    ix = {e.iri: e for e in events}; top = []
    for r in rows[:top_n]:
        e, x = ix[r[0]], ix[r[1]]; shared = sorted(labels.get(o, o) for o in e.objs & x.objs)
        top.append({"event_a": r[0], "event_b": r[1], "score": round(r[7], 6), "components": {"corr_t": round(r[3], 6), "corr_s": round(r[4], 6), "corr_o": round(r[5], 6), "ek": r[6]},
                    "delta_t_s": round(r[2], 6), "a": {"type": e.etype, "parser": e.parser, "file": e.source_file, "row": e.row}, "b": {"type": x.etype, "parser": x.parser, "file": x.source_file, "row": x.row},
                    "shared_objects": shared[:5], "rules_hit": r[8],
                    "explanation": ("EK (R1) terpenuhi -> skor 1,0" if r[6] else f"(CorrT {r[3]:.3f} + CorrS {r[4]:.3f} + CorrO {r[5]:.3f}) / 3") + f"; dt={r[2]:.3f} s; {len(e.objs & x.objs)} objek bersama dari {len(e.objs)} vs {len(x.objs)}"})
    counts = {"candidate_pairs_unique": len(union), "candidates_by_source": {"A_object_dt_le_Tmax": len(pA), "B_subject": len(pB), "C_R1": len(pC)},
              "restating_excluded": restating, "candidates_after_restating": nonrest, "ek_pairs": len(pC), "pairs_in_pairs_csv": len(rows),
              "eligible_by_source_nonexclusive": dict(src), "eligible_drivers": dict(drivers)}
    groups = sorted(((len(v), k) for k, v in oi.items()), reverse=True)[:5]
    desc = {"eligible_by_parser_pair_top": [{"parsers": " | ".join(k), "pairs": v, "share": round(v / max(len(rows), 1), 4)} for k, v in pp.most_common(8)],
            "largest_object_groups": [{"object": labels.get(k, k), "canonical_events": c, "pairs_in_group_total": c * (c - 1) // 2} for c, k in groups]}
    ablation = {"definition": "skor varian = rata-rata HANYA komponen yang dihitung (bobot dinormalisasi ulang), EK-saja = 1,0 bila EK selain itu 0; dihitung atas kandidat setelah restating dikeluarkan (bukan seluruh timeline)",
                "only_T": abl["only_T"], "only_S": abl["only_S"], "only_O": abl["only_O"], "only_EK": abl["only_EK"], "full": len(rows)}
    return {"rows": rows, "counts": counts, "sensitivity": sens, "ablation": ablation, "top": top, "descriptive": desc}
