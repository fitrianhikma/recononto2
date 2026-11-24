"""STAGE 12 - Evaluasi laporan LLM. M0-M8 dihitung oleh fungsi lama (report_metrics.evaluate_run, tidak diubah); metrik tambahan V1
(extra_metrics.py) ditulis sebagai kolom baru. Bisa dijalankan sebelum ada run LLM: cakupan ground truth oleh digest tetap dilaporkan.

    python3 src/12_evaluate.py [--unit task|scenario] [--scenario all] [--unit-id ID ...] [--variant NAMA]
Masukan : results/unit_<unit>/{08_digest,09_prompts,11_llm}, results/02_preprocess (pemetaan GT -> rowHash), data/tasks (GT resmi, hanya dibaca)
Keluaran: results/unit_<unit>/12_eval/{runs_wide.csv, metrics_long.csv, summary_by_scenario.csv, summary_overall.csv, summary_deltas.csv,
          failures.csv, report_validity.csv (validation_v2, tambahan), gt_coverage.json, eval_report.md}
Satu run per kondisi: tidak ada uji signifikansi; seluruh angka deskriptif.
"""
import argparse, csv, glob, hashlib, json, sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config, events_reader as er, extra_metrics as xm, report_metrics as rm, report_validation as rv, tasks as tk

META = ["model", "backend", "strategy", "scenario", "unit", "unit_id", "tasks", "llm_call", "reused_from", "finish_reason", "prompt_tokens", "completion_tokens", "duration_s"]
TASK_COLS = ["t_gt_items_raw", "t_gt_items_unique", "t_gt_unique_in_digest", "t_gt_unique_unmapped", "t_precision", "t_recall", "t_f1",
             "t_recall_weighted", "t_recall_conditional", "t_recall_mention"]
S1_MULTI = ["tm_gt_items_raw", "tm_gt_items_unique", "tm_gt_unique_in_digest", "tm_recall", "tm_recall_weighted", "tm_recall_conditional", "tm_recall_mention"]
LEX = ["bleu", "bleu_smooth1", "rouge1_f", "rouge2_f", "rougeL_f", "mean_bleu_rouge", "reference_valid", "ref_tokens", "hyp_tokens"]
LEX_COLS = LEX + ["tl_" + c for c in LEX] + ["lib_bleu_nltk", "lib_bleu_nltk_smooth1", "lib_rouge1_f", "lib_rouge2_f", "lib_rougeL_f"]
EXTRA = TASK_COLS + S1_MULTI + LEX_COLS
ALL = rm.WANT + EXTRA
KEY_COLS = ["m0_structure", "m1_citation_valid_ratio", "m2_unsupported_rate_all", "m3_evidence_coverage", "m5_recall_report", "m6b_degenerate_echo",
            "t_precision", "t_recall", "t_f1", "bleu", "rouge1_f", "rouge2_f", "rougeL_f", "mean_bleu_rouge"]


def s3_hashes(lines: list) -> list:
    """Sama dengan gt_s3 lama (baris CSV 8 kolom -> rowHash persis), tetapi selalu satu entri per baris agar urutannya sejajar."""
    out = []
    for l in lines:
        try: f = next(csv.reader([l]))
        except Exception: f = []
        out.append({er.row_hash(f)} if len(f) == 8 else set())
    return out


def load_gt(scenario: str, tasks_dir: Path, root=None) -> dict:
    """-> {task: {'old': [..] (masukan M5 lama), 'groups': [...], 'groups_multi': [...]|None, 'items': [...]}}"""
    rows = tk.read_processed_rows(scenario, root); old = rm.load_gt_tasks(scenario, tasks_dir, rows); idx = rm.index_rows(rows); out = {}
    for t in tk.list_tasks(scenario, tasks_dir):
        items = tk.read_gt(t, "single"); name = t["task"]
        hs = s3_hashes(items) if scenario == "scenario3" else [x["hashes"] for x in old[name]]
        d = {"old": old[name], "items": items, "groups": tk.group_items(scenario, items, hs), "groups_multi": None}
        if scenario == "scenario1" and t.get("gt_multiple_path"):
            mi = tk.read_gt(t, "multiple"); d["groups_multi"] = tk.group_items(scenario, mi, [x["hashes"] for x in rm.gt_s1(mi, t["source_file"], idx)])
        out[name] = d
    return out


def evaluate_one(run: dict, scenario: str, unit_tasks: list, gt: dict, digest: str, evidence: list, prompt: str, terms: dict, st: dict) -> dict:
    text = run["text"]; M = rm.evaluate_run(text, digest, evidence, {t: gt[t]["old"] for t in unit_tasks}, prompt, run.get("finish_reason"), terms)["metrics"]
    cited, mentioned = xm.cited_and_mentioned(text, evidence)
    groups = [g for t in unit_tasks for g in gt[t]["groups"]]
    if scenario == "scenario1":
        prec = set().union(*[g["hashes"] for t in unit_tasks for g in (gt[t]["groups_multi"] or gt[t]["groups"])])
    else: prec = set().union(*[g["hashes"] for g in groups]) if groups else set()
    M.update(xm.task_metrics(groups, evidence, cited, mentioned, prec, "t_"))
    if scenario == "scenario1":
        gm = [g for t in unit_tasks for g in (gt[t]["groups_multi"] or [])]
        if gm:
            x = xm.task_metrics(gm, evidence, cited, mentioned, prec, "tm_")
            M.update({k: x[k] for k in S1_MULTI})
        ev = st["evaluation"]; ref = tk.s1_reference_lines([it for t in unit_tasks for it in gt[t]["items"]])
        M.update(xm.lexical_scores(text, ref, ev["bleu_max_n"], ev["min_reference_tokens"]))
        M.update(xm.lexical_scores(rm.split_sections(text).get("TIMELINE", ""), ref, ev["bleu_max_n"], ev["min_reference_tokens"], prefix="tl_"))
        M.update(xm.library_scores(text, ref))
    return M


def collect(unit: str, scenario: str) -> tuple:
    base = config.unit_dir(unit) / "11_llm"; ok, failed = [], []
    for fp in sorted(glob.glob(str(base / "*" / scenario / "*" / "P*.json"))):
        d = json.loads(Path(fp).read_text(encoding="utf-8"))
        if fp.endswith(".failed.json"): failed.append(d)
        elif d.get("status") == "OK": ok.append(d)
    return ok, failed


def mean(xs):
    xs = [x for x in xs if x is not None]; return sum(xs) / len(xs) if xs else None


def subset_rows(rows, subset):
    if subset == "all": return rows
    if subset == "pure": return [r for r in rows if r["m"].get("pure") == 1.0]
    by = defaultdict(dict)
    for r in rows: by[(r["model"], r["scenario"], r["unit_id"])][r["strategy"]] = r
    keep = []
    for g in by.values():
        if set(g) >= {"P1", "P2", "P3"} and (subset == "paired" or all(g[p]["m"].get("pure") == 1.0 for p in ("P1", "P2", "P3"))): keep += [g[p] for p in ("P1", "P2", "P3")]
    return keep


def write_csv(path, header, rows): rm.write_csv(Path(path), header, rows)


def report_md(unit, rows, failed, coverage, notes) -> str:
    L = [f"# Evaluasi laporan LLM (unit={unit}; dibangkitkan dari data)", "",
         f"Run sah: {len(rows)}; kegagalan tercatat: {len(failed)}. Satu run per kondisi (temperatur 0): **tidak ada uji signifikansi**; seluruh angka deskriptif.", "",
         "## Peringatan wajib", "",
         "- **Presisi S1 (`t_precision`, skenario 1) adalah BATAS BAWAH.** Ground truth event-summarization hanya mencakup 8 jenis event tingkat tinggi yang didefinisikan dftpl; "
         "event valid di luar jenis itu yang dikutip laporan dihitung bukan-GT. Presisi S1 dihitung terhadap GT `multiple` berkas yang sama.",
         "- Recall S1 dilaporkan terhadap GT `single` (`t_recall`) dan `multiple` (`tm_recall`) secara terpisah; keduanya tidak dipertukarkan.",
         "- Semantik himpunan: butir GT dengan identitas sama dihitung satu (S1: tipe, detik, evidence_source; S2: waktu, pesan; S3: baris). "
         "`t_gt_items_raw` vs `t_gt_items_unique` dan `t_recall_weighted` (berbobot multiplisitas) disertakan sebagai informasi.",
         "- BLEU/ROUGE hanya untuk S1 dan hanya bila referensi valid (`reference_valid`). S2 dan S3 dievaluasi deterministik (P/R/F1). "
         "Referensi S1 = baris '<waktu> <tipe>: <deskripsi>' dari GT single; laporan dibersihkan dari sitasi [Exx] dan judul bagian. `bleu` = tanpa smoothing, `bleu_smooth1` = method1.",
         "- M0-M8 dihitung oleh fungsi lama tanpa perubahan. Pada unit=task, M5 per unit bernilai 0 atau 1 (satu tugas per unit).",
         "- Laporan dari prompt identik (`llm_call=False`, `reused_from`) adalah laporan yang SAMA yang dievaluasi terhadap GT tugas masing-masing.", ""]
    L += ["## Cakupan ground truth oleh digest (tidak bergantung model)", "", "| skenario | unit | butir GT unik | ada di digest | tak terpetakan |", "|---|---|---|---|---|"]
    for s, us in coverage.items():
        for uid, c in us.items(): L.append(f"| {s} | {uid} | {c['gt_unique']} | {c['gt_unique_in_digest'] if c['gt_unique_in_digest'] is not None else 'digest: ' + c.get('digest_status', '-')} | {c['gt_unique_unmapped']} |")
    L += ["", "Digest hanya memuat puluhan butir dari ribuan event: cakupan parsial adalah akibat desain digest lama, bukan kesalahan model.", ""]
    if rows:
        for sub in ("all", "paired"):
            sr = subset_rows(rows, sub); g = defaultdict(list)
            for r in sr: g[(r["scenario"], r["model"], r["strategy"])].append(r["m"])
            L += [f"## Rata-rata per skenario x model x strategi - subset `{sub}`", "", "| skenario | model | strategi | n | " + " | ".join(KEY_COLS) + " |", "|---|---|---|---|" + "---|" * len(KEY_COLS)]
            for (s, m, p), Ms in sorted(g.items()): L.append(f"| {s} | {m} | {p} | {len(Ms)} | " + " | ".join(rm.fmt(mean([x.get(k) for x in Ms])) or "-" for k in KEY_COLS) + " |")
            L += [""]
        L += ["Subset `paired` = hanya unit yang ketiga strategi (P1, P2, P3) berhasil untuk model yang sama; dipakai untuk membandingkan strategi. "
              "Selisih per unit: `summary_deltas.csv`. Semua kolom: `runs_wide.csv`.", ""]
    else: L += ["Belum ada run LLM sah (jalankan stage 11).", ""]
    if notes: L += ["## Catatan", ""] + [f"- {n}" for n in sorted(set(notes))] + [""]
    return "\n".join(L) + "\n"


def main():
    st = config.load_settings()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--unit", choices=["task", "scenario"], default=st["unit_default"]); ap.add_argument("--scenario", choices=["1", "2", "3", "all"], default="all")
    ap.add_argument("--tasks", default=str(config.TASKS_DIR)); ap.add_argument("--unit-id", action="append", help="hanya unit ini (boleh berulang)")
    ap.add_argument("--variant", help="evaluasi results/unit_<unit>__<variant> (baseline tidak tersentuh)"); a = ap.parse_args(); config.set_variant(a.variant)
    if a.unit_id and not a.variant: ap.error("--unit-id (hasil parsial) wajib disertai --variant agar 12_eval baseline tidak tertimpa")
    out = config.unit_dir(a.unit) / "12_eval"; terms = rm.load_template_terms(config.PROMPTS_DIR)
    rows, failed, notes, coverage, validity = [], [], [], {}, []
    for s in config.scenario_list(a.scenario):
        dbase = config.unit_dir(a.unit) / "08_digest" / s; pbase = config.unit_dir(a.unit) / "09_prompts" / s
        if not (dbase / "digest_index.json").exists(): notes.append(f"{s}: digest belum ada (stage 08)"); continue
        gt = load_gt(s, Path(a.tasks)); units = {u["unit_id"]: u for u in tk.units(s, a.unit, a.tasks) if not a.unit_id or u["unit_id"] in a.unit_id}; coverage[s] = {}
        dstat = json.loads((dbase / "digest_index.json").read_text(encoding="utf-8"))["units"]
        dig = {}
        for uid, u in units.items():
            dd = dbase / uid
            if not (dd / "digest.txt").exists():
                st_ = dstat.get(uid, {}).get("status", "TIDAK_ADA"); groups = [g for t in u["tasks"] for g in gt[t["task"]]["groups"]]
                coverage[s][uid] = {"gt_unique": len(groups), "gt_raw": sum(g["mult"] for g in groups), "gt_unique_in_digest": None, "gt_unique_unmapped": sum(1 for g in groups if not g["hashes"]), "digest_status": st_}
                notes.append(f"{s} {uid}: digest tidak dibangun ({st_}); tidak ada laporan LLM untuk unit ini"); continue
            text = (dd / "digest.txt").read_text(encoding="utf-8"); evid = json.loads((dd / "digest_evidence.json").read_text(encoding="utf-8"))["evidence"]
            dig[uid] = {"text": text, "evidence": evid, "sha": hashlib.sha256(text.encode("utf-8")).hexdigest()}
            dh = {e["row_hash"] for e in evid}; groups = [g for t in u["tasks"] for g in gt[t["task"]]["groups"]]
            coverage[s][uid] = {"gt_unique": len(groups), "gt_raw": sum(g["mult"] for g in groups), "gt_unique_in_digest": sum(1 for g in groups if g["hashes"] & dh),
                                "gt_unique_unmapped": sum(1 for g in groups if not g["hashes"])}
        ok, fl = collect(a.unit, s); failed += fl
        for d in ok + fl: validity.append(rv.csv_row(d, {e["id"] for e in dig[d["unit_id"]]["evidence"]} if d.get("unit_id") in dig else None))      # validation_v2: tambahan, tidak memengaruhi metrik lama
        for d in ok:
            uid = d["unit_id"]
            if uid not in dig: notes.append(f"{s} {uid}: run tanpa digest saat ini; dilewati"); continue
            pp = pbase / uid / f"{d['strategy']}.txt"; ptext = pp.read_text(encoding="utf-8") if pp.exists() else None
            if ptext is None: notes.append(f"{s} {uid} {d['strategy']}: prompt tidak ditemukan; M6b memakai frasa instruksi saja")
            elif hashlib.sha256(ptext.encode("utf-8")).hexdigest() != d.get("prompt_sha256"): notes.append(f"{s} {uid} {d['model_tag']} {d['strategy']}: prompt saat ini != prompt run (run basi?)")
            M = evaluate_one(d, s, [t["task"] for t in units[uid]["tasks"]], gt, dig[uid]["text"], dig[uid]["evidence"], ptext, terms, st)
            rows.append({"model": d["model_tag"], "backend": d["backend"], "strategy": d["strategy"], "scenario": s, "unit": a.unit, "unit_id": uid,
                         "tasks": "|".join(t["task"] for t in units[uid]["tasks"]), "llm_call": d.get("llm_call", True), "reused_from": d.get("reused_from", ""),
                         "finish_reason": d.get("finish_reason"), "prompt_tokens": d.get("prompt_tokens"), "completion_tokens": d.get("completion_tokens"), "duration_s": d.get("duration_s"), "m": M})
    out.mkdir(parents=True, exist_ok=True)
    write_csv(out / "runs_wide.csv", META + ALL, [[r[k] for k in META] + [rm.fmt(r["m"].get(c)) for c in ALL] for r in sorted(rows, key=lambda r: (r["scenario"], r["unit_id"], r["model"], r["strategy"]))])
    write_csv(out / "metrics_long.csv", ["scenario", "unit_id", "model", "strategy", "metric", "value", "pure_run"],
              [[r["scenario"], r["unit_id"], r["model"], r["strategy"], c, rm.fmt(r["m"].get(c)), int(r["m"].get("pure") or 0)] for r in rows for c in ALL])
    for name, keyf in (("summary_by_scenario.csv", lambda r: (r["scenario"], r["model"], r["strategy"])), ("summary_overall.csv", lambda r: ("all", r["model"], r["strategy"]))):
        agg = []
        for sub in ("all", "pure", "paired", "paired_pure"):
            g = defaultdict(list)
            for r in subset_rows(rows, sub): g[keyf(r)].append(r["m"])
            for (s, m, p), Ms in sorted(g.items()): agg.append([sub, s, m, p, len(Ms)] + [rm.fmt(mean([x.get(c) for x in Ms])) for c in ALL])
        write_csv(out / name, ["subset", "scenario", "model", "strategy", "n"] + ALL, agg)
    by = {(r["model"], r["scenario"], r["unit_id"], r["strategy"]): r["m"] for r in rows}; deltas = []
    for (m, s, uid, p), M in sorted(by.items()):
        if p == "P1" or (m, s, uid, "P1") not in by: continue
        P1 = by[(m, s, uid, "P1")]; deltas.append([f"{p}-P1", m, s, uid] + [rm.fmt(None if M.get(c) is None or P1.get(c) is None else M[c] - P1[c]) for c in ALL])
    write_csv(out / "summary_deltas.csv", ["delta", "model", "scenario", "unit_id"] + ["d_" + c for c in ALL], deltas)
    write_csv(out / "report_validity.csv", rv.CSV_COLUMNS, sorted(validity, key=lambda r: tuple(str(x) for x in (r[2], r[3], r[1], r[4]))))      # keluaran tambahan validation_v2
    write_csv(out / "failures.csv", ["model", "scenario", "unit_id", "strategy", "status", "note"],
              [[d.get("model_tag"), d.get("scenario"), d.get("unit_id"), d.get("strategy"), d.get("status"), (d.get("note") or "")[:200]] for d in failed])
    (out / "gt_coverage.json").write_text(json.dumps(coverage, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    (out / "eval_report.md").write_text(report_md(a.unit, rows, failed, coverage, notes), encoding="utf-8")
    print(f"run sah dievaluasi={len(rows)} kegagalan={len(failed)} -> {out}")
    for n in sorted(set(notes)): print("CATATAN:", n)


if __name__ == "__main__":
    main()
