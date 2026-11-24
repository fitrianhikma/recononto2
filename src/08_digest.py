"""STAGE 08 - Digest per unit (aturan digest lama tidak diubah; lihat digest.py).

    python3 src/08_digest.py --scenario {1,2,3,all} [--unit task|scenario] [--unit-id ID ...] [--variant NAMA]
Masukan : results/03_rdf/scenarioN.nt, results/07_correlation/scenarioN/pairs.csv (pasangan R1 diambil, TIDAK dihitung ulang)
Keluaran: results/unit_<unit>/08_digest/scenarioN/<unit_id>/{digest.txt, digest_evidence.json, digest_report.json}
          results/unit_<unit>/08_digest/scenarioN/digest_index.json (ringkasan + kelompok digest identik)
unit=scenario menghasilkan digest yang sama byte-per-byte dengan pipeline lama (diperiksa tools/check_legacy.py).
"""
import argparse, hashlib, json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config, digest, tasks


NO_TIMED = "NO_TIMED_EVENTS"


def sha256(p: Path) -> str: return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def run_scenario(scenario: str, unit: str, root=None, tasks_dir=None, only=None) -> dict:
    rp = config.rdf_paths(scenario, root); pairs = config.correlation_dir(scenario, root) / "pairs.csv"; crep = pairs.parent / "correlation_report.json"
    for p in (rp["nt"], pairs):
        if not p.exists(): return {"scenario": scenario, "status": "INPUT_NOT_FOUND", "expected_path": str(p)}
    nt_sha = sha256(rp["nt"])
    if crep.exists() and json.loads(crep.read_text(encoding="utf-8"))["nt_sha256"] != nt_sha: raise ValueError(f"pairs.csv {scenario} tidak cocok dengan graf saat ini (jalankan ulang stage 07)")
    graph = digest.load_graph(rp["nt"]); pairs_sha = sha256(pairs)
    base = config.unit_dir(unit, root) / "08_digest" / scenario; index = {"scenario": scenario, "unit": unit, "nt_sha256": nt_sha, "pairs_csv_sha256": pairs_sha, "units": {}}
    for u in tasks.units(scenario, unit, tasks_dir):
        if only and u["unit_id"] not in only: continue
        sf = set(u["source_files"]) if u["source_files"] is not None else None
        sel = [v for v in graph[0].values() if sf is None or v.get("hasSourceFile", [""])[0] in sf]
        if not sel:
            index["units"][u["unit_id"]] = {"status": "SOURCE_FILE_NOT_IN_RDF", "source_files": sorted(sf)}; continue
        if not any("hasTimestamp" in v for v in sel):                     # aturan digest lama (D3/D8) hanya memakai event berwaktu valid
            index["units"][u["unit_id"]] = {"status": NO_TIMED, "source_files": sorted(sf) if sf else "ALL", "events": len(sel),
                                            "note": "semua event tanpa timestamp valid; digest tidak dapat dibangun dengan aturan lama (tidak diubah). Unit dilewati di stage 09/11; pengambilan SPARQL (stage 06) tetap dievaluasi."}
            continue
        res = digest.build(rp["nt"], pairs, source_files=sf, graph=graph); out = base / u["unit_id"]
        rep = dict(res["report"], scenario=scenario, unit=unit, unit_id=u["unit_id"], tasks=[t["task"] for t in u["tasks"]],
                   source_files=sorted(sf) if sf else "ALL", status="OK", nt_sha256=nt_sha, pairs_csv_sha256=pairs_sha)
        digest.write_atomic(out / "digest.txt", res["text"])
        digest.write_atomic(out / "digest_evidence.json", json.dumps({"scenario": scenario, "unit_id": u["unit_id"], "evidence": res["evidence"]}, indent=1, ensure_ascii=False) + "\n")
        digest.write_atomic(out / "digest_report.json", json.dumps(rep, indent=1, ensure_ascii=False) + "\n")
        index["units"][u["unit_id"]] = {k: rep[k] for k in ("status", "chars", "approx_tokens_chars_div4", "evidence_items", "r1_items", "canonical_events", "over_budget", "digest_sha256")}
    groups = {}
    for uid, v in index["units"].items():
        if v.get("status") == "OK": groups.setdefault(v["digest_sha256"], []).append(uid)
    index["identical_digest_groups"] = [g for g in groups.values() if len(g) > 1]
    index["status"] = "OK"
    digest.write_atomic(base / "digest_index.json", json.dumps(index, indent=1, ensure_ascii=False) + "\n")
    return index


def main():
    st = config.load_settings()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scenario", required=True, choices=["1", "2", "3", "all"]); ap.add_argument("--unit", choices=["task", "scenario"], default=st["unit_default"])
    ap.add_argument("--unit-id", action="append", help="hanya unit ini (boleh berulang); untuk verifikasi terarah"); ap.add_argument("--variant", help="tulis ke results/unit_<unit>__<variant> (baseline tidak tersentuh)")
    a = ap.parse_args(); config.set_variant(a.variant); bad = False
    if a.unit_id and not a.variant: ap.error("--unit-id (hasil parsial) wajib disertai --variant agar digest_index baseline tidak tertimpa")
    for s in config.scenario_list(a.scenario):
        r = run_scenario(s, a.unit, only=set(a.unit_id) if a.unit_id else None)
        if r["status"] != "OK": print(f"[{s}] {r['status']}: {r['expected_path']}"); bad = True; continue
        for uid, v in r["units"].items():
            if v["status"] == NO_TIMED: print(f"[{s}] {uid}: {NO_TIMED} ({v['events']} event, 0 berwaktu valid) - digest TIDAK dibangun; unit dilewati di stage 09/11 (lihat docs/METHODOLOGY.md)"); continue
            if v["status"] != "OK": print(f"[{s}] {uid}: {v['status']} {v.get('source_files')}"); bad = True; continue
            print(f"[{s}] {uid}: chars={v['chars']} (~{v['approx_tokens_chars_div4']} tok) evidence={v['evidence_items']} r1={v['r1_items']} canonical={v['canonical_events']} over_budget={v['over_budget']} sha256={v['digest_sha256'][:12]}")
        if r["identical_digest_groups"]: print(f"[{s}] digest identik (data sumber sama; dievaluasi terpisah per tugas): {r['identical_digest_groups']}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
