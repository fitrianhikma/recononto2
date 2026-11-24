"""STAGE 07 - Korelasi event (kode lama 05_correlate.py + 05_check_cases.py; rumus dan parameter TIDAK diubah).
    python3 src/07_correlate.py --scenario {1,2,3,all} [--verify-determinism]
Keluaran: results/07_correlation/scenarioN/{pairs.csv, correlation_report.json, case_check.json}.
Verifikasi rumus terhadap Chabot et al. (2015): docs/REFERENCE.md (bagian 3).

PHASE 5B (v2) - Korelasi event baseline gaya ORD2I (Chabot et al., 2015). Satu skenario per proses; graf tidak pernah digabung.

    python3 src/05_correlate.py --scenario all [--verify-determinism]
Keluaran: results/correlation/scenarioN/pairs.csv + correlation_report.json. Parameter: src/correlation.py.
Skor hanya untuk mengurutkan dan menyaring pasangan; bukan probabilitas dan bukan bukti kausal.

Uji kasus kewajaran korelasi (dulu berkas terpisah correlation_cases.py, kode lama 05_check_cases.py; digabung di sini saat refactoring
folder, lihat docs/REFERENCE.md (bagian 4) - TIDAK ada perubahan logika, hanya dipindah ke bagian "UJI KASUS" di bawah).
PHASE 5B (v2) - Uji kasus kewajaran korelasi (BUKAN precision/recall). Definisi kasus: cases/correlation_cases.json (data).
Event ditemukan lewat parser + nama executable di graf; pasangannya harus ada di pairs.csv dengan ek = 1 dan skor tepat 1,0."""
import argparse, csv, hashlib, json, os, resource, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config, correlation as cc, correlation as core

COLS = ["event_a", "event_b", "delta_t_s", "corr_t", "corr_s", "corr_o", "ek", "score", "rules_hit"]


def write_pairs(path, rows) -> str:
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True); tmp = path.with_name(path.name + ".tmp")
    try:
        with open(tmp, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f, lineterminator="\n"); w.writerow(COLS)
            for r in rows: w.writerow([r[0], r[1], f"{r[2]:.6f}", f"{r[3]:.6f}", f"{r[4]:.6f}", f"{r[5]:.6f}", r[6], f"{r[7]:.6f}", r[8]])
        os.replace(tmp, path)
    finally:
        if tmp.exists(): tmp.unlink()
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_scenario(scenario, root=None, out_root=None, verify_determinism=False) -> dict:
    rp = config.rdf_paths(scenario, root); rootp = Path(root) if root else config.ROOT
    if not rp["nt"].exists(): return {"scenario": scenario, "status": "RDF_NOT_FOUND", "expected_path": str(rp["nt"])}
    nt_sha = hashlib.sha256(rp["nt"].read_bytes()).hexdigest()
    brp = rp["report_dir"] / f"build_report_{scenario}.json"
    if brp.exists() and json.loads(brp.read_text(encoding="utf-8"))["nt_sha256"] != nt_sha: raise ValueError(f"{rp['nt'].name} tidak cocok dengan laporan Phase 3B (graf basi?)")
    out_dir = Path(out_root) / scenario if out_root else config.correlation_dir(scenario, root)
    t0 = time.time(); data = core.load_events(rp["nt"]); events = data["events"]; load_s = round(time.time() - t0, 2)
    t1 = time.time(); res = core.correlate(events, data["labels"], data["facets"], tau=cc.TAU, weights=cc.WEIGHTS); corr_s = round(time.time() - t1, 2)
    sha = write_pairs(out_dir / "pairs.csv", res["rows"]); pairs_path = out_dir / "pairs.csv"
    rep = {"scenario": scenario, "status": "OK", "nt_sha256": nt_sha,
           "parameters": {"NEAR_OBJECT_SCORE": cc.NEAR_OBJECT_SCORE, "TAU": cc.TAU, "R1_WINDOW_S": cc.R1_WINDOW_S, "T_CANDIDATE_MAX_S": cc.T_CANDIDATE_MAX_S, "WEIGHTS": list(cc.WEIGHTS),
                          "label": "operasionalisasi penelitian kecuali TAU=0,5 dan NEAR=0,25 yang berasal dari contoh Chabot et al. (2015)"},
           "events": data["stats"], "counts": res["counts"], "window_pairs_info_not_candidates": core.window_pair_counts(events),
           "sensitivity_pairs_with_score_ge": res["sensitivity"], "ablation_eligible_pairs": res["ablation"], "descriptive": res["descriptive"],
           "pairs_csv": {"rows": len(res["rows"]), "bytes": pairs_path.stat().st_size, "sha256": sha}, "top20": res["top"],
           "load_seconds": load_s, "correlate_seconds": corr_s}
    if verify_determinism:
        d2 = core.load_events(rp["nt"]); again = core.correlate(d2["events"], d2["labels"], d2["facets"], tau=cc.TAU, weights=cc.WEIGHTS); tmp = out_dir / ".verify_pairs.csv"
        rep["deterministic"] = write_pairs(tmp, again["rows"]) == sha; tmp.unlink()
    rep["peak_rss_mb"] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)
    tmp = out_dir / "correlation_report.json.tmp"; tmp.write_text(json.dumps(rep, indent=2, ensure_ascii=False), encoding="utf-8"); os.replace(tmp, out_dir / "correlation_report.json")
    return rep


# ---------------------------------------------------------------- UJI KASUS (dulu correlation_cases.py, isi tidak diubah)
def tod(t_us: int) -> str:
    s, us = divmod(t_us, 1_000_000)
    return f"{(s % 86400) // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}.{us // 100_000}"


def _secs(hms: str) -> float:
    return sum(float(v) * k for v, k in zip(hms.split(":"), (3600, 60, 1)))


def check_case(scenario, case, root=None, out_root=None) -> dict:
    rp = config.rdf_paths(scenario, root); base = Path(out_root) / scenario if out_root else config.correlation_dir(scenario, root)
    pp = base / "pairs.csv"
    if not rp["nt"].exists() or not pp.exists(): return {"scenario": scenario, "status": "INPUT_NOT_FOUND", "expected": [str(rp["nt"]), str(pp)]}
    events = core.load_events(rp["nt"])["events"]; exe, parsers = case["executable"].lower(), set(case["parsers"])
    found = [e for e in events if exe in e.exes and e.parser in parsers]; w = cc.R1_WINDOW_S * 1_000_000
    cand = [(a, b) for i, a in enumerate(found) for b in found[i + 1:] if a.parser != b.parser and abs(b.t - a.t) <= w]
    with open(pp, newline="", encoding="utf-8") as f: table = {(r["event_a"], r["event_b"]): dict(r, _rank=i) for i, r in enumerate(csv.DictReader(f), 1)}      # peringkat = urutan baris
    total, res = len(table), []
    for a, b in cand:
        e, x = (a, b) if (a.t, a.iri) <= (b.t, b.iri) else (b, a); r = table.get((e.iri, x.iri))
        d = {"event_a": {"parser": e.parser, "time_of_day": tod(e.t), "file": e.source_file, "row": e.row}, "event_b": {"parser": x.parser, "time_of_day": tod(x.t), "file": x.source_file, "row": x.row}, "in_pairs_csv": r is not None}
        if r: d.update({k: float(r[k]) for k in ("delta_t_s", "corr_t", "corr_s", "corr_o", "ek", "score")}, rules_hit=r["rules_hit"], rank_in_pairs_csv=r["_rank"], pairs_csv_total=total)
        res.append(d)
    times = sorted({tod(e.t) for p in cand for e in p}); tol = case.get("time_tolerance_s", 1.0)
    deltas = sorted(round(p["delta_t_s"], 1) for p in res if p["in_pairs_csv"])
    checks = {"events_found_by_parser_and_executable": {p: sum(1 for e in found if e.parser == p) for p in case["parsers"]}, "pairs_found": len(res), "pairs_expected": case["expected_pairs"],
              "pairs_count_ok": len(res) == case["expected_pairs"], "all_in_pairs_csv": bool(res) and all(r["in_pairs_csv"] for r in res),
              "all_ek_ok": bool(res) and all(r.get("ek") == case["expected_ek"] for r in res),
              "all_score_exactly_ok": bool(res) and all(abs(r.get("score", -1) - case["expected_score"]) <= cc.SCORE_EPS for r in res),
              "approx_times_present_INFO": {t: any(abs(_secs(x) - _secs(t)) <= tol for x in times) for t in case.get("approx_time_of_day_utc", [])},
              "approx_deltas_INFO": {"expected": sorted(case.get("approx_delta_s", [])), "found": deltas}}
    ok = checks["pairs_count_ok"] and checks["all_in_pairs_csv"] and checks["all_ek_ok"] and checks["all_score_exactly_ok"]
    out = {"scenario": scenario, "status": "OK", "name": case["name"], "executable": case["executable"], "passed": ok, "checks": checks, "pairs": res, "note": "uji kewajaran, bukan evaluasi"}
    tmp = base / "case_check.json.tmp"; tmp.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8"); os.replace(tmp, base / "case_check.json")
    return out


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--scenario", required=True, choices=["1", "2", "3", "all"]); ap.add_argument("--verify-determinism", action="store_true")
    a = ap.parse_args(); bad = False
    for s in (["scenario3", "scenario2", "scenario1"] if a.scenario == "all" else [f"scenario{a.scenario}"]):      # graf terkecil dulu
        r = run_scenario(s, verify_determinism=a.verify_determinism)
        if r["status"] != "OK": print(f"[{s}] {r['status']}: {r['expected_path']}"); bad = True; continue
        c = r["counts"]
        print(f"[{s}] canonical={r['events']['canonical_events']} "
              f"restating={c['restating_excluded']} sources={c['candidates_by_source']} candidates={c['candidate_pairs_unique']} ge0.5={c['pairs_in_pairs_csv']} ek={c['ek_pairs']} peak_rss={r['peak_rss_mb']}MB load={r['load_seconds']}s corr={r['correlate_seconds']}s deterministic={r.get('deterministic', 'tidak diuji')}")
        bad |= r.get("deterministic") is False
    cases = {k: v for k, v in json.loads((config.ROOT / "cases" / "correlation_cases.json").read_text(encoding="utf-8")).items() if not k.startswith("_")}
    for s, case in cases.items():                                          # uji kewajaran (bukan precision/recall); dulu langkah terpisah 05_check_cases.py
        if a.scenario != "all" and s != f"scenario{a.scenario}": continue
        r = check_case(s, case)
        if r["status"] != "OK": print(f"[{s}] uji kasus: {r['status']}"); bad = True; continue
        print(f"[{s}] uji kasus '{r['name']}': {'LULUS' if r['passed'] else 'GAGAL'} | pasangan={r['checks']['pairs_found']}/{r['checks']['pairs_expected']}"); bad |= not r["passed"]
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
