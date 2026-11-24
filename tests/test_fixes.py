"""Unit test perbaikan MIN-01, MIN-02, MIN-04 (tanpa data, tanpa jaringan, tanpa menjalankan stage; menulis hanya ke folder sementara).
Jalankan: python3 -m unittest tests.test_fixes -v   (atau: python3 -m unittest discover -s tests -v)"""
import importlib.util, io, json, sys, tempfile, unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src")); sys.path.insert(0, str(ROOT / "tools"))
import config, digest, report_validation as rv  # noqa: E402
import check_legacy  # noqa: E402


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "src" / filename); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m


s11 = _load("run_llm_11_fix", "11_run_llm.py")
FULL = "SUMMARY: ok [E01].\nTIMELINE:\n[E01] 10:00:00 x\nFINDINGS: f [E01]\nLIMITATIONS: l"


class TestMin01(unittest.TestCase):
    def test_ek_maps_via_row_hash_to_unit_canonical(self):
        hash_of = {"g/other/00590": "h1", "g/unit/01001": "h1", "g/unit/00002": "h2", "g/other/9": "hX"}
        canon = {"h1": "g/unit/01001", "h2": "g/unit/00002"}        # kanonik unit; IRI pasangan global menunjuk berkas lain
        out = digest.ek_to_unit_canonical(["g/other/00590", "g/unit/01001", "g/unit/00002", "g/other/9", "tidak-ada"], hash_of, canon)
        self.assertEqual(out, ["g/unit/01001", "g/unit/00002"])      # urutan dipertahankan, tanpa duplikat, event di luar unit dilewati

    def test_ek_same_as_old_when_iri_already_canonical(self):
        hash_of = {"a": "h1", "b": "h2"}; canon = {"h1": "a", "h2": "b"}
        self.assertEqual(digest.ek_to_unit_canonical(["b", "a"], hash_of, canon), ["b", "a"])


class TestMin02(unittest.TestCase):
    def test_valid(self):
        v = rv.validate_report(FULL, "stop", {"E01"}); self.assertEqual(v["status"], "VALID"); self.assertTrue(v["valid_report"])

    def test_empty_whitespace_null(self):
        for t in ("", "  \n\t", None):
            v = rv.validate_report(t, "stop", {"E01"}); self.assertEqual(v["status"], "EMPTY_RESPONSE"); self.assertFalse(v["response_present"]); self.assertTrue(v["transport_ok"])

    def test_not_ordi_incomplete_truncated_bad_id(self):
        self.assertEqual(rv.validate_report("I cannot help with that.", "stop", {"E01"})["status"], "NOT_ORDI_REPORT")
        self.assertEqual(rv.validate_report("SUMMARY: a [E01]\nTIMELINE:\n[E01] x", "stop", {"E01"})["status"], "INCOMPLETE_STRUCTURE")
        self.assertEqual(rv.validate_report(FULL, "length", {"E01"})["status"], "TRUNCATED")
        v = rv.validate_report(FULL.replace("FINDINGS: f [E01]", "FINDINGS: f [E99]"), "stop", {"E01"})
        self.assertEqual(v["status"], "INVALID_EVIDENCE_ID"); self.assertEqual(v["invalid_ids"], ["E99"])

    def test_ids_unknown_when_evidence_missing_not_assumed_valid(self):
        v = rv.validate_report(FULL, "stop", None); self.assertIsNone(v["ids_valid"]); self.assertIsNone(v["invalid_ids"])

    def test_transport_failure_separate(self):
        self.assertEqual(rv.validate_report(None, None, None, transport_ok=False)["status"], "TRANSPORT_FAILED")

    def test_csv_row_matches_columns(self):
        row = rv.csv_row({"status": "GAGAL_RESPON_KOSONG", "model_tag": "m", "scenario": "scenario1", "unit_id": "u", "strategy": "P1", "text": None}, {"E01"})
        self.assertEqual(len(row), len(rv.CSV_COLUMNS)); self.assertEqual(row[rv.CSV_COLUMNS.index("transport_ok")], 1)
        self.assertEqual(row[rv.CSV_COLUMNS.index("status")], "EMPTY_RESPONSE")

    def _call(self, text, finish="stop"):
        r = {"raw": {}, "text": text, "model_served": "m", "provider": "p", "prompt_tokens": 1, "completion_tokens": 1, "finish_reason": finish, "parameters": {}, "attempts": 1}
        m = {"backend": "openrouter", "model": "x", "tag": "t"}
        with mock.patch.object(s11.lc, "call_openrouter", return_value=r): return s11.call(m, "p", {"openrouter_url": "u"}, "k")

    def test_stage11_empty_is_explicit_failure(self):
        for t in ("", "   \n", None):
            status, r, extra = self._call(t); self.assertEqual(status, rv.FAIL_EMPTY); self.assertIsNotNone(r)

    def test_stage11_nonempty_still_ok_even_if_truncated_or_unstructured(self):
        self.assertEqual(self._call("hello")[0], s11.OK); self.assertEqual(self._call("SUMMARY: x", "length")[0], s11.OK)


class TestMin04(unittest.TestCase):
    def _tree(self, d, E):
        (d / "acceptance").mkdir()
        (d / "acceptance" / "legacy_expected.json").write_text(json.dumps(E)); (d / "acceptance" / "legacy_baseline_before_changes.json").write_text(json.dumps({"pairs_csv_sha256": {s: "x" for s in check_legacy.SC}}))

    def _E(self):
        sc = {s: "h" for s in check_legacy.SC}
        return {"hashes": {"post_2_3": {"official_events_classified_sha256": sc, "nt_sha256": sc}}, "phase4b": {"rows": {}}, "phase6b": {"digest": {"digest_sha256": sc}}}

    def test_normal_structure_runs(self):
        old = check_legacy.ROOT
        try:
            with tempfile.TemporaryDirectory() as d:
                d = Path(d); self._tree(d, self._E()); buf = io.StringIO()
                with redirect_stdout(buf): rc = check_legacy.main(root=d)
                self.assertEqual(rc, 0); self.assertTrue((d / "results" / "legacy_check.json").exists()); self.assertIn("TIDAK_ADA", buf.getvalue())
        finally: check_legacy.ROOT = old

    def test_missing_key_gives_clear_message(self):
        E = self._E(); E["phase6b"] = {"digest_sha256": {}}          # struktur lama yang salah
        old = check_legacy.ROOT
        try:
            with tempfile.TemporaryDirectory() as d:
                d = Path(d); self._tree(d, E)
                with self.assertRaises(KeyError) as c, redirect_stdout(io.StringIO()): check_legacy.main(root=d)
                self.assertIn("phase6b.digest", str(c.exception)); self.assertIn("legacy_expected.json", str(c.exception))
        finally: check_legacy.ROOT = old

    def test_real_acceptance_files_have_expected_keys(self):
        E = json.loads((ROOT / "acceptance" / "legacy_expected.json").read_text(encoding="utf-8"))
        for s in check_legacy.SC: self.assertEqual(len(check_legacy.need(E, "phase6b", "digest", "digest_sha256", s)), 64)


class TestVariant(unittest.TestCase):
    def test_variant_separates_unit_dir_and_default_unchanged(self):
        base = config.unit_dir("task")
        try:
            config.set_variant("r1fix"); self.assertEqual(config.unit_dir("task").name, "unit_task__r1fix"); self.assertEqual(config.unit_dir("task").parent, base.parent)
            with self.assertRaises(ValueError): config.set_variant("../x")
        finally: config.set_variant(None)
        self.assertEqual(config.unit_dir("task"), base); self.assertEqual(base.name, "unit_task")


if __name__ == "__main__":
    unittest.main()
