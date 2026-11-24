"""STAGE 10 - Pemeriksaan model SEBELUM eksperimen (dijalankan peneliti; memerlukan jaringan).

    python3 src/10_models_check.py --local                 # Ollama: versi + model terpasang (tanpa generasi)
    python3 src/10_models_check.py --local --probe         # + satu generasi 8 token per model lokal (gratis, lokal)
    python3 src/10_models_check.py --cloud                 # OpenRouter: katalog publik GET /models -> snapshot harga/konteks/ketersediaan
                                                                #   + validasi kunci (GET /key) bila OPENROUTER_API_KEY diset. TANPA generasi.
Keluaran: results/10_models/{ollama_check.json, openrouter_snapshot.json}. Snapshot ini WAJIB untuk stage 11 cloud (penjaga biaya).
Kunci API hanya dari environment; tidak pernah ditulis atau dicetak.
"""
import argparse, json, os, sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config, llm as lc

OUT = config.RESULTS / "10_models"


def now(): return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def check_local(st, probe=False) -> dict:
    base = st["ollama_url"]; rep = {"checked_utc": now(), "ollama_url": base, "ollama_version": lc.ollama_version(base), "models": []}
    try: tags, _ = lc.http_json(base.rstrip("/") + "/api/tags", timeout=15, retries=0); installed = {m.get("name") for m in tags.get("models", [])}
    except lc.LLMError as e: installed = None; rep["tags_error"] = e.message
    for m in st["models"]:
        if m["backend"] != "ollama": continue
        row = {"tag": m["tag"], "model": m["model"], "installed": (m["model"] in installed) if installed is not None else None, "num_ctx": m["num_ctx"]}
        if row["installed"] is False: row["hint"] = f"ollama pull {m['model']}"
        if probe and row["installed"]:
            try:
                r = lc.call_ollama(m, lc.CHECK_PROMPT, base, num_predict=lc.CHECK_TOKENS, timeout=300); row.update(probe="OK", reply=r["text"][:40], model_served=r["model_served"])
            except lc.LLMError as e: row.update(probe=e.status, note=e.message)
        rep["models"].append(row)
    rep["ok"] = rep["ollama_version"] is not None and all(r["installed"] for r in rep["models"]) and all(r.get("probe", "OK") == "OK" for r in rep["models"])
    return rep


def check_cloud(st) -> dict:
    base = st["openrouter_url"].rstrip("/"); key = os.environ.get(st["openrouter_api_key_env"], "")
    rep = {"checked_utc": now(), "source": base + "/models", "api_key_present": bool(key), "models": {}}
    cat, _ = lc.http_json(base + "/models", timeout=60, retries=2)                      # katalog publik; tidak memakai kunci, tidak ada biaya
    byid = {m.get("id"): m for m in cat.get("data", [])}
    for m in st["models"]:
        if m["backend"] != "openrouter": continue
        x = byid.get(m["model"])
        if not x: rep["models"][m["model"]] = {"tag": m["tag"], "available": False}; continue
        pr = x.get("pricing", {})
        rep["models"][m["model"]] = {"tag": m["tag"], "available": True, "name": x.get("name"), "context_length": x.get("context_length"),
                                     "usd_per_token_input": float(pr.get("prompt", 0) or 0), "usd_per_token_output": float(pr.get("completion", 0) or 0),
                                     "usd_per_million_input": round(float(pr.get("prompt", 0) or 0) * 1e6, 6), "usd_per_million_output": round(float(pr.get("completion", 0) or 0) * 1e6, 6),
                                     "top_provider": x.get("top_provider"), "supported_parameters": x.get("supported_parameters")}
    if key:                                                                             # validasi kunci tanpa generasi
        for path in ("/key", "/auth/key"):
            try: info, _ = lc.http_json(base + path, headers={"Authorization": f"Bearer {key}"}, timeout=30, retries=0); rep["api_key_check"] = {"endpoint": path, "ok": True, "data": {k: v for k, v in info.get("data", {}).items() if k != "label"}}; break
            except lc.LLMError as e: rep["api_key_check"] = {"endpoint": path, "ok": False, "http_status": e.http_status, "note": e.message[:160]}
    rep["ok"] = all(v["available"] for v in rep["models"].values()) and (rep.get("api_key_check", {}).get("ok", False) if key else True)     # tanpa kunci: snapshot tetap sah untuk estimasi
    return rep


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--local", action="store_true"); ap.add_argument("--cloud", action="store_true"); ap.add_argument("--probe", action="store_true")
    a = ap.parse_args(); st = config.load_settings(); bad = False
    if not (a.local or a.cloud): ap.error("pilih --local dan/atau --cloud")
    OUT.mkdir(parents=True, exist_ok=True)
    if a.local:
        r = check_local(st, a.probe); lc.write_atomic(OUT / "ollama_check.json", json.dumps(r, indent=1, ensure_ascii=False) + "\n")
        print(f"Ollama {r['ollama_version'] or 'TIDAK TERJANGKAU di ' + st['ollama_url']}")
        for m in r["models"]: print(f"  {m['tag']:14s} terpasang={m['installed']}" + (f" probe={m.get('probe')}" if a.probe else "") + (f"  -> {m['hint']}" if m.get("hint") else ""))
        bad |= not r["ok"]
    if a.cloud:
        try: r = check_cloud(st)
        except lc.LLMError as e: print(f"OpenRouter tidak terjangkau: {e.message}"); sys.exit(1)
        lc.write_atomic(OUT / "openrouter_snapshot.json", json.dumps(r, indent=1, ensure_ascii=False) + "\n")
        for mid, v in r["models"].items():
            print(f"  {mid}: " + (f"tersedia, konteks={v['context_length']}, USD/1M in={v['usd_per_million_input']} out={v['usd_per_million_output']}" if v["available"] else "TIDAK TERSEDIA di katalog"))
        print(f"  kunci API: {'diset' if r['api_key_present'] else 'TIDAK diset (export ' + st['openrouter_api_key_env'] + '=...)'}" + (f", validasi={r['api_key_check']['ok']}" if "api_key_check" in r else ""))
        print(f"  snapshot: {OUT / 'openrouter_snapshot.json'} ({r['checked_utc']})"); bad |= not r["ok"]
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
