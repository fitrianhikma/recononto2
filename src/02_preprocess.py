"""STAGE 02 - Preprocessing (kode lama 02b_preprocess_events.py; logika tidak diubah, hanya lokasi keluaran).

    python3 src/02_preprocess.py --scenario {1,2,3,all}
Keluaran: results/02_preprocess/scenarioN/official_events_classified.csv + results/02_preprocess/preprocess_report_scenarioN.json

PHASE 2.1 - Preprocessing untuk file resmi timeline/events/*.csv (gabungan per skenario).

Memakai Classifier/ekstraksi/status timestamp dari 02_preprocess.py tanpa duplikasi logika.
Tidak ada dedup, tidak ada filter, tidak ada baris dibuang. Header ganda dicatat, bukan dihitung sebagai event.

    python3 src/02b_preprocess_events.py --scenario all
    python3 src/02b_preprocess_events.py --scenario 1 --rules src/event_rules_v2.csv
"""
import argparse, csv, json, os, sys, time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config, events_reader

import classifier as pre                      # dulu: importlib dari 02_preprocess.py (isi sama)

EXTRA = ["source_file", "row_in_file", "row_hash"]
OUT_COLUMNS = pre.OUT_COLUMNS + EXTRA


def sha256_file(p: Path) -> str:
    return pre.sha256_file(p)


def build_row(row_id: int, rec: dict, clf) -> list:
    dt, tsd, src, srcl, msg, parser, disp, _tag = rec["cols"]
    status = pre.timestamp_status(dt, tsd)
    etype, rid = clf.classify(parser, tsd, msg)
    derived = pre.extract_fields(parser, msg)
    return [row_id, dt, pre.normalize_dt(dt) if status == "valid" else "", status, tsd, etype, rid, src, srcl, parser, *derived, msg, disp,
            rec["source_file"], rec["row_in_file"], rec["row_hash"]]


def verify_output(out_path: Path, records: list, clf) -> dict:
    csv.field_size_limit(1 << 30)
    mism, first, n = 0, None, 0
    with open(out_path, newline="", encoding="utf-8") as f:
        rd = csv.reader(f); hdr = next(rd)
        if hdr != OUT_COLUMNS: return {"ok": False, "error": "header output tidak sesuai"}
        io_ = {c: i for i, c in enumerate(hdr)}
        for i, (row, rec) in enumerate(zip(rd, records), 1):
            n += 1; c = rec["cols"]
            bad = None
            if row[io_["row_id"]] != str(i): bad = "row_id"
            elif row[io_["datetime_raw"]] != c[0]: bad = "datetime_raw"
            elif [row[io_[k]] for k in ("timestamp_desc", "source", "source_long", "message", "parser", "display_name")] != [c[1], c[2], c[3], c[4], c[5], c[6]]: bad = "kolom verbatim"
            elif (row[io_["timestamp_clean"]] != "") != (row[io_["timestamp_status"]] == "valid"): bad = "timestamp_clean/status"
            elif row[io_["event_type"]] not in clf.event_types or (row[io_["rule_id"]] == "") != (row[io_["event_type"]] == pre.UNCLASSIFIED): bad = "event_type/rule_id"
            elif (row[io_["source_file"]], row[io_["row_in_file"]], row[io_["row_hash"]]) != (rec["source_file"], str(rec["row_in_file"]), rec["row_hash"]): bad = "source_file/row_in_file/row_hash"
            if bad:
                mism += 1; first = first or {"row": i, "reason": bad}
    return {"ok": mism == 0 and n == len(records), "rows_checked": n, "mismatches": mism, "first_mismatch": first}


def process_scenario(scenario: str, rules_path: Path, root=None, out_path=None, report_path=None, legacy_all_events=None) -> dict:
    paths = config.scenario_paths(scenario, root)
    ev_dir = paths["events_dir"]
    if not ev_dir.exists() or not list(ev_dir.glob("*.csv")):
        return {"scenario": scenario, "status": "RAW_NOT_FOUND", "expected_path": str(ev_dir)}
    t0 = time.time()
    clf = pre.Classifier(rules_path)
    records, infos = events_reader.read_scenario_events(ev_dir)
    out_path = Path(out_path) if out_path else paths["processed_dir"] / config.OFFICIAL_PROCESSED
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_name(out_path.name + ".tmp")
    ev, ts, hits, uncl, parsers = Counter(), Counter(), Counter(), Counter(), Counter()
    sep_space = tag_non_dash = 0
    try:
        with open(tmp, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f, lineterminator="\n"); w.writerow(OUT_COLUMNS)
            for i, rec in enumerate(records, 1):
                row = build_row(i, rec, clf); w.writerow(row)
                ev[row[5]] += 1; ts[row[3]] += 1; parsers[row[9]] += 1
                if row[6]: hits[row[6]] += 1
                else: uncl[row[9]] += 1
                c = rec["cols"]
                sep_space += c[0][10:11] == " " and c[0][:4].isdigit()
                tag_non_dash += c[7] != "-"
        os.replace(tmp, out_path)
    finally:
        if tmp.exists(): tmp.unlink()
    rep = {"scenario": scenario, "status": "OK", "rules_path": str(rules_path), "rules_sha256": sha256_file(Path(rules_path)),
           "rows_in": len(records), "rows_out": len(records), "files": len(infos), "per_file": infos,
           "header_fused_files": [x["file"] for x in infos if x["header_fused"]],
           "duplicate_header_rows": [x["file"] for x in infos if x["duplicate_header_row"]],
           "datetime_space_separator_rows": sep_space, "tag_not_dash_rows": tag_non_dash,
           "row_hash_unique": len({r["row_hash"] for r in records}), "parser_count": len(parsers),
           "event_type": dict(ev.most_common()), "timestamp_status": {k: ts.get(k, 0) for k in pre.TS_STATUSES},
           "rule_hits": dict(sorted(hits.items())), "unclassified_total": ev.get(pre.UNCLASSIFIED, 0),
           "unclassified_by_parser": dict(uncl.most_common()), "output_path": str(out_path),
           "output_bytes": out_path.stat().st_size, "output_sha256": sha256_file(out_path)}
    rep["verification"] = verify_output(out_path, records, clf)
    if legacy_all_events and Path(legacy_all_events).exists():           # INFORMASI SAJA, bukan target
        with open(legacy_all_events, newline="", encoding="utf-8") as f:
            rd = csv.reader(f); next(rd); old = Counter(tuple(r) for r in rd)
        new = Counter(tuple(r["cols"]) for r in records)
        rep["legacy_all_events_comparison_INFO_ONLY"] = {"legacy_rows": sum(old.values()), "identical_multiset": old == new,
                                                           "rows_only_in_events": sum((new - old).values()), "rows_only_in_legacy": sum((old - new).values())}
    rep["elapsed_sec"] = round(time.time() - t0, 1)
    rp = Path(report_path) if report_path else config.preprocess_report_path(scenario, root)
    rp.parent.mkdir(parents=True, exist_ok=True)
    rp.write_text(json.dumps(rep, indent=2, ensure_ascii=False), encoding="utf-8")
    return rep


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", required=True, choices=["1", "2", "3", "all"])
    ap.add_argument("--rules", default=str(config.RULES_V2))
    ap.add_argument("--out", default=None, help="path output (hanya untuk satu skenario)")
    ap.add_argument("--legacy-all-events", default=None, help="all_events.csv lama (perbandingan informasi, S1)")
    a = ap.parse_args()
    scs = config.SCENARIOS if a.scenario == "all" else [f"scenario{a.scenario}"]
    if a.out and len(scs) != 1: ap.error("--out hanya untuk satu skenario")
    for s in scs:
        r = process_scenario(s, Path(a.rules), out_path=a.out, legacy_all_events=a.legacy_all_events if s == "scenario1" else None)
        if r["status"] != "OK": print(f"[{s}] {r['status']}: {r['expected_path']}"); continue
        print(f"[{s}] files={r['files']} rows_in={r['rows_in']} rows_out={r['rows_out']} row_hash_unique={r['row_hash_unique']} parsers={r['parser_count']} "
              f"unclassified={r['unclassified_total']} verify_ok={r['verification']['ok']} fused={r['header_fused_files']} dup_header={r['duplicate_header_rows']}")


if __name__ == "__main__":
    main()
