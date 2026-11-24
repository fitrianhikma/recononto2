"""STAGE 06 - Validitas pengambilan SPARQL terhadap ground truth resmi S2/S3 (kode lama 04_eval_retrieval.py + tambahan V1).
Tambahan V1 (metode lama tetap dijalankan dan dilaporkan, tidak diganti):
  S2 regex-literal-bracket(Q13): kata kunci dibaca dengan keywords.literal_brackets (lihat docstring modul itu).
  S3 regex-paper(Q17): pola grep -E dari paper dataset (config/pipeline.json s3_grep_patterns) pada pesan ATAU display_name.
  F1 ditambahkan pada setiap metode. Keluaran: results/06_retrieval/.

PHASE 4B (B2) - Validitas PENGAMBILAN event ground truth resmi lewat SPARQL (bukan evaluasi korelasi/laporan).

S2 (tasks/keyword-analysis): kunci dari additional-keywords.json -> regex (Q13), literal (Q14), struktur (Q12) bila kunci berpola EVTX.
    Identitas = (datetime mentah, 100 karakter pesan); juga tingkat ISI (abaikan datetime).
S3 (tasks/grep): needle = token nama berkas tugas sebelum '-' pertama (ASUMSI: pola grep asli tidak ada di tasks); Q14 pada pesan/display_name.
    Q12 ditambahkan bila SEMUA baris GT adalah event EVTX berpasangan (provider, ID) sama (diurai dari baris GT). Identitas baris = (datetime, timestamp_desc, pesan[:100], display_name).
Ruang pencarian = berkas events tugas itu (hasSourceFile); hasil di seluruh graf dilaporkan terpisah.
    python3 src/04_eval_retrieval.py --scenario all [--tasks data/tasks]"""
import argparse, csv, glob, json, os, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config, keywords, sparql_common as sc

_run = sc.run_template


def _methods_result(rows, sf, keyfn, gt_keys, contentfn=None, gt_content=None):
    inf = [keyfn(r) for r in rows if r["file"] == sf]
    d = sc.prf(list(set(inf)) if contentfn else inf, gt_keys)
    d["retrieved_whole_scenario"] = len({keyfn(r) for r in rows}) if contentfn else len(rows)
    if contentfn: d["content_level"] = sc.prf(list({contentfn(r) for r in rows if r["file"] == sf}), gt_content)
    fn = sorted(set(gt_keys) - set(inf))[:5]; fp = sorted(set(inf) - set(gt_keys))[:5]
    d["missed_examples"], d["extra_examples"] = [list(x) for x in fn], [list(x) for x in fp]
    return d


def eval_s2(g, tasks, qdir=None, run=None) -> dict:
    run = run or _run; out = {}
    kws = json.loads((Path(tasks) / "keyword-analysis" / "additional-keywords.json").read_text(encoding="utf-8"))
    for fp in sorted(glob.glob(str(Path(tasks) / "keyword-analysis" / "ground-truth" / "*.json"))):
        sf = os.path.basename(fp).replace(".json", ".csv"); items = json.loads(Path(fp).read_text(encoding="utf-8"))
        ev = items[0]["event"]; found = [k["keyword"] for k in kws if k["event"] == ev]
        if not found: out[os.path.basename(fp)] = {"error": f"kunci untuk event {ev!r} tidak ada di additional-keywords.json"}; continue
        kw = found[0]; G = [(x["datetime"], x["message"][:100]) for x in items]; Gset = set(G); gc_ = {x[1] for x in Gset}
        res = {"keyword_event": ev, "keyword": kw, "gt_items": len(items), "gt_distinct_events": len(Gset), "methods": {}}
        meths = {"regex(Q13)": ("Q13_message_regex", {"pattern": kw}), "literal(Q14)": ("Q14_message_literal", {"needle": kw})}
        meths["regex-literal-bracket(Q13)"] = ("Q13_message_regex", {"pattern": keywords.literal_brackets(kw)})        # V1
        pair = sc.evtx_pair(kw)
        if pair: meths["struktur(Q12 provider+EventID)"] = ("Q12_by_provider_eventid", {"provider": pair[0], "eid": pair[1]})
        for name, (qn, params) in meths.items():
            try: rows = run(g, qn, queries_dir=qdir, **params)
            except Exception as e: res["methods"][name] = {"error": repr(e)[:120]}; continue
            res["methods"][name] = _methods_result(rows, sf, lambda r: (r["ts_raw"], r["msg"][:100]), list(Gset), lambda r: r["msg"][:100], gc_)
        out[os.path.basename(fp)] = res
    return out


def gt_lines(fp):
    rows = []
    for l in Path(fp).read_text(encoding="utf-8", errors="replace").splitlines():
        if not l.strip(): continue
        try: f = next(csv.reader([l]))
        except Exception: continue
        if len(f) >= 7: rows.append((f[0], f[1], f[4][:100], f[6], f[4]))          # (datetime, timestamp_desc, pesan[:100], display_name, pesan penuh)
    return rows


def eval_s3(g, tasks, qdir=None, run=None, patterns=None) -> dict:
    run = run or _run; out = {}; patterns = patterns if patterns is not None else {k: v for k, v in config.load_settings()["s3_grep_patterns"].items() if not k.startswith("_")}
    key = lambda r: (r["ts_raw"], r["tsd"], r["msg"][:100], r["disp"])
    for fp in sorted(glob.glob(str(Path(tasks) / "grep" / "ground-truth" / "*.txt"))):
        stem = os.path.basename(fp)[:-4]; sf = stem + ".csv"; full = gt_lines(fp); G = [x[:4] for x in full]
        needle = stem.split("-")[0]
        res = {"gt_lines": len(G), "gt_distinct_rows": len(set(G)), "needle_ASSUMED_from_filename": needle, "methods": {}}
        try:
            rows = run(g, "Q14_message_literal", queries_dir=qdir, needle=needle); res["methods"]["literal(Q14) msg|display_name"] = _methods_result(rows, sf, key, G)
        except Exception as e: res["methods"]["literal(Q14) msg|display_name"] = {"error": repr(e)[:120]}
        if stem in patterns:                                                    # V1: pola grep paper
            res["paper_pattern"] = patterns[stem]
            try:
                rows = run(g, "Q17_grep_regex", queries_dir=qdir, pattern=patterns[stem]); res["methods"]["regex-paper(Q17) msg|display_name"] = _methods_result(rows, sf, key, G)
            except Exception as e: res["methods"]["regex-paper(Q17) msg|display_name"] = {"error": repr(e)[:120]}
        pairs = {sc.evtx_pair(x[4]) for x in full}
        if full and len(pairs) == 1 and None not in pairs:                       # semua baris GT = event EVTX dengan pasangan sama
            prov, eid = next(iter(pairs)); res["evtx_pair_from_gt"] = [prov, eid]
            try:
                rows = run(g, "Q12_by_provider_eventid", queries_dir=qdir, provider=prov, eid=eid); res["methods"]["struktur(Q12 provider+EventID dari GT)"] = _methods_result(rows, sf, key, G)
            except Exception as e: res["methods"]["struktur(Q12 provider+EventID dari GT)"] = {"error": repr(e)[:120]}
        out[stem] = res
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", required=True, choices=["2", "3", "all"])
    ap.add_argument("--tasks", default=str(config.TASKS_DIR)); ap.add_argument("--queries", default=str(config.QUERIES_DIR))
    a = ap.parse_args(); fn = {"scenario2": eval_s2, "scenario3": eval_s3}
    for s in (["scenario2", "scenario3"] if a.scenario == "all" else [f"scenario{a.scenario}"]):
        rp = config.rdf_paths(s)
        if not rp["nt"].exists(): print(f"[{s}] RDF_NOT_FOUND: {rp['nt']}"); continue
        g = sc.load_graph(rp["nt"]); res = {"scenario": s, "assumptions": ["S3 literal(Q14): needle = token nama berkas sebelum '-' pertama (metode lama, dipertahankan)",
                                              "S3 regex-paper(Q17): pola dari paper dataset; pola OneDrive disimpulkan (lihat config/pipeline.json)",
                                              "S2 regex-literal-bracket: operasionalisasi V1, lihat src/keywords.py",
                                              "Q12 untuk S3 hanya bila semua baris GT berpasangan (provider, Event ID) sama"], "tasks": fn[s](g, a.tasks, a.queries)}
        out = config.RESULTS / "06_retrieval" / f"retrieval_{s}.json"; out.parent.mkdir(parents=True, exist_ok=True); tmp = out.with_name(out.name + ".tmp")
        tmp.write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8"); os.replace(tmp, out)
        for t, v in res["tasks"].items():
            for m, d in v.get("methods", {}).items(): print(f"[{s}] {t} | {m}: " + (d["error"] if "error" in d else f"P={d['precision']} R={d['recall']} F1={d['f1']} tp={d['tp']}/{d['gt']} (seluruh graf {d['retrieved_whole_scenario']})"))
        del g


if __name__ == "__main__":
    main()
