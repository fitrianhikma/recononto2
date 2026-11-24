"""Konfigurasi path dan pengaturan V1 (satu tempat).

Nama konstanta lama dipertahankan agar modul lama (classifier, RDF, korelasi, digest) tetap berjalan tanpa perubahan logika.
Yang berubah hanya LOKASI keluaran: semua hasil ditulis di results/<NN_tahap>/, dataset di data/ hanya dibaca.
Pengaturan operasional (model, unit, pola grep S3, penjaga biaya) dibaca dari config/pipeline.json.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCENARIOS = ("scenario1", "scenario2", "scenario3")
RAW_FILENAME = "timeline.csv"          # tidak dipakai di V1 (timeline penuh); dipertahankan demi kompatibilitas modul lama
EXPECTED_COLUMNS = ["datetime", "timestamp_desc", "source", "source_long",
                    "message", "parser", "display_name", "tag"]

RULES_V1 = ROOT / "rules" / "event_rules.csv"
RULES_V2 = ROOT / "rules" / "event_rules_v2.csv"      # dipakai pipeline (v1 + 8 rule, keputusan lama D5)
RULES_PATH = RULES_V1                                  # default lama Classifier; stage 02 selalu memberi --rules v2
DIGEST_WEIGHTS = ROOT / "rules" / "digest_weights.csv"
EVENTS_DIRNAME = "events"
OFFICIAL_PROCESSED = "official_events_classified.csv"
PROCESSED_FILENAME = "events_classified.csv"
PROCESSED_REPORT = "preprocess_report.json"
DATA_DIR = ROOT / "data"
TASKS_DIR = DATA_DIR / "tasks"
QUERIES_DIR = ROOT / "queries"
PROMPTS_DIR = ROOT / "prompts" / "templates"
RESULTS = ROOT / "results"
RDF_DIR = RESULTS / "03_rdf"
RESULTS_DIR = RESULTS / "05_sparql"                    # nama lama: keluaran SPARQL
SETTINGS_PATH = ROOT / "config" / "pipeline.json"


def _root(root=None) -> Path:
    return Path(root) if root else ROOT


def check_scenario(scenario: str):
    if scenario not in SCENARIOS:
        raise ValueError(f"scenario tidak dikenal: {scenario!r}")


def scenario_list(arg: str) -> list:
    """'1' -> ['scenario1']; 'all' -> ketiganya."""
    return list(SCENARIOS) if arg == "all" else [f"scenario{arg}"]


def scenario_paths(scenario: str, root=None) -> dict:
    check_scenario(scenario); r = _root(root)
    return {"events_dir": r / "data" / scenario / EVENTS_DIRNAME,
            "raw": r / "data" / scenario / "raw" / RAW_FILENAME,
            "processed_dir": r / "results" / "02_preprocess" / scenario,
            "report_dir": r / "results" / "02_preprocess"}


def preprocess_report_path(scenario: str, root=None) -> Path:
    check_scenario(scenario)
    return _root(root) / "results" / "02_preprocess" / f"preprocess_report_{scenario}.json"


def rdf_paths(scenario: str, root=None) -> dict:
    check_scenario(scenario); r = _root(root) / "results" / "03_rdf"
    return {"nt": r / f"{scenario}.nt", "sample_ttl": r / f"sample_{scenario}.ttl",
            "schema": r / "ord2i_impl_schema.nt", "report_dir": r,
            "validate_dir": _root(root) / "results" / "04_validate"}


def correlation_dir(scenario: str, root=None) -> Path:
    check_scenario(scenario)
    return _root(root) / "results" / "07_correlation" / scenario


VARIANT = None     # None = hasil baseline (results/unit_<unit>). Diset --variant NAMA pada stage 08/09/11/12 -> results/unit_<unit>__NAMA (terpisah dari baseline)


def set_variant(name):
    """Pisahkan keluaran/masukan stage 08-12 ke folder varian agar baseline tidak tertimpa (mis. verifikasi perbaikan MIN-01 untuk satu unit)."""
    global VARIANT
    if name and not name.replace("_", "").replace("-", "").isalnum(): raise ValueError(f"nama varian tidak valid: {name!r}")
    VARIANT = name or None


def unit_dir(unit: str, root=None) -> Path:
    if unit not in ("task", "scenario"): raise ValueError(f"unit tidak dikenal: {unit!r}")
    return _root(root) / "results" / (f"unit_{unit}" + (f"__{VARIANT}" if VARIANT else ""))


def load_settings(path=None) -> dict:
    return json.loads(Path(path or SETTINGS_PATH).read_text(encoding="utf-8"))
