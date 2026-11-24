"""STAGE 00 - Pemeriksaan lingkungan (tanpa jaringan, tanpa memproses data).

    python3 src/00_check_env.py
Memeriksa: versi Python, paket wajib (rdflib==7.5.0) dan opsional (nltk, rouge-score), tata letak data/, berkas aturan, templat prompt.
Keluaran: results/00_env/env_report.json
"""
import hashlib, json, platform, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config, tasks as tk


def pkg(name):
    try:
        m = __import__(name); return getattr(m, "__version__", "terpasang")
    except ImportError: return None


def main():
    st = config.load_settings(); rep = {"python": sys.version.split()[0], "platform": platform.platform(), "checks": {}}
    C = rep["checks"]
    C["python>=3.10"] = sys.version_info >= (3, 10)
    rep["rdflib"] = pkg("rdflib"); C["rdflib==7.5.0 (wajib untuk stage 05-06)"] = rep["rdflib"] == "7.5.0"
    rep["optional"] = {"nltk": pkg("nltk"), "rouge_score": pkg("rouge_score")}
    for s in config.SCENARIOS:
        ev = config.scenario_paths(s)["events_dir"]; files = sorted(p.name for p in ev.glob("*.csv")) if ev.exists() else []
        rep[f"{s}_event_files"] = len(files); C[f"data/{s}/events/*.csv ada"] = bool(files)
        try:
            ts = tk.list_tasks(s); rep[f"{s}_tasks"] = len(ts)
            miss = [t["source_file"] for t in ts if t["source_file"] not in files]; C[f"{s}: setiap tugas punya berkas events"] = bool(ts) and not miss
            if miss: rep[f"{s}_missing_event_files"] = miss
            rep[f"{s}_event_files_without_gt"] = sorted(set(files) - {t["source_file"] for t in ts})
        except FileNotFoundError: C[f"{s}: ground truth ditemukan"] = False
    C["data/tasks/keyword-analysis/additional-keywords.json ada"] = (config.TASKS_DIR / "keyword-analysis" / "additional-keywords.json").exists()
    rep["rules_v2_sha256"] = hashlib.sha256(config.RULES_V2.read_bytes()).hexdigest()
    C["event_rules_v2.csv identik dengan run lama"] = rep["rules_v2_sha256"] == json.loads((config.ROOT / "acceptance" / "legacy_expected.json").read_text())["hashes"]["rules_v2_sha256"]
    for f in ("rules.txt", "P1.txt", "P2.txt", "P3.txt", "correlation_scale.txt", st["prompt"]["p3_example_file"]): C[f"templat {f} ada"] = (config.PROMPTS_DIR / f).exists()
    rep["models"] = [f"{m['tag']} ({m['backend']}: {m['model']})" for m in st["models"]]
    out = config.RESULTS / "00_env"; out.mkdir(parents=True, exist_ok=True); (out / "env_report.json").write_text(json.dumps(rep, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"Python {rep['python']} | rdflib {rep['rdflib']} | nltk {rep['optional']['nltk']} | rouge-score {rep['optional']['rouge_score']}")
    for k, v in C.items(): print(f"  {'OK   ' if v else 'GAGAL'} {k}")
    for s in config.SCENARIOS: print(f"  {s}: {rep.get(s + '_event_files')} berkas events, {rep.get(s + '_tasks')} tugas; tanpa GT: {rep.get(s + '_event_files_without_gt')}")
    print("  model:", "; ".join(rep["models"]))
    sys.exit(0 if all(C.values()) else 1)


if __name__ == "__main__":
    main()
