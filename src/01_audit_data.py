"""STAGE 01 - Audit data dan ground truth (HANYA MEMBACA; tidak ada berkas dataset yang diubah, tidak ada GT yang dibuat).

    python3 src/01_audit_data.py --scenario {1,2,3,all}
Per skenario: SHA-256 dan jumlah baris tiap berkas events, cacat format (header menyatu/ganda; ditangani events_reader lama),
kelompok berkas berisi identik, tugas dan berkas tanpa GT, jumlah butir GT mentah vs unik (identitas keputusan (c)),
lokalisasi GT -> baris events (pemetaan lama D24), S1 single subset multiple, diagnosis kata kunci S2 (as-is vs literal-bracket),
reproduksi grep S3 (pola paper pada baris CSV mentah), serta hitungan unit dan panggilan LLM yang diharapkan.
Keluaran: results/01_audit/audit_scenarioN.json + audit_summary.md
"""
import argparse, hashlib, json, re, sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config, events_reader as er, keywords, report_metrics as rm, tasks as tk


def audit_files(ev_dir: Path) -> dict:
    files, groups = [], {}
    for fp in er.list_event_files(ev_dir):
        rows, info = er.read_events_file(fp); sha = hashlib.sha256(fp.read_bytes()).hexdigest()
        content = hashlib.sha256("\n".join("\x1f".join(r) for r in rows).encode("utf-8", "surrogatepass")).hexdigest()
        files.append({"file": fp.name, "rows": len(rows), "sha256": sha, "content_sha256": content, **info,
                      "row_hash_unique": len({er.row_hash(r) for r in rows}), "datetime_space_separator": sum(1 for r in rows if r[0][10:11] == " ")})
        groups.setdefault(content, []).append(fp.name)
    return {"files": files, "identical_content_groups": [g for g in groups.values() if len(g) > 1], "distinct_contents": len(groups)}


def audit_gt(scenario: str, rows: list, tasks_dir) -> dict:
    out = {}; ts = tk.list_tasks(scenario, tasks_dir); idx = rm.index_rows(rows)
    old = rm.load_gt_tasks(scenario, Path(tasks_dir), rows)
    for t in ts:
        items = tk.read_gt(t, "single"); name = t["task"]
        hs = [x["hashes"] for x in old[name]] if scenario != "scenario3" else None
        g = tk.group_items(scenario, items, hs)
        d = {"gt_items_raw": len(items), "gt_items_unique": len(g)}
        if scenario != "scenario3":
            d.update({"unresolved_items": sum(1 for x in old[name] if not x["hashes"]), "ambiguous_items_gt1_rowhash": sum(1 for x in old[name] if len(x["hashes"]) > 1)})
        if scenario == "scenario1":
            mi = tk.read_gt(t, "multiple"); gm = tk.group_items(scenario, mi)
            ks = {x["identity"] for x in g}; km = {x["identity"] for x in gm}
            d.update({"multiple_items_raw": len(mi), "multiple_items_unique": len(gm), "single_subset_of_multiple": ks <= km,
                      "single_types": dict(Counter(x["item"].get("type") for x in g)), "multiple_types": dict(Counter(x["item"].get("type") for x in gm)),
                      "multiple_unresolved_items": sum(1 for x in rm.gt_s1(mi, t["source_file"], idx) if not x["hashes"])})
        out[name] = d
    return out


def audit_s2_keywords(rows: list, tasks_dir) -> dict:
    kws = json.loads((Path(tasks_dir) / "keyword-analysis" / "additional-keywords.json").read_text(encoding="utf-8")); out = {}
    for t in tk.list_tasks("scenario2", tasks_dir):
        items = tk.read_gt(t, "single"); ev = items[0]["event"] if items else None; kw = next((k["keyword"] for k in kws if k["event"] == ev), None)
        if kw is None: out[t["task"]] = {"error": f"kata kunci untuk {ev!r} tidak ada"}; continue
        msgs = [r for r in rows if r["source_file"] == t["source_file"]]; G = {tk.identity("scenario2", it) for it in items}
        res = {"event": ev, "keyword": kw, "gt_unique": len(G)}
        for name, pat in (("as_is", kw), ("literal_bracket", keywords.literal_brackets(kw))):
            if not keywords.compiles(pat): res[name] = {"error": "regex tidak valid"}; continue
            hit = [r for r in msgs if re.search(pat, r["message"])]; R = {tk.identity("scenario2", {"datetime": r["datetime_raw"], "message": r["message"]}) for r in hit}
            res[name] = {"pattern": pat, "rows_matched": len(hit), "unique_matched": len(R), "tp_unique": len(R & G)}
        out[t["task"]] = res
    return out


def audit_s3_grep(ev_dir: Path, tasks_dir) -> dict:
    pats = {k: v for k, v in config.load_settings()["s3_grep_patterns"].items() if not k.startswith("_")}; out = {}
    for t in tk.list_tasks("scenario3", tasks_dir):
        fp = ev_dir / t["source_file"]; pat = pats.get(t["task"])
        if not fp.exists() or not pat: out[t["task"]] = {"error": "berkas events atau pola tidak ada"}; continue
        lines = fp.read_text(encoding="utf-8", errors="replace").splitlines()[1:]               # grep -E pada berkas mentah tanpa baris header pertama
        hit = Counter(l for l in lines if re.search(pat, l)); gt = Counter(tk.read_gt(t, "single"))
        out[t["task"]] = {"pattern": pat, "grep_matches": sum(hit.values()), "gt_lines": sum(gt.values()), "exact_multiset_match": hit == gt,
                          "gt_not_in_grep": sum((gt - hit).values()), "grep_not_in_gt": sum((hit - gt).values())}
    return out


def main():
    st = config.load_settings()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scenario", required=True, choices=["1", "2", "3", "all"]); ap.add_argument("--tasks", default=str(config.TASKS_DIR)); a = ap.parse_args()
    out = config.RESULTS / "01_audit"; out.mkdir(parents=True, exist_ok=True); md = ["# Audit data dan ground truth (stage 01, hanya membaca)", ""]; tot_tasks = tot_data = 0
    for s in config.scenario_list(a.scenario):
        ev = config.scenario_paths(s)["events_dir"]
        if not ev.exists(): print(f"[{s}] RAW_NOT_FOUND: {ev}"); continue
        rep = {"scenario": s, **audit_files(ev)}; rows = tk.raw_rows_for_mapping(ev)
        ts = tk.list_tasks(s, a.tasks); rep["tasks"] = [t["task"] for t in ts]
        rep["event_files_without_gt"] = sorted({f["file"] for f in rep["files"]} - {t["source_file"] for t in ts})
        rep["ground_truth"] = audit_gt(s, rows, a.tasks)
        if s == "scenario2": rep["s2_keyword_diagnosis"] = audit_s2_keywords(rows, a.tasks)
        if s == "scenario3": rep["s3_grep_reproduction"] = audit_s3_grep(ev, a.tasks)
        task_files = {t["source_file"] for t in ts}; contents = {f["content_sha256"] for f in rep["files"] if f["file"] in task_files}
        rep["units"] = {"task_units": len(ts), "data_units_distinct_content_among_task_files": len(contents),
                        "expected_reports_per_model": len(ts) * len(st["strategies"]), "note": "panggilan LLM berbeda dihitung pasti oleh stage 09 (prompt identik dipakai ulang)"}
        tot_tasks += len(ts); tot_data += len(contents)
        (out / f"audit_{s}.json").write_text(json.dumps(rep, indent=1, ensure_ascii=False), encoding="utf-8")
        md += [f"## {s}", "", f"- berkas events: {len(rep['files'])}; isi berbeda: {rep['distinct_contents']}; kelompok isi identik: {rep['identical_content_groups'] or '-'}",
               f"- header menyatu: {[f['file'] for f in rep['files'] if f['header_fused']] or '-'}; header ganda: {[f['file'] for f in rep['files'] if f['duplicate_header_row']] or '-'}",
               f"- tugas: {len(ts)}; berkas tanpa GT: {rep['event_files_without_gt'] or '-'}", "", "| tugas | GT mentah | GT unik | catatan |", "|---|---|---|---|"]
        for tn, g in rep["ground_truth"].items():
            note = []
            if "unresolved_items" in g: note.append(f"tak terlokalisasi {g['unresolved_items']}, ambigu {g['ambiguous_items_gt1_rowhash']}")
            if "single_subset_of_multiple" in g: note.append(f"multiple {g['multiple_items_raw']}/{g['multiple_items_unique']} unik; single subset multiple={g['single_subset_of_multiple']}")
            md.append(f"| {tn} | {g['gt_items_raw']} | {g['gt_items_unique']} | {'; '.join(note)} |")
        if s == "scenario2":
            md += ["", "Diagnosis kata kunci S2 (tp = butir GT unik yang tertangkap regex pada pesan berkas tugas):", "", "| tugas | GT unik | as-is cocok/tp | literal-bracket cocok/tp |", "|---|---|---|---|"]
            for tn, d in rep["s2_keyword_diagnosis"].items():
                if "error" in d: md.append(f"| {tn} | - | {d['error']} | |"); continue
                md.append(f"| {tn} | {d['gt_unique']} | {d['as_is'].get('rows_matched')}/{d['as_is'].get('tp_unique')} | {d['literal_bracket'].get('rows_matched')}/{d['literal_bracket'].get('tp_unique')} |")
        if s == "scenario3":
            md += ["", "Reproduksi grep S3 (pola paper pada baris CSV mentah):", "", "| tugas | cocok grep | baris GT | identik |", "|---|---|---|---|"]
            for tn, d in rep["s3_grep_reproduction"].items(): md.append(f"| {tn} | {d.get('grep_matches')} | {d.get('gt_lines')} | {d.get('exact_multiset_match')} |")
        md += [""]; print(f"[{s}] berkas={len(rep['files'])} tugas={len(ts)} isi_identik={rep['identical_content_groups']} tanpa_GT={rep['event_files_without_gt']}")
    n_models = len(st["models"]); n_p = len(st["strategies"])
    md += ["## Hitungan unit", "", f"- unit tugas: {tot_tasks}; unit data (isi berkas tugas berbeda): {tot_data}",
           f"- laporan yang dievaluasi: {tot_tasks} x {n_p} x {n_models} = {tot_tasks * n_p * n_models}",
           f"- panggilan LLM: paling banyak {tot_tasks * n_p * n_models}; jumlah pasti (setelah prompt identik dipakai ulang) dicetak stage 09.", ""]
    (out / "audit_summary.md").write_text("\n".join(md), encoding="utf-8"); print(f"-> {out / 'audit_summary.md'}")


if __name__ == "__main__":
    main()
