"""Unit test Stage 13 (SBERT) tanpa model, tanpa torch, tanpa dataset, tanpa jaringan: encoder palsu deterministik (bag-of-token ter-hash).
Menulis hanya ke folder sementara. Jalankan: python3 -m unittest tests.test_sbert -v"""
import hashlib, importlib.util, inspect, math, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import extra_metrics as xm, report_metrics as rm, tasks as tk  # noqa: E402

spec = importlib.util.spec_from_file_location("sbert_13", ROOT / "src" / "13_sbert.py")
sb = importlib.util.module_from_spec(spec); spec.loader.exec_module(sb)

try:
    import numpy as np
except ImportError:      # pragma: no cover
    np = None


class FakeEncoder:
    """Vektor 64 dimensi dari hash token (tokenizer BLEU/ROUGE); jumlah token = kata + 2 (meniru [CLS]/[SEP])."""

    def __init__(self, max_seq_length=256):
        self.max_seq_length = max_seq_length; self.calls = 0

    def encode(self, texts):
        self.calls += 1; out = np.zeros((len(texts), 64))
        for i, t in enumerate(texts):
            toks = xm.tokens(t) or ["<kosong>"]
            for w in toks: out[i, int(hashlib.md5(w.encode()).hexdigest(), 16) % 64] += 1.0
            out[i] /= np.linalg.norm(out[i])
        return out.astype(np.float32)

    def n_tokens(self, text): return len(text.split()) + 2


def report(timeline: str, summary="User opened the browser.") -> str:
    return f"SUMMARY: {summary}\n\nTIMELINE:\n{timeline}\n\nFINDINGS:\n- Edge was launched [E01].\n\nLIMITATIONS:\n- None."


EV = [{"id": "E01", "timestamp": "2023-12-26T00:34:27.243709Z"}, {"id": "E02", "timestamp": "2023-12-26T00:34:30.000000Z"}]
UNITS = {
    "u-edge": {"ref_lines": ["00:34:27 Application Launch: Microsoft Edge was launched", "00:35:11 Web Visit: user visited microsoft.com welcome page"],
               "evidence": EV, "digest_text": "Scope: x\n[E01] 00:34:27 prefetch AppExecution: MSEDGE.EXE (x9)\n[E02] 00:34:30 winevtx UserLogon: id=4624"},
    "u-cmd": {"ref_lines": ["00:40:01 Application Launch: cmd.exe command prompt was launched by the user"], "evidence": EV, "digest_text": "[E01] 00:40:01 prefetch AppExecution: CMD.EXE"},
    "u-empty": {"ref_lines": [], "evidence": None, "digest_text": None},
}
RUNS = [
    {"model_tag": "m1", "backend": "x", "strategy": "P1", "unit_id": "u-edge", "status": "OK", "finish_reason": "stop",
     "text": report("[E01] 00:34:27 Microsoft Edge was launched. The user then visited microsoft.com welcome page.")},
    {"model_tag": "m1", "backend": "x", "strategy": "P2", "unit_id": "u-edge", "status": "OK", "finish_reason": "length",
     "text": report("[E01] 00:34:27 prefetch AppExecution: MSEDGE.EXE")},
    {"model_tag": "m1", "backend": "x", "strategy": "P1", "unit_id": "u-cmd", "status": "OK", "finish_reason": "stop",
     "text": "SUMMARY: only a summary, no timeline section [E07]."},
    {"model_tag": "m1", "backend": "x", "strategy": "P1", "unit_id": "u-empty", "status": "OK", "finish_reason": "stop", "text": report("[E01] 00:34:27 x")},
]


@unittest.skipIf(np is None, "numpy tidak terpasang")
class TestSbertStage13(unittest.TestCase):
    def test_reuses_stage12_text_functions(self):
        src = inspect.getsource(sb)
        self.assertNotIn("def strip_report", src); self.assertNotIn("def s1_reference_lines", src)
        self.assertIs(sb.xm, xm); self.assertIs(sb.tk, tk); self.assertIs(sb.rm, rm)
        t = RUNS[0]["text"]
        self.assertEqual(sb.hypothesis_text(t), xm.strip_report(t))
        self.assertEqual(sb.hypothesis_text(t, True), xm.strip_report(rm.split_sections(t).get("TIMELINE", "")))
        self.assertEqual(sb.reference_text(["a b", "c d"]), "a b\nc d")
        self.assertNotIn("[E01]", sb.hypothesis_text(t)); self.assertNotIn("TIMELINE", sb.hypothesis_text(t))

    def test_segments(self):
        s = sb.segments("  00:34:27 Edge launched. Then user visited bing.com.\n\n - \nfirefox.exe ran")
        self.assertEqual(s, ["00:34:27 Edge launched.", "Then user visited bing.com.", "firefox.exe ran"])

    def test_line_scores_math(self):
        H = np.array([[1.0, 0.0], [0.0, 1.0]]); R = np.array([[1.0, 0.0]])
        r, p, f = sb.line_scores(H, R)
        self.assertAlmostEqual(r, 1.0); self.assertAlmostEqual(p, 0.5); self.assertAlmostEqual(f, 2 * 0.5 / 1.5)
        r, p, f = sb.line_scores(np.array([[-1.0, 0.0]]), R); self.assertEqual((r, p, f), (-1.0, -1.0, 0.0))
        self.assertAlmostEqual(sb.cosine([3, 4], [3, 4]), 1.0); self.assertEqual(sb.cosine([0, 0], [1, 0]), 0.0)

    def test_compute_self_range_validity_baselines(self):
        R = sb.compute(FakeEncoder(), RUNS, UNITS, 5); rows = {(r["unit_id"], r["strategy"]): r for r in R["rows"]}
        self.assertEqual(set(R["self_check"]), {"u-edge", "u-cmd"})
        for v in R["self_check"].values():
            for k in sb.METRICS: self.assertAlmostEqual(v[k], 1.0, places=6)
        self.assertEqual(R["range_violations"], [])
        a = rows[("u-edge", "P1")]
        self.assertEqual(a["validity_status"], "VALID"); self.assertEqual(rows[("u-edge", "P2")]["validity_status"], "TRUNCATED")
        self.assertEqual(a["reference_valid"], 1); self.assertEqual(a["ref_lines"], 2)
        for p in ("", "tl_"):
            for k in sb.METRICS: self.assertTrue(-1 <= a[p + k] <= 1)
        self.assertGreater(a["tl_sbert_line_recall"], a["tl_sbert_line_precision"] - 1)   # dihitung, bukan None
        self.assertIsNotNone(a["mismatch_doc_mean"]); self.assertEqual(a["mismatch_doc_mean"], a["mismatch_doc_max"])   # hanya 1 unit lain yang valid
        c = rows[("u-cmd", "P1")]                                                        # tanpa bagian TIMELINE
        self.assertEqual(c["tl_hyp_empty"], 1); self.assertIsNone(c["tl_sbert_doc"]); self.assertIsNotNone(c["sbert_doc"])
        self.assertEqual(c["validity_status"], "INCOMPLETE_STRUCTURE")
        e = rows[("u-empty", "P1")]                                                      # referensi kosong -> tidak dinilai
        self.assertEqual(e["reference_valid"], 0); self.assertIsNone(e["sbert_doc"]); self.assertIsNone(e["ref_doc_truncated"])
        names = {(b["baseline"], b["unit_id"]) for b in R["baselines"]}
        for x in ("self_reference", "timestamp_only", "cite_all", "mismatch_reference", "mismatch_report", "mismatch_report_tl"):
            self.assertIn((x, "u-edge"), names); self.assertIn((x, "ALL_UNITS_MEAN"), names)
        ts = [b for b in R["baselines"] if b["baseline"] == "timestamp_only" and b["unit_id"] == "u-edge"][0]
        self.assertEqual(ts["hyp_segments"], 2)
        self.assertEqual(sb.timestamp_only_text(EV), "00:34:27\n00:34:30")
        self.assertEqual(sb.cite_all_text(UNITS["u-edge"]["digest_text"]).count("\n"), 1)
        self.assertNotIn("Scope", sb.cite_all_text(UNITS["u-edge"]["digest_text"])); self.assertNotIn("[E01]", sb.cite_all_text(UNITS["u-edge"]["digest_text"]))

    def test_identical_text_scores_one(self):
        u = {"u": {"ref_lines": ["00:34:27 Application Launch: Microsoft Edge was launched"], "evidence": EV, "digest_text": ""}}
        run = {"model_tag": "m", "backend": "x", "strategy": "P1", "unit_id": "u", "status": "OK", "finish_reason": "stop",
               "text": report("00:34:27 Application Launch: Microsoft Edge was launched")}
        r = sb.compute(FakeEncoder(), [run], u, 5)["rows"][0]
        self.assertAlmostEqual(r["tl_sbert_doc"], 1.0, places=6); self.assertAlmostEqual(r["tl_sbert_line_f1"], 1.0, places=6)
        self.assertIsNone(r["mismatch_doc_mean"])                                       # tidak ada unit lain

    def test_truncation_flags(self):
        R = sb.compute(FakeEncoder(max_seq_length=6), RUNS, UNITS, 5); a = [r for r in R["rows"] if r["unit_id"] == "u-edge"][0]
        self.assertEqual(a["hyp_doc_truncated"], 1); self.assertEqual(a["ref_doc_truncated"], 1); self.assertEqual(a["any_truncated"], 1)
        self.assertGreater(a["ref_line_trunc_n"], 0)
        R2 = sb.compute(FakeEncoder(max_seq_length=10_000), RUNS, UNITS, 5)
        self.assertTrue(all(r["any_truncated"] == 0 for r in R2["rows"]))

    def test_deterministic_and_order_independent(self):
        A = sb.compute(FakeEncoder(), RUNS, UNITS, 5); B = sb.compute(FakeEncoder(), RUNS, UNITS, 5)
        self.assertEqual(sb.table(A["rows"], sb.COLS), sb.table(B["rows"], sb.COLS))
        self.assertEqual(sb.table(A["baselines"], sb.BASE_COLS), sb.table(B["baselines"], sb.BASE_COLS))
        C = sb.compute(FakeEncoder(), list(reversed(RUNS)), UNITS, 5)
        key = lambda r: (r["unit_id"], r["strategy"])
        self.assertEqual(sb.table(sorted(A["rows"], key=key), sb.COLS), sb.table(sorted(C["rows"], key=key), sb.COLS))
        enc = FakeEncoder(); c = sb.Cache(enc); c.prime(["b", "a", "b"]); c.prime(["a"]); self.assertEqual(enc.calls, 1)

    def test_summary_subsets(self):
        R = sb.compute(FakeEncoder(), RUNS, UNITS, 5); S = sb.summary_rows(R["rows"])
        subsets = {(s[0], s[3]) for s in S}
        self.assertIn(("all", "P2"), subsets); self.assertNotIn(("VALID", "P2"), subsets)    # P2 TRUNCATED -> tidak masuk VALID
        row = [s for s in S if s[0] == "all" and s[3] == "P1" and s[4] == "sbert_doc"][0]
        self.assertEqual(row[5], 3); self.assertEqual(row[6], 2)                            # n_reports=3, n nilai tak kosong=2 (u-empty None)

    def test_hash_tree_excludes_output_and_detects_change(self):
        with tempfile.TemporaryDirectory() as d:
            r = Path(d); (r / "a").mkdir(); (r / "a" / "x.txt").write_text("1"); out = r / "unit_task" / "13_sbert"; out.mkdir(parents=True)
            (out / "y.csv").write_text("z"); h1 = sb.hash_tree(r, out)
            self.assertEqual(list(h1), ["a/x.txt"])
            (out / "y.csv").write_text("changed"); self.assertEqual(sb.hash_tree(r, out), h1)
            (r / "a" / "x.txt").write_text("2"); self.assertNotEqual(sb.manifest_digest(sb.hash_tree(r, out)), sb.manifest_digest(h1))

    def test_output_paths_and_no_model_import_at_load(self):
        self.assertEqual(sb.STAGE, "13_sbert"); self.assertNotIn("sentence_transformers", sys.modules)   # model/pustaka hanya dimuat oleh SbertEncoder
        self.assertTrue(math.isclose(sb.SELF_TOL, 1e-5))


if __name__ == "__main__":
    unittest.main()
