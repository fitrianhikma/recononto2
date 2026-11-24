"""Validasi laporan LLM, versi `validation_v2` (MIN-02). TAMBAHAN: tidak mengubah M0-M8, `pure`, atau status OK lama (report_metrics.py).

Empat tingkat yang dipisahkan (jangan dicampur; HTTP 200 dan `pure`=1 BUKAN bukti laporan valid):
  1. transport_ok      : panggilan API/jaringan berhasil (status run bukan GAGAL_HTTP/JARINGAN/FORMAT/KONTEKS/TAK_TERDUGA)
  2. response_present  : teks respons berupa string tidak kosong (bukan None, '' atau whitespace)
  3. structure_*       : keempat bagian ORDi (SUMMARY, TIMELINE, FINDINGS, LIMITATIONS) ada; urutan/duplikasi diperiksa terpisah
  4. ids_valid         : semua ID [Exx] yang dikutip ada di digest_evidence.json unit (None bila daftar evidence tidak tersedia)
Terpotong (`finish_reason == 'length'`) adalah penanda tersendiri. `status` = satu label utama menurut prioritas tetap; semua penanda tetap ada terpisah.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import report_metrics as rm

VALIDATION_VERSION = "validation_v2"
TRANSPORT_FAIL = ("GAGAL_HTTP", "GAGAL_JARINGAN", "GAGAL_FORMAT", "GAGAL_KONTEKS", "GAGAL_TAK_TERDUGA")
FAIL_EMPTY = "GAGAL_RESPON_KOSONG"          # status Stage 11 untuk run baru: transport berhasil tetapi respons None/kosong/whitespace
CSV_COLUMNS = ["validation_version", "model", "scenario", "unit_id", "strategy", "run_status", "transport_ok", "response_present", "truncated",
               "sections_found", "structure_complete", "order_unique", "citations_total", "invalid_ids", "ids_valid", "status", "valid_report"]


def is_blank(text) -> bool:
    return not isinstance(text, str) or not text.strip()


def validate_report(text, finish_reason=None, evidence_ids=None, transport_ok=True) -> dict:
    present = not is_blank(text); body = text if present else ""
    secs = rm.split_sections(body); found = [s for s in rm.SECTIONS if s in secs]
    cites = rm.cited_ids(body); invalid = sorted(set(cites) - set(evidence_ids)) if evidence_ids is not None else None
    v = {"validation_version": VALIDATION_VERSION, "transport_ok": bool(transport_ok), "response_present": present, "truncated": finish_reason == "length",
         "sections_found": found, "structure_complete": len(found) == len(rm.SECTIONS), "order_unique": rm.heading_sequence(body) == list(rm.SECTIONS),
         "citations_total": len(cites), "invalid_ids": invalid, "ids_valid": None if invalid is None else not invalid}
    if not v["transport_ok"]: status = "TRANSPORT_FAILED"
    elif not present: status = "EMPTY_RESPONSE"
    elif not found: status = "NOT_ORDI_REPORT"
    elif v["truncated"]: status = "TRUNCATED"
    elif not v["structure_complete"]: status = "INCOMPLETE_STRUCTURE"
    elif v["ids_valid"] is False: status = "INVALID_EVIDENCE_ID"
    else: status = "VALID"
    v["status"] = status; v["valid_report"] = status == "VALID"
    return v


def csv_row(run: dict, evidence_ids=None) -> list:
    """Satu baris report_validity.csv dari JSON run (OK maupun .failed.json). Urutan = CSV_COLUMNS."""
    st = run.get("status"); v = validate_report(run.get("text"), run.get("finish_reason"), evidence_ids, transport_ok=st not in TRANSPORT_FAIL)
    return [VALIDATION_VERSION, run.get("model_tag"), run.get("scenario"), run.get("unit_id"), run.get("strategy"), st, int(v["transport_ok"]), int(v["response_present"]),
            int(v["truncated"]), len(v["sections_found"]), int(v["structure_complete"]), int(v["order_unique"]), v["citations_total"],
            "" if v["invalid_ids"] is None else "|".join(v["invalid_ids"]), "" if v["ids_valid"] is None else int(v["ids_valid"]), v["status"], int(v["valid_report"])]
