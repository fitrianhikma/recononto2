"""Unit test kecil V1 (tanpa dataset, tanpa rdflib, tanpa jaringan eksternal). Jalankan: python3 -m unittest discover -s tests -v"""
import http.server, importlib.util, io, json, math, os, sys, tempfile, threading, time, unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src")); sys.path.insert(0, str(ROOT))
import config, extra_metrics as xm, keywords, report_metrics as rm, tasks as tk  # noqa: E402
import run as runner  # noqa: E402


def _load(modname: str, filename: str):
    """09_prompts.py / 11_run_llm.py berawalan angka: tidak bisa 'import' biasa, pakai importlib."""
    spec = importlib.util.spec_from_file_location(modname, ROOT / "src" / filename)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


sp = _load("prompts_09", "09_prompts.py")
s11 = _load("run_llm_11", "11_run_llm.py")


class TestKeywords(unittest.TestCase):
    def test_literal_brackets(self):
        kw = "[104 / 0x0068] Provider identifier: \\{[a-f0-9\\-]+\\} Source Name: Microsoft-Windows-Eventlog"
        msg = "[104 / 0x0068] Provider identifier: {fc65ddd8-d6ef-4962-83d5-6e5cfe9ce148} Source Name: Microsoft-Windows-Eventlog Strings: ['x']"
        import re
        self.assertIsNone(re.search(kw, msg), "pola as-is memang tidak cocok (character class)")
        self.assertIsNotNone(re.search(keywords.literal_brackets(kw), msg))
        self.assertIsNotNone(re.search(keywords.literal_brackets("Prefetch [REGEDIT.EXE] was executed"), "Prefetch [REGEDIT.EXE] was executed. Run count 1"))
        esc = "\\[HKEY_LOCAL_MACHINE\\\\System\\]"; self.assertEqual(keywords.literal_brackets(esc), esc, "kurung yang sudah di-escape tidak berubah")


class TestLexical(unittest.TestCase):
    hyp, ref = "the cat sat on the mat".split(), "the cat is on the mat".split()

    def test_rouge(self):
        self.assertAlmostEqual(xm.rouge_n(self.hyp, self.ref, 1), 5 / 6)
        self.assertAlmostEqual(xm.rouge_n(self.hyp, self.ref, 2), 0.6)
        self.assertAlmostEqual(xm.rouge_l(self.hyp, self.ref), 5 / 6)

    def test_bleu(self):
        self.assertEqual(xm.bleu(self.hyp, self.ref), 0.0, "4-gram nol -> BLEU tanpa smoothing = 0")
        exp = math.exp((math.log(5 / 6) + math.log(3 / 5) + math.log(1 / 4) + math.log(0.1 / 3)) / 4)
        self.assertAlmostEqual(xm.bleu(self.hyp, self.ref, smooth=True), exp)
        self.assertAlmostEqual(xm.bleu(self.ref, self.ref), 1.0)
        short = "the cat".split(); self.assertLess(xm.bleu(short, self.ref, smooth=True), xm.bleu(self.ref, self.ref))

    def test_reference_gate_and_strip(self):
        r = xm.lexical_scores("SUMMARY: x [E01]", [], min_ref_tokens=5); self.assertEqual(r["reference_valid"], 0.0); self.assertIsNone(r["bleu"])
        self.assertNotIn("e01", xm.tokens(xm.strip_report("SUMMARY: firefox.exe ran [E01].\nTIMELINE:\n[E01] 00:46:08 w3schools.com")))
        self.assertIn("00:46:08", xm.tokens("at 00:46:08 x")); self.assertIn("firefox.exe", xm.tokens("Firefox.exe ran"))


class TestTaskMetrics(unittest.TestCase):
    def test_prf(self):
        ev = [{"id": "E01", "row_hash": "a", "timestamp": "2023-12-26T00:01:02"}, {"id": "E02", "row_hash": "b", "timestamp": "2023-12-26T00:01:03"},
              {"id": "E03", "row_hash": "c", "timestamp": "2023-12-26T00:01:04"}]
        groups = [{"identity": 1, "mult": 3, "hashes": {"a"}}, {"identity": 2, "mult": 1, "hashes": {"z"}}]
        m = xm.task_metrics(groups, ev, {"E01", "E02"}, {"E01", "E02"}, {"a", "z"})
        self.assertEqual(m["t_precision"], 0.5); self.assertEqual(m["t_recall"], 0.5); self.assertAlmostEqual(m["t_f1"], 0.5)
        self.assertEqual(m["t_recall_weighted"], 0.75); self.assertEqual(m["t_recall_conditional"], 1.0); self.assertEqual(m["t_gt_items_raw"], 4.0)
        none = xm.task_metrics(groups, ev, set(), set(), {"a"}); self.assertIsNone(none["t_precision"]); self.assertEqual(none["t_recall"], 0.0)

    def test_cited_matches_m1(self):
        ev = [{"id": "E01", "row_hash": "a", "timestamp": "2023-12-26T00:01:02", "label": "x", "event_type": "T"}]
        c, men = xm.cited_and_mentioned("SUMMARY: ok [E01][E09]. At 00:01:02.", ev); self.assertEqual(c, {"E01"}); self.assertEqual(men, {"E01"})


class TestTasks(unittest.TestCase):
    def test_identity_set_semantics(self):
        a = {"type": "Web Visit", "date_time_min": "2023-12-26 00:45:24.1+00:00", "evidence_source": "https://x  a\\\\b", "description": "Web Visit to 'x'"}
        b = {"type": "Web Visit", "date_time_min": "2023-12-26 00:45:24.9+00:00", "evidence_source": "https://x a\\b", "description": "Web Visit to 'x'"}
        c = dict(a, evidence_source="https://y", description="Web Visit to 'y'")
        g = tk.group_items("scenario1", [a, b, c]); self.assertEqual(len(g), 2); self.assertEqual(g[0]["mult"], 2)
        lines = tk.s1_reference_lines([c, a, b]); self.assertEqual(len(lines), 2); self.assertTrue(lines[0].startswith("00:45:24 Web Visit"))

    def test_s1_reference_dedupes_identical_text_across_evidence_sources(self):
        """Baris identik dari evidence_source berbeda = satu baris referensi, tetapi tetap dua butir GT untuk P/R/F1."""
        base = {"type": "Program opened", "date_time_min": "2023-12-26 00:36:59.1+00:00", "description": "A Windows program cmd.exe was opened"}
        a, b = dict(base, evidence_source="NTFS:\\Windows\\System32\\cmd.exe"), dict(base, evidence_source="NTFS:\\Windows\\WinSxS\\cmd.exe")
        self.assertEqual(tk.s1_reference_lines([a, b]), ["00:36:59 Program opened: A Windows program cmd.exe was opened"])
        g = tk.group_items("scenario1", [a, b]); self.assertEqual([x["mult"] for x in g], [1, 1], "identitas P/R/F1 tidak berubah")

    def test_s1_reference_dedupe_case_and_whitespace_keeps_first_text(self):
        """Varian yang tokennya sama bagi BLEU/ROUGE (huruf besar/kecil, spasi) dihitung satu; teks kemunculan pertama dipertahankan."""
        base = {"type": "Program opened", "date_time_min": "2023-12-26 00:44:11+00:00"}
        lines = tk.s1_reference_lines([dict(base, evidence_source="a", description="A Windows program DfrgUI.exe was opened"),
                                       dict(base, evidence_source="b", description="A Windows  program dfrgui.exe was opened")])
        self.assertEqual(lines, ["00:44:11 Program opened: A Windows program DfrgUI.exe was opened"])

    def test_s1_reference_keeps_distinct_time_type_description_and_date(self):
        it = {"type": "Web Visit", "date_time_min": "2023-12-26 00:34:59+00:00", "evidence_source": "e", "description": "Web Visit to 'msn.com'"}
        variants = [it, dict(it, date_time_min="2023-12-26 00:35:00+00:00"), dict(it, type="Google Search"), dict(it, description="Web Visit to 'bing.com'"),
                    dict(it, date_time_min="2023-12-27 00:34:59+00:00")]
        self.assertEqual(len(tk.s1_reference_lines(variants)), 5)

    def test_s1_reference_duplicates_no_longer_lower_lexical_scores(self):
        """Laporan yang persis sama dengan satu baris referensi harus bernilai sempurna; duplikasi referensi dulu menurunkannya."""
        base = {"type": "Program opened", "date_time_min": "2023-12-26 00:36:59+00:00", "description": "A Windows program cmd.exe was opened"}
        ref = tk.s1_reference_lines([dict(base, evidence_source=str(i)) for i in range(4)])
        r = xm.lexical_scores("00:36:59 Program opened: A Windows program cmd.exe was opened", ref)
        for k in ("bleu", "rouge1_f", "rouge2_f", "rougeL_f", "mean_bleu_rouge"): self.assertAlmostEqual(r[k], 1.0, msg=k)

    def test_s1_reference_real_gt_counts_if_data_present(self):
        if not (config.TASKS_DIR / "event-summarization" / "ground-truth-single").exists(): self.skipTest("data/tasks belum diekstrak")
        by = {t["task"]: t for t in tk.list_tasks("scenario1")}
        counts = {n: len(tk.s1_reference_lines(tk.read_gt(by[n], "single"))) for n in ("1-open-bing", "4-open-mozilla-org", "9-launch-firefox", "14-shutdown")}
        self.assertEqual(counts, {"1-open-bing": 7, "4-open-mozilla-org": 47, "9-launch-firefox": 12, "14-shutdown": 1})
        for t in by.values():
            L = tk.s1_reference_lines(tk.read_gt(t, "single")); self.assertEqual(len(L), len({tuple(xm.tokens(x)) for x in L}), t["task"])

    def test_units_counts_if_data_present(self):
        if not (config.TASKS_DIR / "grep" / "ground-truth").exists(): self.skipTest("data/tasks belum diekstrak")
        n = sum(len(tk.units(s, "task")) for s in config.SCENARIOS); self.assertEqual(n, 26)
        self.assertEqual(sum(len(tk.units(s, "scenario")) for s in config.SCENARIOS), 3)


class TestPrompts(unittest.TestCase):
    def setUp(self):
        self.ev = [{"id": f"E{i:02d}", "event_iri": f"https://x/s1/event/f/{i:05d}", "parser": f"p{i}", "row_hash": str(i), "timestamp": "2023-12-26T00:00:00", "label": "l"} for i in range(1, 9)]
        self.pairs = [{"event_a": f"https://x/s1/event/f/{a:05d}", "event_b": f"https://x/s1/event/f/{b:05d}", "delta_t_s": float(d), "corr_t": 1.0, "corr_s": 0.0, "corr_o": 1.0,
                       "ek": "1" if s == 1.0 else "0", "score": s} for a, b, d, s in [(1, 2, 3, 1.0), (2, 3, 0, 0.9), (3, 4, 1, 0.9), (4, 5, 0, 0.6), (5, 6, 0, 0.55), (6, 7, 0, 0.51), (1, 99, 0, 1.0)]]

    def test_top5_with_source_labels(self):
        b = sp.correlation_block(self.pairs, self.ev, 5)
        self.assertEqual(b["pairs_shown"], 5); first = b["text"].splitlines()[0]
        self.assertTrue(first.startswith("[E01] (p1) and [E02] (p2): score 1.00") and "expert rule R1" in first)
        self.assertNotIn("0.51", b["text"].split("pairs scored")[0].rsplit("\n", 2)[0])

    def test_only_one_block_differs(self):
        r = sp.build_prompts("Scope: x\n[E01] 00:00:00 p1 T: l\n", self.ev, self.pairs, 5)
        p1, p2, p3 = (r["prompts"][k] for k in ("P1", "P2", "P3"))
        self.assertTrue(p2.startswith(p1.rstrip("\n"))); self.assertIn("CORRELATIONS", p2); self.assertNotIn("CORRELATIONS", p3)
        self.assertIn("EXAMPLE REPORT", p3); tail = "EVIDENCE\n" + p1.split("EVIDENCE\n", 1)[1]
        self.assertTrue(p3.endswith(tail)); self.assertTrue(p3.startswith(p1.split("EVIDENCE\n", 1)[0].rstrip("\n")))

    def test_example_leak_check(self):
        ex = (config.PROMPTS_DIR / "format_example.txt").read_text(encoding="utf-8")
        ok = sp.example_leak_check(ex, "Scope\n[E01] 05:11:02 x", [{"id": "E01"}], 90)
        self.assertTrue(ok["ok"]); self.assertEqual(ok["WARN_times_in_digest"], ["05:11:02"])
        bad = sp.example_leak_check(ex, "[E01] 01:00:00 visited quillfast", [{"id": "E01"}], 90); self.assertFalse(bad["ok"])
        bad2 = sp.example_leak_check(ex, "x", [{"id": "E90"}], 90); self.assertFalse(bad2["ok"])

    def test_example_obeys_old_rules(self):
        ex = (config.PROMPTS_DIR / "format_example.txt").read_text(encoding="utf-8").split("\n", 1)[1]
        c = rm.rule_compliance(ex); self.assertEqual(c["m8_compliance_share"], 1.0, c)
        self.assertEqual(rm.evaluate_run(ex, "", [])["metrics"]["m0_format_exact"], 1.0)


class TestDuplicateContentGroups(unittest.TestCase):
    """PERBAIKAN V2 #1 (docs/CHANGELOG_V2.md): correlation_block() salah menghitung ringkasan P2 untuk unit yang
    berkas nominalnya isinya identik dengan berkas lain ('without-regex' tersingkir total dari pairs.csv karena
    kanonikalisasi hasRowHash di correlation.load_events(), bukan dipindah - lihat docs/CHANGELOG_V2.md). Uji ini
    memakai data sintetis yang menirukan situasi scenario3 4616-with-regex/4616-without-regex: dua berkas isi
    identik, tapi hanya satu (file_a) yang punya pasangan di pairs.csv; file_b sama sekali tidak muncul di sana."""

    def test_expand_with_duplicate_groups_none_passthrough(self):
        self.assertIsNone(sp.expand_with_duplicate_groups(None, [{"a.csv", "b.csv"}]))

    def test_expand_with_duplicate_groups_unrelated_unit_unchanged(self):
        self.assertEqual(sp.expand_with_duplicate_groups({"c.csv"}, [{"a.csv", "b.csv"}]), {"c.csv"})

    def test_expand_with_duplicate_groups_expands_sibling(self):
        self.assertEqual(sp.expand_with_duplicate_groups({"b.csv"}, [{"a.csv", "b.csv"}]), {"a.csv", "b.csv"})

    def test_load_duplicate_groups_missing_file_reported_not_empty_assumed(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = sp.load_duplicate_groups("scenario9", root=Path(tmp))
            self.assertEqual(r["groups"], []); self.assertEqual(r["source"], "MISSING")      # dilaporkan, bukan diam-diam dianggap tidak ada duplikat

    def test_load_duplicate_groups_reads_audit_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); d = root / "results" / "01_audit"; d.mkdir(parents=True)
            (d / "audit_scenario3.json").write_text(json.dumps({"identical_content_groups": [["4616-with-regex.csv", "4616-without-regex.csv"]]}), encoding="utf-8")
            r = sp.load_duplicate_groups("scenario3", root=root)
            self.assertEqual(r["source"], "audit_json"); self.assertEqual(r["groups"], [{"4616-with-regex.csv", "4616-without-regex.csv"}])

    def test_correlation_block_scope_fixed_for_sibling_file_bug(self):
        # file_a punya event yang muncul di pairs.csv; file_b isinya identik tapi event-nya TIDAK muncul di pairs.csv sama sekali
        # (menirukan kanonikalisasi hasRowHash correlation.load_events() yang menyingkirkan event file_b, bukan memindahkannya).
        ev_a = [{"id": "E01", "event_iri": "https://x/s3/event/file_a/00001", "parser": "p"}, {"id": "E02", "event_iri": "https://x/s3/event/file_a/00002", "parser": "p"}]
        ev_b = [{"id": "E01", "event_iri": "https://x/s3/event/file_b/00001", "parser": "p"}, {"id": "E02", "event_iri": "https://x/s3/event/file_b/00002", "parser": "p"}]
        pairs = [{"event_a": "https://x/s3/event/file_a/00001", "event_b": "https://x/s3/event/file_a/00002", "delta_t_s": 0.1, "corr_t": 1.0, "corr_s": 0.0, "corr_o": 1.0, "ek": "0", "score": 0.6666}]
        dup_groups = [{"file_a.csv", "file_b.csv"}]
        # SEBELUM perbaikan (source_files tidak diperluas): unit file_b selalu '0 of 0' walau buktinya sama dengan file_a.
        cb_a_broken = sp.correlation_block(pairs, ev_a, 5, {"file_a.csv"})
        cb_b_broken = sp.correlation_block(pairs, ev_b, 5, {"file_b.csv"})
        self.assertEqual(cb_a_broken["pairs_ge_tau_in_scope"], 1); self.assertEqual(cb_b_broken["pairs_ge_tau_in_scope"], 0)      # inilah bug yang ditemukan
        # SESUDAH perbaikan (run_scenario() memperluas source_files lewat expand_with_duplicate_groups() sebelum memanggil ini):
        sf_a = sp.expand_with_duplicate_groups({"file_a.csv"}, dup_groups); sf_b = sp.expand_with_duplicate_groups({"file_b.csv"}, dup_groups)
        cb_a_fixed = sp.correlation_block(pairs, ev_a, 5, sf_a); cb_b_fixed = sp.correlation_block(pairs, ev_b, 5, sf_b)
        self.assertEqual(cb_a_fixed["pairs_ge_tau_in_scope"], 1); self.assertEqual(cb_b_fixed["pairs_ge_tau_in_scope"], 1)        # sekarang sama - sesuai bukti yang identik
        # kalimat ringkasan (baris terakhir sebelum skala) kini sama untuk kedua unit - inilah baris yang berbeda pada kasus nyata 4616-with-regex/4616-without-regex
        self.assertEqual(cb_a_fixed["text"].splitlines()[-2], cb_b_fixed["text"].splitlines()[-2])
        self.assertNotEqual(cb_a_broken["text"].splitlines()[-2], cb_b_broken["text"].splitlines()[-2])      # sebelum perbaikan: baris ini berbeda (bug)


class _Mock(http.server.BaseHTTPRequestHandler):
    calls = []
    def log_message(self, *a): pass
    def _send(self, body, code=200):
        b = json.dumps(body).encode(); self.send_response(code); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        if self.path == "/api/version": return self._send({"version": "test"})
        if self.path == "/api/tags": return self._send({"models": [{"name": "qwen2.5:0.5b"}]})
        self._send({"error": "nf"}, 404)
    def do_POST(self):
        n = int(self.headers["Content-Length"]); p = json.loads(self.rfile.read(n)); _Mock.calls.append(p)
        self._send({"model": p["model"], "message": {"content": "SUMMARY: test [E01].\nTIMELINE:\n[E01] 00:00:00 x\nFINDINGS:\n- y [E01]\nLIMITATIONS:\n- z"},
                    "prompt_eval_count": 100, "eval_count": 20, "done_reason": "stop"})


class TestRunner(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.old = (config.ROOT, config.RESULTS); config.ROOT = Path(self.tmp.name); config.RESULTS = config.ROOT / "results"
        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Mock); threading.Thread(target=self.srv.serve_forever, daemon=True).start(); _Mock.calls.clear()
        self.st = config.load_settings(); self.st["ollama_url"] = f"http://127.0.0.1:{self.srv.server_port}"
        base = config.unit_dir("task") / "09_prompts" / "scenario3"; idx = {"status": "OK", "units": {}}
        for uid in ("a", "b"):                                       # dua unit dengan prompt identik
            d = base / uid; d.mkdir(parents=True)
            for p in ("P1", "P2", "P3"): (d / f"{p}.txt").write_text(f"prompt {p}\n", encoding="utf-8")
            idx["units"][uid] = {p: s11.lc.sha(f"prompt {p}\n") for p in ("P1", "P2", "P3")}
        (base / "prompts_index.json").write_text(json.dumps(idx), encoding="utf-8")

    def tearDown(self):
        self.srv.shutdown(); self.srv.server_close(); config.ROOT, config.RESULTS = self.old; self.tmp.cleanup()

    def test_dedupe_and_resume(self):
        items = s11.plan(self.st, "task", ["scenario3"], ["P1", "P2", "P3"], ["qwen2.5-0.5b"])
        self.assertEqual(len(items), 6)
        with redirect_stdout(io.StringIO()): c = s11.execute(self.st, "task", items)
        self.assertEqual(c, {"OK": 3, "REUSED": 3}); self.assertEqual(len(_Mock.calls), 3)
        self.assertEqual(_Mock.calls[0]["options"]["temperature"], 0); self.assertEqual(_Mock.calls[0]["options"]["num_ctx"], 4096)
        rec = json.loads(s11.run_paths("task", "qwen2.5-0.5b", "scenario3", "b", "P1")["json"].read_text()); self.assertFalse(rec["llm_call"]); self.assertEqual(rec["unit_id"], "b")
        with redirect_stdout(io.StringIO()): c2 = s11.execute(self.st, "task", items)
        self.assertEqual(c2, {"SKIP_SUDAH_SAH": 6}); self.assertEqual(len(_Mock.calls), 3)

    def test_cloud_gate(self):
        items = s11.plan(self.st, "task", ["scenario3"], ["P1"], backend="openrouter")
        with self.assertRaises(PermissionError): s11.cloud_gate(self.st, items, confirm=False)
        os.environ["OPENROUTER_API_KEY_TEST"] = "x"; self.st["openrouter_api_key_env"] = "OPENROUTER_API_KEY_TEST"
        with self.assertRaises(PermissionError): s11.cloud_gate(self.st, items, confirm=True)          # snapshot belum ada
        snap = {"checked_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "models": {m["model"]: {"available": True, "usd_per_token_input": 1e-7, "usd_per_token_output": 2e-7} for m in self.st["models"] if m["backend"] == "openrouter"}}
        p = config.RESULTS / "10_models" / "openrouter_snapshot.json"; p.parent.mkdir(parents=True); p.write_text(json.dumps(snap))
        g = s11.cloud_gate(self.st, items, confirm=True); self.assertTrue(g["needed"]); self.assertLess(g["estimate"]["total_est_usd_upper_bound"], 0.01)
        self.assertEqual(sum(v["calls"] for v in g["estimate"]["per_model"].values()), 2, "prompt identik dihitung sekali per model")
        self.st["cloud_guard"]["max_estimated_cost_usd"] = 1e-9
        with self.assertRaises(PermissionError): s11.cloud_gate(self.st, items, confirm=True)
        snap["checked_utc"] = "2020-01-01T00:00:00Z"; p.write_text(json.dumps(snap)); self.st["cloud_guard"]["max_estimated_cost_usd"] = 1.0
        with self.assertRaises(PermissionError): s11.cloud_gate(self.st, items, confirm=True)
        del os.environ["OPENROUTER_API_KEY_TEST"]


class TestV3Stage11Progress(unittest.TestCase):
    """PERBAIKAN V3 (11_run_llm.py): pengujian terarah dengan Ollama tiruan (mock server `_Mock`, tanpa jaringan/model
    nyata). Hanya menguji tampilan/orkestrasi baru (progres, [RUNNING]/[SKIP]/[REUSED]/[WAITING], isolasi error
    tak terduga, Ctrl-C) - TIDAK menguji ulang logika resume/skip/OK (sudah dicakup TestRunner.test_dedupe_and_resume,
    yang tetap lulus tanpa perubahan di atas kode V3 ini)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.old = (config.ROOT, config.RESULTS); config.ROOT = Path(self.tmp.name); config.RESULTS = config.ROOT / "results"
        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Mock); threading.Thread(target=self.srv.serve_forever, daemon=True).start(); _Mock.calls.clear()
        self.st = config.load_settings(); self.st["ollama_url"] = f"http://127.0.0.1:{self.srv.server_port}"
        base = config.unit_dir("task") / "09_prompts" / "scenario3"; idx = {"status": "OK", "units": {}}
        for uid in ("a", "b"):                                       # dua unit dengan prompt identik (pemicu REUSED)
            d = base / uid; d.mkdir(parents=True)
            for p in ("P1", "P2", "P3"): (d / f"{p}.txt").write_text(f"prompt {p}\n", encoding="utf-8")
            idx["units"][uid] = {p: s11.lc.sha(f"prompt {p}\n") for p in ("P1", "P2", "P3")}
        (base / "prompts_index.json").write_text(json.dumps(idx), encoding="utf-8")

    def tearDown(self):
        self.srv.shutdown(); self.srv.server_close(); config.ROOT, config.RESULTS = self.old; self.tmp.cleanup()

    def test_progress_numbers_and_running_reused_skip_messages(self):
        items = s11.plan(self.st, "task", ["scenario3"], ["P1", "P2", "P3"], ["qwen2.5-0.5b"]); self.assertEqual(len(items), 6)
        logs = []; c = s11.execute(self.st, "task", items, log=logs.append)
        self.assertEqual(c, {"OK": 3, "REUSED": 3})
        running = [l for l in logs if " RUNNING | " in l]; reused = [l for l in logs if " REUSED dari " in l]
        self.assertEqual(len(running), 3); self.assertEqual(len(reused), 3)
        self.assertTrue(running[0].startswith("[1/6] RUNNING | qwen2.5-0.5b | scenario3 | a | P1"))     # nomor progres i/N persis
        self.assertTrue(all(l.split("]", 1)[0].lstrip("[").split("/")[1] == "6" for l in logs), "total N selalu 6 di setiap baris")
        ok_lines = [l for l in logs if " OK | " in l]; self.assertEqual(len(ok_lines), 3)
        # kedua kali dijalankan ulang (resume): semua kombinasi sudah sah -> SKIP, dengan teks verbatim yang disyaratkan
        logs2 = []; c2 = s11.execute(self.st, "task", items, log=logs2.append)
        self.assertEqual(c2, {"SKIP_SUDAH_SAH": 6}); self.assertEqual(len(_Mock.calls), 3, "tidak ada panggilan LLM baru saat semua sudah SKIP")
        self.assertEqual(len(logs2), 6)
        for i, l in enumerate(logs2, 1):
            self.assertTrue(l.startswith(f"[{i}/6] SKIP — sudah berhasil dijalankan sebelumnya | "), l)   # teks verbatim wajib

    def test_heartbeat_waits_then_stops_cleanly_on_success(self):
        """Thread [WAITING] harus muncul selagi menunggu satu respons yang lambat, dan harus berhenti bersih begitu
        respons datang (eksekusi lanjut tanpa macet - lihat assertFalse(hb hidup) tersirat dari waktu tes selesai)."""
        old_interval = s11.HEARTBEAT_INTERVAL_S; s11.HEARTBEAT_INTERVAL_S = 0.05
        orig_do_post = _Mock.do_POST
        def slow_do_post(self_):
            time.sleep(0.25); orig_do_post(self_)
        _Mock.do_POST = slow_do_post
        try:
            items = s11.plan(self.st, "task", ["scenario3"], ["P1"], ["qwen2.5-0.5b"])
            logs = []; c = s11.execute(self.st, "task", items, log=logs.append)
            self.assertEqual(c, {"OK": 1, "REUSED": 1})
            waiting = [l for l in logs if "[WAITING]" in l]
            self.assertGreaterEqual(len(waiting), 1, "harus ada minimal satu baris [WAITING] selama panggilan yang lambat")
            self.assertIn("elapsed=", waiting[0])
        finally:
            s11.HEARTBEAT_INTERVAL_S = old_interval; _Mock.do_POST = orig_do_post

    def test_heartbeat_helper_stops_immediately_when_stop_is_set(self):
        """Uji langsung _heartbeat(): memverifikasi ketentuan 'heartbeat harus berhenti dengan aman' tanpa tergantung
        pada server tiruan - mencakup kondisi berhenti sukses/gagal/Ctrl-C karena ketiganya memicu `stop.set()` yang
        sama di `execute()` (blok `finally`)."""
        old_interval = s11.HEARTBEAT_INTERVAL_S; s11.HEARTBEAT_INTERVAL_S = 0.03
        try:
            logs = []; stop = threading.Event(); t0 = time.time()
            hb = threading.Thread(target=s11._heartbeat, args=(stop, "label-uji", t0, logs.append), daemon=True); hb.start()
            time.sleep(0.12)                      # cukup untuk >=1 tik [WAITING]
            stop.set(); hb.join(timeout=1.0)
            self.assertFalse(hb.is_alive(), "thread heartbeat harus benar-benar berhenti setelah stop.set()")
            self.assertTrue(any(l.startswith("[WAITING] label-uji | elapsed=") for l in logs))
        finally:
            s11.HEARTBEAT_INTERVAL_S = old_interval

    def test_unexpected_error_isolated_per_job_and_stage12_compatible_failed_json(self):
        """Error tak terduga (bukan LLMError, mis. bug/IO) pada satu job tidak boleh menghentikan sisa rencana, dan
        `.failed.json` yang dihasilkan harus tetap memuat field yang dibaca `collect()` di 12_evaluate.py
        (model_tag/scenario/unit_id/strategy/status/note)."""
        items = s11.plan(self.st, "task", ["scenario3"], ["P1", "P2", "P3"], ["qwen2.5-0.5b"])
        orig_call = s11.call
        def flaky(m, prompt, st, key):
            if "P2" in prompt: raise RuntimeError("disk penuh (simulasi)")
            return orig_call(m, prompt, st, key)
        s11.call = flaky
        try:
            logs = []; c = s11.execute(self.st, "task", items, log=logs.append)
            # 4 job P1/P3 (a,b) sukses OK; 2 job P2 (a,b) gagal tak terduga - keduanya tetap DIPROSES (bukan dihentikan)
            self.assertEqual(c, {"OK": 2, "REUSED": 2, s11.UNEXPECTED_FAIL_STATUS: 2})
            self.assertEqual(len(items), sum(c.values()), "seluruh rencana tetap diproses walau ada error tak terduga")
            fail_lines = [l for l in logs if s11.UNEXPECTED_FAIL_STATUS in l]; self.assertEqual(len(fail_lines), 2)
            fp = s11.run_paths("task", "qwen2.5-0.5b", "scenario3", "a", "P2")["failed"]
            self.assertTrue(fp.exists()); rec = json.loads(fp.read_text(encoding="utf-8"))
            for field in ("model_tag", "scenario", "unit_id", "strategy", "status", "note"):    # skema minimal yang dibaca collect() Stage 12
                self.assertIn(field, rec)
            self.assertEqual(rec["status"], s11.UNEXPECTED_FAIL_STATUS); self.assertIn("disk penuh", rec["note"])
            self.assertEqual(rec["model_tag"], "qwen2.5-0.5b"); self.assertEqual(rec["scenario"], "scenario3")
            self.assertEqual(rec["unit_id"], "a"); self.assertEqual(rec["strategy"], "P2")
            self.assertFalse((fp.parent / "P2.json").exists(), "tidak boleh ada P2.json sah saat job tak terduga gagal")
        finally:
            s11.call = orig_call

    def test_ctrl_c_during_execute_is_reported_not_raised_raw(self):
        """Ctrl-C (KeyboardInterrupt) saat menunggu respons tidak boleh menghentikan heartbeat secara kotor, dan harus
        tetap dilempar ke pemanggil (main()) tanpa tertangkap diam-diam oleh `except Exception` di execute()."""
        items = s11.plan(self.st, "task", ["scenario3"], ["P1"], ["qwen2.5-0.5b"])
        orig_call = s11.call
        def interrupt(m, prompt, st, key): raise KeyboardInterrupt
        s11.call = interrupt
        try:
            logs = []
            with self.assertRaises(KeyboardInterrupt):
                s11.execute(self.st, "task", items, log=logs.append)
            self.assertFalse(any(s11.UNEXPECTED_FAIL_STATUS in l for l in logs), "Ctrl-C tidak boleh tercatat sebagai GAGAL_TAK_TERDUGA (harus tetap menjalar, bukan tertangkap except Exception)")
        finally:
            s11.call = orig_call


class TestV3Main(unittest.TestCase):
    """main(): Ctrl-C ditangani rapi (kode keluar 130, tanpa traceback mentah) - diuji dengan menyuntik
    KeyboardInterrupt pada execute() (monkeypatch), tanpa pengaturan/server tiruan karena plan()/cloud_gate()
    juga disuntik agar tidak perlu data/prompt nyata."""

    def test_main_returns_130_on_keyboard_interrupt_without_traceback(self):
        st = config.load_settings()
        orig_load, orig_plan, orig_gate, orig_exec = config.load_settings, s11.plan, s11.cloud_gate, s11.execute
        config.load_settings = lambda: st
        s11.plan = lambda *a, **k: []
        s11.cloud_gate = lambda *a, **k: {"needed": False}
        def boom(*a, **k): raise KeyboardInterrupt
        s11.execute = boom
        try:
            buf = io.StringIO()
            with redirect_stdout(buf): rc = s11.main(["--backend", "ollama"])
            self.assertEqual(rc, 130)
            self.assertIn("DIHENTIKAN oleh pengguna (Ctrl-C)", buf.getvalue())
            self.assertNotIn("Traceback", buf.getvalue())
        finally:
            config.load_settings, s11.plan, s11.cloud_gate, s11.execute = orig_load, orig_plan, orig_gate, orig_exec


class TestRunPy(unittest.TestCase):
    def test_ranges(self):
        self.assertEqual(runner.stage_range("02-04"), ["02", "03", "04"])
        with self.assertRaises(SystemExit): runner.stage_range("08-12")
        self.assertIsNone(runner.command("06", "1", None, [])); self.assertIn("--verify-determinism", runner.command("05", "2", None, []))


class TestSettings(unittest.TestCase):
    def test_models(self):
        st = config.load_settings(); tags = {m["tag"]: m for m in st["models"]}
        self.assertEqual(set(tags), {"qwen2.5-0.5b", "qwen2.5-1.5b", "llama-3.1-8b", "qwen-2.5-7b"})
        self.assertEqual(tags["llama-3.1-8b"]["model"], "meta-llama/llama-3.1-8b-instruct"); self.assertEqual(tags["qwen-2.5-7b"]["model"], "qwen/qwen-2.5-7b-instruct")
        self.assertEqual(st["prompt"]["p2_top_pairs"], 5)


if __name__ == "__main__":
    unittest.main()
