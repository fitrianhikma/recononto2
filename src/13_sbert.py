"""STAGE 13 - Kemiripan semantik SBERT untuk laporan Skenario 1 (TAMBAHAN; stage 00-12 dan isi results/ lama tidak diubah).

    python3 src/13_sbert.py [--revision HASH] [--verify-determinism] [--threads 1] [--batch-size 1]
Masukan : results/unit_task/11_llm/*/scenario1 (via collect() stage 12), results/unit_task/08_digest/scenario1, data/tasks (GT single)
Keluaran: results/unit_task/13_sbert/{sbert_per_report.csv, sbert_summary_by_cell.csv, sbert_baselines.csv, sbert_report.json}

Teks yang dibandingkan SAMA PERSIS dengan BLEU/ROUGE stage 12 (fungsi diimpor, tidak disalin):
  referensi = "\\n".join(tasks.s1_reference_lines(GT single unit))
  hipotesis = extra_metrics.strip_report(teks laporan)                                  -> kolom tanpa awalan
              extra_metrics.strip_report(report_metrics.split_sections(teks)["TIMELINE"]) -> kolom berawalan tl_
Model: sentence-transformers/all-MiniLM-L6-v2, CPU, HANYA dari cache lokal (tidak mengunduh; unduh manual lebih dulu).
Metrik (embedding dinormalisasi, cosine dalam float64):
  sbert_doc            cosine(embedding seluruh hipotesis, embedding seluruh referensi)
  sbert_line_recall    rata-rata, atas baris referensi, dari cosine maksimum ke segmen hipotesis mana pun
  sbert_line_precision rata-rata, atas segmen hipotesis, dari cosine maksimum ke baris referensi mana pun
  sbert_line_f1        2PR/(P+R) bila P>0 dan R>0, selain itu 0
  Segmen hipotesis = baris tak kosong, dipecah lagi per kalimat ('. ', '! ', '? ' diikuti huruf besar/angka); segmen tanpa token
  (tokenizer BLEU/ROUGE) dibuang. Baris referensi = satu baris per butir s1_reference_lines.
Pemotongan: model hanya membaca max_seq_length token (WordPiece, termasuk [CLS]/[SEP]); teks lebih panjang DIPOTONG diam-diam.
  Flag *_truncated / *_trunc_n mencatatnya. sbert_doc pada teks panjang hanya mewakili awal teks.
Pembanding (sbert_baselines.csv): self_reference (referensi vs dirinya; harus ~1), timestamp_only (HH:MM:SS unik bukti digest),
  cite_all (semua baris [Exx] digest disalin apa adanya), mismatch_report[_tl] (laporan vs referensi unit LAIN), mismatch_reference
  (referensi vs referensi unit lain). Angka deskriptif; stage ini tidak menyimpulkan model/strategi terbaik.
Validasi otomatis (sbert_report.json; kode keluar 1 bila gagal): hash berkas results/ di luar 13_sbert sebelum = sesudah,
  referensi vs dirinya ~1, semua skor dalam [-1, 1], dan (dengan --verify-determinism) dua kali hitung (model dimuat ulang) identik.
"""
import argparse, hashlib, importlib.util, json, math, os, platform, re, sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config, extra_metrics as xm, report_metrics as rm, report_validation as rv, tasks as tk  # noqa: E402

STAGE = "13_sbert"
SCENARIO = "scenario1"
MODEL_ID = "sentence-transformers/all-MiniLM-L6-v2"
EXPECTED_REPORTS = 168
SELF_TOL = 1e-5          # |cos(x, x) - 1|
RANGE_TOL = 1e-6         # toleransi pembulatan float untuk batas [-1, 1]
MODEL_FILES = ["modules.json", "config_sentence_transformers.json", "sentence_bert_config.json", "config.json", "model.safetensors",
               "pytorch_model.bin", "tokenizer.json", "tokenizer_config.json", "vocab.txt", "special_tokens_map.json", "1_Pooling/config.json"]
METRICS = ["sbert_doc", "sbert_line_recall", "sbert_line_precision", "sbert_line_f1"]
MODES = (("", "full"), ("tl_", "timeline"))
META = ["model", "backend", "strategy", "scenario", "unit_id", "run_status", "finish_reason", "validity_status", "valid_report",
        "reference_valid", "ref_lines", "ref_doc_tokens", "ref_doc_truncated", "ref_line_trunc_n"]
PER_MODE = ["hyp_empty", "hyp_segments", "hyp_doc_tokens", "hyp_doc_truncated", "hyp_seg_trunc_n"] + METRICS + \
           ["mismatch_doc_mean", "mismatch_doc_max", "mismatch_line_f1_mean", "mismatch_line_f1_max"]
COLS = META + [p + c for p, _ in MODES for c in PER_MODE] + ["any_truncated"]
SUMMARY_METRICS = [p + c for p, _ in MODES for c in METRICS + ["mismatch_doc_mean", "mismatch_line_f1_mean", "hyp_doc_truncated"]] + ["ref_doc_truncated"]
BASE_COLS = ["baseline", "unit_id", "n_pairs", "hyp_segments", "hyp_doc_tokens", "hyp_doc_truncated"] + METRICS
_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")
_EVLINE = re.compile(r"(?m)^\[E\d+\][^\n]*$")


def _load_stage12():
    """12_evaluate.py berawalan angka: dimuat lewat importlib (main() tidak dijalankan). Dipakai untuk collect() yang sama persis."""
    spec = importlib.util.spec_from_file_location("evaluate_12", Path(__file__).resolve().parent / "12_evaluate.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m


# ---------------------------------------------------------------- teks (fungsi stage 12 dipakai ulang, tidak disalin)
def reference_text(ref_lines: list) -> str:
    return "\n".join(ref_lines)                                   # sama dengan xm.lexical_scores / xm.library_scores


def hypothesis_text(report_text: str, timeline_only: bool = False) -> str:
    t = report_text or ""
    if timeline_only: t = rm.split_sections(t).get("TIMELINE", "")
    return xm.strip_report(t)


def segments(text: str) -> list:
    """Segmen hipotesis: baris tak kosong -> kalimat; dibuang bila tidak punya token (tokenizer BLEU/ROUGE)."""
    out = []
    for line in (text or "").splitlines():
        for s in _SENT.split(line.strip()):
            s = s.strip()
            if s and xm.tokens(s): out.append(s)
    return out


def timestamp_only_text(evidence: list) -> str:
    return "\n".join(sorted({e["timestamp"][11:19] for e in evidence if len(e.get("timestamp", "")) >= 19}))


def cite_all_text(digest_text: str) -> str:
    return xm.strip_report("\n".join(_EVLINE.findall(digest_text or "")))


# ---------------------------------------------------------------- skor (numpy; murni, dapat diuji tanpa model)
def _np():
    import numpy as np
    return np


def cosine(a, b) -> float:
    np = _np(); a = np.asarray(a, dtype=np.float64); b = np.asarray(b, dtype=np.float64)
    na, nb = float(np.linalg.norm(a)), float(np.linalg.norm(b))
    return float(a @ b / (na * nb)) if na > 0 and nb > 0 else 0.0


def line_scores(H, R) -> tuple:
    """H: (m, d) segmen hipotesis, R: (n, d) baris referensi -> (recall, precision, f1). Pencocokan maksimum (gaya BERTScore, tingkat kalimat)."""
    np = _np(); H = np.asarray(H, dtype=np.float64); R = np.asarray(R, dtype=np.float64)
    H = H / np.linalg.norm(H, axis=1, keepdims=True); R = R / np.linalg.norm(R, axis=1, keepdims=True); S = H @ R.T
    rec, prec = float(S.max(axis=0).mean()), float(S.max(axis=1).mean())
    return rec, prec, (2 * prec * rec / (prec + rec) if prec > 0 and rec > 0 else 0.0)


# ---------------------------------------------------------------- encoder
class SbertEncoder:
    """Model dari cache HF lokal saja (local_files_only); CPU; deterministik (1 thread, algoritme deterministik, batch tetap)."""

    def __init__(self, model_id=MODEL_ID, revision=None, threads=1, batch_size=1):
        os.environ.setdefault("TOKENIZERS_PARALLELISM", "false"); os.environ["HF_HUB_OFFLINE"] = "1"; os.environ["TRANSFORMERS_OFFLINE"] = "1"
        os.environ["CUDA_VISIBLE_DEVICES"] = ""
        import numpy, torch, transformers, huggingface_hub, sentence_transformers
        from huggingface_hub import snapshot_download
        from sentence_transformers import SentenceTransformer
        transformers.logging.set_verbosity_error()
        torch.manual_seed(0); torch.set_num_threads(threads); torch.use_deterministic_algorithms(True)
        try: path = Path(snapshot_download(model_id, revision=revision, local_files_only=True))
        except Exception as e:
            raise SystemExit(f"Model {model_id} (revisi {revision or 'default'}) tidak ada di cache lokal; unduh manual dulu. ({type(e).__name__}: {e})")
        self.model = SentenceTransformer(str(path), device="cpu"); self.model.eval()
        self.batch_size = batch_size; self.max_seq_length = int(self.model.max_seq_length)
        files = {}
        for f in MODEL_FILES:
            p = path / f
            if p.exists(): files[f] = hashlib.sha256(p.resolve().read_bytes()).hexdigest()
        self.info = {"model_id": model_id, "revision_requested": revision, "revision_resolved": path.name, "snapshot_path": str(path),
                     "file_sha256": files, "max_seq_length": self.max_seq_length, "embedding_dim": int(self.model.get_sentence_embedding_dimension()),
                     "modules": [type(m).__name__ for m in self.model], "device": "cpu", "torch_threads": threads, "batch_size": batch_size,
                     "normalize_embeddings": True, "deterministic_algorithms": True,
                     "libraries": {"python": platform.python_version(), "platform": platform.platform(), "sentence_transformers": sentence_transformers.__version__,
                                   "transformers": transformers.__version__, "torch": torch.__version__, "huggingface_hub": huggingface_hub.__version__,
                                   "numpy": numpy.__version__}}

    def encode(self, texts: list):
        return self.model.encode(texts, batch_size=self.batch_size, convert_to_numpy=True, normalize_embeddings=True, show_progress_bar=False)

    def n_tokens(self, text: str) -> int:
        return len(self.model.tokenizer(text, add_special_tokens=True, truncation=False)["input_ids"])


class Cache:
    """Embedding dan jumlah token per teks unik; teks baru dikodekan dalam urutan terurut agar hasil tidak bergantung urutan pemanggilan."""

    def __init__(self, enc):
        self.enc, self.vec, self.ntok = enc, {}, {}

    def prime(self, texts):
        new = sorted({t for t in texts if t not in self.vec})
        if new:
            for t, v in zip(new, self.enc.encode(new)): self.vec[t] = v
        for t in new: self.ntok[t] = self.enc.n_tokens(t)

    def v(self, t): return self.vec[t]
    def trunc(self, t): return self.ntok[t] > self.enc.max_seq_length


# ---------------------------------------------------------------- perhitungan
def pair_scores(c: Cache, hyp_doc: str, hyp_segs: list, ref_doc: str, ref_lines: list) -> dict:
    np = _np(); out = {"sbert_doc": cosine(c.v(hyp_doc), c.v(ref_doc))}
    r, p, f = line_scores(np.stack([c.v(s) for s in hyp_segs]), np.stack([c.v(s) for s in ref_lines]))
    out.update({"sbert_line_recall": r, "sbert_line_precision": p, "sbert_line_f1": f}); return out


def compute(enc, runs: list, units: dict, min_ref_tokens: int) -> dict:
    """runs : [{model_tag, backend, strategy, unit_id, status, finish_reason, text}] (JSON run stage 11)
    units: {unit_id: {"ref_lines": [...], "evidence": [...] | None, "digest_text": str | None}}
    -> {"rows": [dict per laporan], "baselines": [dict], "self_check": {...}, "range_violations": [...]}"""
    c = Cache(enc); U = {}
    for uid, u in units.items():
        rl = list(u["ref_lines"]); rd = reference_text(rl)
        U[uid] = {"lines": rl, "doc": rd, "valid": bool(rl) and len(xm.tokens(rd)) >= min_ref_tokens}
    hyps = {}
    for i, r in enumerate(runs):
        for p, mode in MODES:
            d = hypothesis_text(r.get("text"), mode == "timeline"); hyps[(i, p)] = (d, segments(d))
    synth = {}
    for uid, u in units.items():
        if u.get("evidence") is not None: d = timestamp_only_text(u["evidence"]); synth[("timestamp_only", uid)] = (d, segments(d))
        if u.get("digest_text") is not None: d = cite_all_text(u["digest_text"]); synth[("cite_all", uid)] = (d, segments(d))
    texts = [t for x in U.values() for t in [x["doc"]] + x["lines"]] + [t for d, s in list(hyps.values()) + list(synth.values()) if s for t in [d] + s]
    c.prime([t for t in texts if t])
    valid_ids = sorted(k for k, x in U.items() if x["valid"])

    def score(doc, segs, uid):
        return pair_scores(c, doc, segs, U[uid]["doc"], U[uid]["lines"]) if segs and U[uid]["valid"] else {k: None for k in METRICS}

    rows = []
    for i, r in enumerate(runs):
        uid = r["unit_id"]; ux = U[uid]; ev = units[uid].get("evidence")
        v = rv.validate_report(r.get("text"), r.get("finish_reason"), {e["id"] for e in ev} if ev is not None else None,
                               transport_ok=r.get("status") not in rv.TRANSPORT_FAIL)
        row = {"model": r.get("model_tag"), "backend": r.get("backend"), "strategy": r.get("strategy"), "scenario": SCENARIO, "unit_id": uid,
               "run_status": r.get("status"), "finish_reason": r.get("finish_reason"), "validity_status": v["status"], "valid_report": int(v["valid_report"]),
               "reference_valid": int(ux["valid"]), "ref_lines": len(ux["lines"]), "ref_doc_tokens": c.ntok.get(ux["doc"]),
               "ref_doc_truncated": int(c.trunc(ux["doc"])) if ux["doc"] in c.ntok else None,
               "ref_line_trunc_n": sum(c.trunc(t) for t in ux["lines"])}
        anyt = bool(row["ref_doc_truncated"]) or row["ref_line_trunc_n"] > 0
        for p, _ in MODES:
            d, segs = hyps[(i, p)]; s = score(d, segs, uid)
            row.update({p + "hyp_empty": int(not segs), p + "hyp_segments": len(segs), p + "hyp_doc_tokens": c.ntok.get(d) if segs else None,
                        p + "hyp_doc_truncated": int(c.trunc(d)) if segs else None, p + "hyp_seg_trunc_n": sum(c.trunc(t) for t in segs)})
            row.update({p + k: s[k] for k in METRICS})
            mm = [score(d, segs, o) for o in valid_ids if o != uid] if segs else []
            for k, name in (("sbert_doc", "mismatch_doc"), ("sbert_line_f1", "mismatch_line_f1")):
                xs = [m[k] for m in mm if m[k] is not None]
                row[p + name + "_mean"] = sum(xs) / len(xs) if xs else None; row[p + name + "_max"] = max(xs) if xs else None
            anyt = anyt or bool(row[p + "hyp_doc_truncated"]) or row[p + "hyp_seg_trunc_n"] > 0
        row["any_truncated"] = int(anyt); rows.append(row)

    base, self_check = [], {}
    for uid in sorted(U):
        ux = U[uid]
        if ux["valid"]:
            s = pair_scores(c, ux["doc"], ux["lines"], ux["doc"], ux["lines"]); self_check[uid] = s
            base.append({"baseline": "self_reference", "unit_id": uid, "n_pairs": 1, "hyp_segments": len(ux["lines"]), "hyp_doc_tokens": c.ntok[ux["doc"]],
                         "hyp_doc_truncated": int(c.trunc(ux["doc"])), **s})
        for b in ("timestamp_only", "cite_all"):
            if (b, uid) not in synth: continue
            d, segs = synth[(b, uid)]
            base.append({"baseline": b, "unit_id": uid, "n_pairs": 1, "hyp_segments": len(segs), "hyp_doc_tokens": c.ntok.get(d) if segs else None,
                         "hyp_doc_truncated": int(c.trunc(d)) if segs else None, **score(d, segs, uid)})
        if ux["valid"]:
            mm = [pair_scores(c, ux["doc"], ux["lines"], U[o]["doc"], U[o]["lines"]) for o in valid_ids if o != uid]
            base.append({"baseline": "mismatch_reference", "unit_id": uid, "n_pairs": len(mm), "hyp_segments": len(ux["lines"]), "hyp_doc_tokens": c.ntok[ux["doc"]],
                         "hyp_doc_truncated": int(c.trunc(ux["doc"])), **{k: _mean([m[k] for m in mm]) for k in METRICS}})
        for p, name in (("", "mismatch_report"), ("tl_", "mismatch_report_tl")):
            mine = [r for r in rows if r["unit_id"] == uid and r[p + "mismatch_doc_mean"] is not None]
            if mine:     # rata-rata (atas laporan unit ini) dari rata-rata mismatch tiap laporan; line_recall/precision tidak disimpan per laporan
                base.append({"baseline": name, "unit_id": uid, "n_pairs": len(mine) * (len(valid_ids) - (uid in valid_ids)), "hyp_segments": None, "hyp_doc_tokens": None,
                             "hyp_doc_truncated": None, "sbert_doc": _mean([r[p + "mismatch_doc_mean"] for r in mine]), "sbert_line_recall": None,
                             "sbert_line_precision": None, "sbert_line_f1": _mean([r[p + "mismatch_line_f1_mean"] for r in mine])})
    agg = defaultdict(list)
    for b in base: agg[b["baseline"]].append(b)
    for name, bs in sorted(agg.items()):
        base.append({"baseline": name, "unit_id": "ALL_UNITS_MEAN", "n_pairs": sum(b["n_pairs"] for b in bs), "hyp_segments": None, "hyp_doc_tokens": None,
                     "hyp_doc_truncated": _mean([b["hyp_doc_truncated"] for b in bs]), **{k: _mean([b[k] for b in bs]) for k in METRICS}})

    viol = []
    for r in rows:
        for k, x in r.items():
            if any(k.endswith(m) for m in METRICS) or "mismatch_" in k:
                if x is not None and not (-1 - RANGE_TOL <= x <= 1 + RANGE_TOL and math.isfinite(x)): viol.append([r["model"], r["strategy"], r["unit_id"], k, x])
    for b in base:
        for k in METRICS:
            x = b[k]
            if x is not None and not (-1 - RANGE_TOL <= x <= 1 + RANGE_TOL and math.isfinite(x)): viol.append(["baseline", b["baseline"], b["unit_id"], k, x])
    return {"rows": rows, "baselines": base, "self_check": self_check, "range_violations": viol, "n_unique_texts": len(c.vec)}


def _mean(xs):
    xs = [x for x in xs if x is not None]; return sum(xs) / len(xs) if xs else None


def _sd(xs):
    xs = [x for x in xs if x is not None]
    if len(xs) < 2: return None
    m = sum(xs) / len(xs); return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def summary_rows(rows: list) -> list:
    """Format panjang: subset x model x strategi x metrik -> n (nilai tak kosong), n_reports, mean, sd (sampel), min, max."""
    out = []
    for sub in ("all", "VALID"):
        g = defaultdict(list)
        for r in rows:
            if sub == "all" or r["validity_status"] == "VALID": g[(r["model"], r["strategy"])].append(r)
        for (m, p), rs in sorted(g.items()):
            for k in SUMMARY_METRICS:
                xs = [r[k] for r in rs if r[k] is not None]
                out.append([sub, SCENARIO, m, p, k, len(rs), len(xs), _f(_mean(xs)), _f(_sd(xs)), _f(min(xs) if xs else None), _f(max(xs) if xs else None)])
    return out


def _f(v):
    if v is None: return ""
    return rm.fmt(v) if isinstance(v, float) else str(v)


def table(rows: list, cols: list) -> list:
    return [[_f(r[k]) for k in cols] for r in rows]


# ---------------------------------------------------------------- hash results/ lama
def hash_tree(root: Path, exclude: Path) -> dict:
    out, ex = {}, exclude.resolve()
    for p in sorted(root.rglob("*")):
        rp = p.resolve()
        if not p.is_file() or rp == ex or ex in rp.parents: continue
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for b in iter(lambda: f.read(1 << 20), b""): h.update(b)
        out[str(p.relative_to(root))] = h.hexdigest()
    return out


def manifest_digest(m: dict) -> str:
    return hashlib.sha256("".join(f"{v}  {k}\n" for k, v in sorted(m.items())).encode("utf-8")).hexdigest()


def manifest_check(unit_dir: Path, current: dict, results_root: Path) -> dict:
    """Informasi saja: bandingkan dengan MANIFEST_SHA256_unit_task.txt bila ada (bisa basi bila manifest tidak diperbarui)."""
    mf = unit_dir / "MANIFEST_SHA256_unit_task.txt"
    if not mf.exists(): return {"present": False}
    ok = bad = missing = 0; pre = str(unit_dir.relative_to(results_root))
    for line in mf.read_text(encoding="utf-8").splitlines():
        if not line.strip(): continue
        h, rel = line.split(None, 1); key = str(Path(pre) / rel.strip())
        if key not in current: missing += 1
        elif current[key] == h: ok += 1
        else: bad += 1
    return {"present": True, "entries_match": ok, "entries_differ": bad, "entries_missing": missing}


# ---------------------------------------------------------------- muat masukan
def load_inputs(stage12, tasks_dir: Path) -> tuple:
    ok, failed = stage12.collect("task", SCENARIO)
    dbase = config.unit_dir("task") / "08_digest" / SCENARIO; units, notes = {}, []
    for u in tk.units(SCENARIO, "task", tasks_dir):
        uid = u["unit_id"]; items = [it for t in u["tasks"] for it in tk.read_gt(t, "single")]       # = gt[t]["items"] stage 12
        dd = dbase / uid; ev = dt = None
        if (dd / "digest_evidence.json").exists(): ev = json.loads((dd / "digest_evidence.json").read_text(encoding="utf-8"))["evidence"]
        else: notes.append(f"{uid}: digest_evidence.json tidak ada (validitas ids & baseline timestamp_only dilewati)")
        if (dd / "digest.txt").exists(): dt = (dd / "digest.txt").read_text(encoding="utf-8")
        else: notes.append(f"{uid}: digest.txt tidak ada (baseline cite_all dilewati)")
        units[uid] = {"ref_lines": tk.s1_reference_lines(items), "evidence": ev, "digest_text": dt}
    runs = [r for r in ok if r.get("unit_id") in units]
    if len(runs) != len(ok): notes.append(f"{len(ok) - len(runs)} run tanpa unit GT dilewati")
    runs.sort(key=lambda r: (r["unit_id"], r["model_tag"], r["strategy"]))
    return runs, units, failed, notes


def validity_crosscheck(rows: list, path: Path) -> dict:
    """Bandingkan status validitas yang dihitung ulang dengan 12_eval/report_validity.csv (hanya dibaca)."""
    if not path.exists(): return {"present": False}
    import csv
    with open(path, encoding="utf-8") as f: old = {(r["model"], r["unit_id"], r["strategy"]): r["status"] for r in csv.DictReader(f) if r["scenario"] == SCENARIO}
    diff = [[r["model"], r["unit_id"], r["strategy"], old.get((r["model"], r["unit_id"], r["strategy"])), r["validity_status"]]
            for r in rows if old.get((r["model"], r["unit_id"], r["strategy"])) != r["validity_status"]]
    return {"present": True, "compared": len(rows), "differ": len(diff), "differences": diff}


def write_json(path: Path, obj):
    tmp = path.with_name(path.name + ".tmp"); tmp.write_text(json.dumps(obj, indent=1, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"); os.replace(tmp, path)


def main(argv=None):
    st = config.load_settings()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tasks", default=str(config.TASKS_DIR)); ap.add_argument("--model-id", default=MODEL_ID)
    ap.add_argument("--revision", help="commit hash model HF (disarankan dipatok); default = snapshot di cache lokal untuk 'main'")
    ap.add_argument("--threads", type=int, default=1); ap.add_argument("--batch-size", type=int, default=1, help="1 = embedding tiap teks tidak bergantung teks lain dalam batch")
    ap.add_argument("--verify-determinism", action="store_true", help="hitung dua kali (model dimuat ulang) dan bandingkan seluruh keluaran")
    a = ap.parse_args(argv)
    results_root = config.RESULTS; unit_dir = config.unit_dir("task"); out = unit_dir / STAGE
    before = hash_tree(results_root, out)
    runs, units, failed, notes = load_inputs(_load_stage12(), Path(a.tasks))
    if len(runs) != EXPECTED_REPORTS: notes.append(f"jumlah laporan S1 = {len(runs)}, bukan {EXPECTED_REPORTS}")
    mrt = st["evaluation"]["min_reference_tokens"]

    def one_pass():
        enc = SbertEncoder(a.model_id, a.revision, a.threads, a.batch_size); R = compute(enc, runs, units, mrt)
        return enc.info, R, table(R["rows"], COLS), summary_rows(R["rows"]), table(R["baselines"], BASE_COLS)

    info, R, t_rows, t_sum, t_base = one_pass(); det = None
    if a.verify_determinism:
        info2, R2, t_rows2, t_sum2, t_base2 = one_pass()
        raw_equal = [[r[k] for k in COLS] for r in R["rows"]] == [[r[k] for k in COLS] for r in R2["rows"]]
        det = {"checked": True, "raw_values_identical": raw_equal, "formatted_outputs_identical": (t_rows, t_sum, t_base) == (t_rows2, t_sum2, t_base2),
               "model_revision_identical": info["revision_resolved"] == info2["revision_resolved"]}
    out.mkdir(parents=True, exist_ok=True)
    rm.write_csv(out / "sbert_per_report.csv", COLS, t_rows)
    rm.write_csv(out / "sbert_summary_by_cell.csv", ["subset", "scenario", "model", "strategy", "metric", "n_reports", "n", "mean", "sd", "min", "max"], t_sum)
    rm.write_csv(out / "sbert_baselines.csv", BASE_COLS, t_base)
    after = hash_tree(results_root, out)

    sc = R["self_check"]; worst = max((abs(v[k] - 1.0) for v in sc.values() for k in METRICS), default=None)
    rows = R["rows"]; n = len(rows)
    checks = {
        "old_results_unchanged": {"pass": before == after, "files": len(before), "manifest_sha256_before": manifest_digest(before), "manifest_sha256_after": manifest_digest(after),
                                  "changed_or_added_or_removed": sorted(set(before) ^ set(after) | {k for k in before if k in after and before[k] != after[k]})},
        "self_reference_approx_1": {"pass": worst is not None and worst <= SELF_TOL, "tolerance": SELF_TOL, "max_abs_deviation": worst, "units": len(sc)},
        "scores_in_range": {"pass": not R["range_violations"], "bounds": [-1, 1], "tolerance": RANGE_TOL, "violations": R["range_violations"]},
        "determinism_two_passes": det or {"checked": False, "note": "jalankan dengan --verify-determinism; juga bandingkan output_sha256 antar-eksekusi"},
    }
    passed = all(v["pass"] for k, v in checks.items() if k != "determinism_two_passes") and (det is None or all(det[k] for k in det if k != "checked"))
    report = {
        "stage": STAGE, "scenario": SCENARIO, "unit": "task", "model": info,
        "text_sources": {"reference": "tasks.s1_reference_lines (GT single) -> '\\n'.join", "hypothesis_full": "extra_metrics.strip_report(text)",
                         "hypothesis_timeline": "extra_metrics.strip_report(report_metrics.split_sections(text)['TIMELINE'])",
                         "reference_valid": f"sama dengan stage 12: >= {mrt} token (extra_metrics.tokens)",
                         "hyp_segments": "baris tak kosong -> kalimat; segmen tanpa token dibuang", "validity": f"report_validation.{rv.VALIDATION_VERSION}"},
        "counts": {"reports": n, "expected_reports": EXPECTED_REPORTS, "failed_runs_not_scored": len(failed), "units": len(units),
                   "units_reference_valid": sum(1 for r in {x['unit_id']: x for x in rows}.values() if r["reference_valid"]),
                   "valid_reports": sum(r["valid_report"] for r in rows), "validity_status": dict(sorted(_count(r["validity_status"] for r in rows).items())),
                   "unique_texts_embedded": R["n_unique_texts"]},
        "truncation": {"max_seq_length": info["max_seq_length"], "reports_any_truncated": sum(r["any_truncated"] for r in rows),
                       "hyp_doc_truncated_full": sum(r["hyp_doc_truncated"] or 0 for r in rows), "hyp_doc_truncated_timeline": sum(r["tl_hyp_doc_truncated"] or 0 for r in rows),
                       "hyp_segments_truncated_full": sum(r["hyp_seg_trunc_n"] for r in rows), "hyp_segments_truncated_timeline": sum(r["tl_hyp_seg_trunc_n"] for r in rows),
                       "reference_docs_truncated": sum(1 for r in {x['unit_id']: x for x in rows}.values() if r["ref_doc_truncated"]),
                       "note": "teks di atas max_seq_length dipotong model; sbert_doc lalu hanya mewakili awal teks. Skor per baris jarang terdampak."},
        "validity_crosscheck_vs_12_eval": validity_crosscheck(rows, unit_dir / "12_eval" / "report_validity.csv"),
        "manifest_unit_task_check": manifest_check(unit_dir, after, results_root),
        "checks": checks, "all_checks_pass": passed,
        "output_sha256": {f: hashlib.sha256((out / f).read_bytes()).hexdigest() for f in ("sbert_per_report.csv", "sbert_summary_by_cell.csv", "sbert_baselines.csv")},
        "notes": sorted(set(notes)),
        "caveats": ["Satu run per kondisi: angka deskriptif, tanpa uji signifikansi; stage ini tidak menentukan model/strategi terbaik.",
                    "Cosine SBERT antar-teks berdomain sama cenderung tinggi; bandingkan dengan baris mismatch_* dan baseline, bukan dengan 0.",
                    "Baseline timestamp_only/cite_all memakai bukti digest (bukan GT); cite_all = salinan baris [Exx] digest setelah strip_report."],
    }
    write_json(out / "sbert_report.json", report)
    print(f"laporan S1 dinilai={n} (VALID={report['counts']['valid_reports']}) gagal-tak-dinilai={len(failed)} -> {out}")
    for k, v in checks.items(): print(f"  cek {k}: {v.get('pass', v)}")
    for x in report["notes"]: print("CATATAN:", x)
    if not passed: print("GAGAL: setidaknya satu validasi tidak lulus (lihat sbert_report.json -> checks)"); return 1
    return 0


def _count(xs):
    d = defaultdict(int)
    for x in xs: d[x] += 1
    return d


if __name__ == "__main__":
    sys.exit(main())
