"""STAGE 05 - Katalog SPARQL (kode lama 04_sparql_run.py; query dan eksekusi tidak diubah). Keluaran: results/05_sparql/scenarioN/.
Tambahan V1: setiap query kosong diberi status menurut queries/catalog.json (DIPERKIRAKAN_KOSONG + alasan, atau PERLU_DIPERIKSA),
serta perbandingan jumlah baris dengan run lama (informasi, bukan target).

PHASE 4B (B1) - Menjalankan katalog SPARQL pada graf satu skenario. rdflib dimuat dari rdf/scenarioN.nt (graf tidak pernah digabung).

    python3 src/04_sparql_run.py --scenario all [--queries queries] [--verify-determinism]
Keluaran: results/sparql/scenarioN/Qxx.csv (urutan baris = hasil ORDER BY) + sparql_report.json.
Isi query TIDAK diubah. Template Q12-Q14 dipanggil lewat sparql_common.run_template."""
import argparse, gc, json, os, resource, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config, sparql_common as sc


def int_column_sum(cols, rows):
    """Jumlah kolom bilangan bulat (terakhir bila ada beberapa) -> (nama kolom, jumlah) atau (None, None)."""
    for j in range(len(cols) - 1, -1, -1):
        try: return cols[j], sum(int(r[j]) for r in rows)
        except ValueError: continue
    return None, None


def empty_analysis(scenario, queries) -> tuple:
    """Status query kosong menurut queries/catalog.json + perbandingan jumlah baris dengan run lama (informasi)."""
    p = config.QUERIES_DIR / "catalog.json"; cat = json.loads(p.read_text(encoding="utf-8"))["queries"] if p.exists() else {}
    empty, legacy = {}, {}
    for n, q in queries.items():
        c = cat.get(n, {}); old = c.get("legacy_rows", {}).get(scenario)
        if old is not None: legacy[n] = {"rows_now": q["rows"], "rows_legacy": old, "same": q["rows"] == old}
        if q["rows"] == 0:
            why = c.get("expected_empty", {}).get(scenario)
            empty[n] = {"status": "DIPERKIRAKAN_KOSONG", "reason": why} if why else {"status": "PERLU_DIPERIKSA", "reason": "kosong padahal tidak tercantum di catalog.json: periksa relevansi query, keberadaan tipe event (Q10), atau bug"}
    return empty, legacy


def run_scenario(scenario, qdir=None, out_root=None, root=None, verify_determinism=False, loader=None) -> dict:
    rp = config.rdf_paths(scenario, root); rootp = Path(root) if root else config.ROOT
    if not rp["nt"].exists(): return {"scenario": scenario, "status": "RDF_NOT_FOUND", "expected_path": str(rp["nt"])}
    names = sc.catalog_queries(qdir)
    br_path = rp["report_dir"] / f"build_report_{scenario}.json"
    br = json.loads(br_path.read_text(encoding="utf-8")) if br_path.exists() else None
    import hashlib
    nt_sha = hashlib.sha256(rp["nt"].read_bytes()).hexdigest()
    if br and br["nt_sha256"] != nt_sha: raise ValueError(f"{rp['nt'].name} tidak cocok dengan laporan Phase 3B (graf basi?)")
    out_dir = Path(out_root) / scenario if out_root else config.RESULTS_DIR / scenario
    t0 = time.time(); g = (loader or sc.load_graph)(rp["nt"]); load_s = round(time.time() - t0, 2)
    rep = {"scenario": scenario, "status": "OK", "nt_sha256": nt_sha, "triples": len(g), "load_seconds": load_s, "queries": {}}
    data = {}
    for pass_no in (1, 2) if verify_determinism else (1,):
        for n in names:
            t = time.time(); cols, rows = sc.run_select(g, sc.query_text(n, qdir)); dt = round(time.time() - t, 2)
            if pass_no == 1:
                sha = sc.write_csv_atomic(out_dir / f"{n}.csv", cols, rows); data[n] = (cols, rows)
                rep["queries"][n] = {"rows": len(rows), "columns": cols, "seconds": dt, "sha256": sha}
                print(f"[{scenario}] {n}: {len(rows)} baris ({dt} dtk)", flush=True)
            else:
                again = sc.write_csv_atomic(out_dir / f".verify_{n}.csv", cols, rows); (out_dir / f".verify_{n}.csv").unlink()
                rep["queries"][n]["deterministic"] = (again == rep["queries"][n]["sha256"])
    if verify_determinism: rep["deterministic_all"] = all(q["deterministic"] for q in rep["queries"].values())
    events = br["events"] if br else None; cons = {"events_from_build_report": events}
    if "Q10_event_type_stats" in data:
        c, s = int_column_sum(*data["Q10_event_type_stats"]); cons.update({"q10_count_column": c, "q10_sum": s, "q10_sum_equals_events": s == events if events is not None else None})
    if "Q01_timeline" in data and "Q01b_undated" in data:
        c, s = int_column_sum(*data["Q01b_undated"]); q1 = len(data["Q01_timeline"][1])
        cons.update({"q01_rows": q1, "q01b_count_column": c, "q01b_sum": s, "q01_plus_q01b_equals_events": (q1 + s == events) if (s is not None and events is not None) else None})
    rep["consistency"] = cons
    rep["empty_query_analysis"], rep["legacy_row_comparison_INFO"] = empty_analysis(scenario, rep["queries"])
    rep["consistency_ok"] = all(v for k, v in cons.items() if k.endswith("equals_events") and v is not None) if any(k.endswith("equals_events") for k in cons) else None
    try:
        import rdflib; rep["rdflib_version"] = rdflib.__version__
    except ImportError: pass
    rep["peak_rss_mb"] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)
    out_dir.mkdir(parents=True, exist_ok=True); tmp = out_dir / "sparql_report.json.tmp"
    tmp.write_text(json.dumps(rep, indent=2, ensure_ascii=False), encoding="utf-8"); os.replace(tmp, out_dir / "sparql_report.json")
    del g; gc.collect()
    return rep


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", required=True, choices=["1", "2", "3", "all"])
    ap.add_argument("--queries", default=str(config.QUERIES_DIR))
    ap.add_argument("--verify-determinism", action="store_true", help="jalankan seluruh katalog dua kali dan bandingkan SHA-256 CSV")
    a = ap.parse_args(); bad = False
    order = ["scenario2", "scenario3", "scenario1"] if a.scenario == "all" else [f"scenario{a.scenario}"]      # graf terkecil dulu
    for s in order:
        r = run_scenario(s, a.queries, verify_determinism=a.verify_determinism)
        if r["status"] != "OK": print(f"[{s}] {r['status']}: {r['expected_path']}"); bad = True; continue
        print(f"[{s}] triples={r['triples']} load={r['load_seconds']}s peak_rss={r['peak_rss_mb']}MB consistency_ok={r['consistency_ok']} deterministic={r.get('deterministic_all', 'tidak diuji')}")
        for n, e in r["empty_query_analysis"].items(): print(f"[{s}]   kosong {n}: {e['status']} - {e['reason']}")
        diff = {n: (v["rows_now"], v["rows_legacy"]) for n, v in r["legacy_row_comparison_INFO"].items() if not v["same"]}
        print(f"[{s}]   beda jumlah baris vs run lama (informasi): {diff if diff else 'tidak ada'}")
        bad |= r["consistency_ok"] is False or r.get("deterministic_all") is False
    sys.exit(2 if bad else 0)


if __name__ == "__main__":
    main()
