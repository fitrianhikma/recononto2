"""STAGE 11 - Menjalankan LLM (dijalankan peneliti di VM). Klien dan parameter lama tidak diubah (llm.py).

    python3 src/11_run_llm.py --dry-run [--scenario N] [--model TAG]       # rencana + ukuran prompt + estimasi biaya; TANPA panggilan
    python3 src/11_run_llm.py --model qwen2.5-0.5b --scenario 2 --limit 1   # pilot lokal kecil
    python3 src/11_run_llm.py --backend ollama                              # semua model lokal, semua unit, P1-P3 (dapat dilanjutkan)
    python3 src/11_run_llm.py --backend openrouter --confirm-cloud          # cloud: WAJIB snapshot stage 10 yang masih baru + di bawah batas biaya
Opsi: --unit task|scenario, --strategy P1|P2|P3|all, --force (ulang run sah), --unit-id ID (terarah), --variant NAMA (folder hasil terpisah dari baseline).

Satu panggilan per (model, prompt berbeda). Bila beberapa unit punya prompt identik (mis. S3 exe/OneDrive: data sumber sama), panggilan
dilakukan sekali dan laporan yang SAMA dicatat untuk setiap tugas (field reused_from); evaluasi tetap terpisah per tugas.
Keluaran: results/unit_<unit>/11_llm/<model>/scenarioN/<unit_id>/{P#.json, P#.txt | P#.failed.json} + run_log.jsonl.
Status selain OK (GAGAL_KONTEKS, GAGAL_HTTP, ...) dicatat sebagai kegagalan, bukan hasil.

PERBAIKAN V3 (lihat docs/CHANGELOG_V3.md): hanya tampilan/orkestrasi di bawah ini yang berubah - timeout, retry, payload
permintaan (llm.py), dan kriteria status OK/kegagalan TIDAK diubah. Ditambahkan: nomor progres i/N per job, baris
[RUNNING] sebelum memanggil Ollama/OpenRouter, heartbeat [WAITING] berkala selama menunggu respons (thread terpisah,
TIDAK menyentuh call_ollama/timeout/retry - hanya mengamati dari luar), baris [SKIP] untuk kombinasi yang sudah sah
(sebelumnya dilewati tanpa pesan apa pun), dan penangkapan error tak terduga per-job (bukan LLMError, mis. bug/disk
penuh) agar satu job yang gagal tak terduga tidak menghentikan seluruh sisa rencana - tetap ditulis sebagai
`P#.failed.json` dengan skema field yang SAMA (model_tag/scenario/unit_id/strategy/status/note) supaya tetap
kompatibel dibaca Stage 12 (lihat collect() di 12_evaluate.py). Resume/skip dan kriteria status OK/gagal TIDAK diubah
sama sekali - hanya pesannya yang sekarang terlihat.
"""
import argparse, json, os, shutil, sys, threading, time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config, llm as lc, report_validation as rv

OK = lc.OK
HEARTBEAT_INTERVAL_S = 20        # PERBAIKAN V3: jeda antar baris [WAITING] selama menunggu satu respons LLM
UNEXPECTED_FAIL_STATUS = "GAGAL_TAK_TERDUGA"   # PERBAIKAN V3: error di luar LLMError (bug/IO) - dicatat, bukan menghentikan run


def now(): return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ident(m, it) -> str: return f"{m['tag']} | {it['scenario']} | {it['unit_id']} | {it['strategy']}"


def _heartbeat(stop: threading.Event, label: str, t0: float, log) -> None:
    """PERBAIKAN V3: thread terpisah, hanya mencetak '[WAITING] ... elapsed=Ns' berkala selagi menunggu satu
    panggilan LLM yang sedang berjalan di thread utama. Tidak membaca/menulis apa pun selain mencetak - tidak
    menyentuh logika pemanggilan, retry, atau penulisan hasil. Berhenti aman begitu `stop` di-set oleh pemanggil
    (lihat execute(): selalu di dalam blok `finally`, sehingga berhenti baik saat sukses, gagal, maupun Ctrl-C)."""
    while not stop.wait(HEARTBEAT_INTERVAL_S):
        log(f"[WAITING] {label} | elapsed={int(time.time() - t0)}s")


def plan(st, unit, scenarios, strategies, model_tags=None, backend=None, limit=None, unit_ids=None) -> list:
    """-> daftar (model, scenario, unit_id, strategy, prompt_path, prompt_sha) dari prompts_index; urutan: model, skenario, unit, strategi."""
    models = [m for m in st["models"] if (not model_tags or m["tag"] in model_tags) and (not backend or m["backend"] == backend)]
    items = []
    for m in models:
        for s in scenarios:
            ip = config.unit_dir(unit) / "09_prompts" / s / "prompts_index.json"
            if not ip.exists(): raise FileNotFoundError(f"{ip} belum ada: jalankan stage 09 untuk {s} (unit={unit})")
            idx = json.loads(ip.read_text(encoding="utf-8"))
            if idx["status"] != "OK": raise ValueError(f"{ip}: status {idx['status']} (cek kebocoran contoh P3)")
            uids = [u for u in idx["units"] if not unit_ids or u in unit_ids]
            uids = uids[:limit] if limit else uids
            for uid in uids:
                for p in strategies:
                    items.append({"model": m, "scenario": s, "unit_id": uid, "strategy": p, "prompt_sha256": idx["units"][uid][p],
                                  "prompt_path": config.unit_dir(unit) / "09_prompts" / s / uid / f"{p}.txt"})
    return items


def _evidence_ids(unit, it):
    """ID evidence digest unit (untuk validasi v2); None bila berkas tidak terbaca (validasi ID dilewati, bukan dianggap valid)."""
    p = config.unit_dir(unit) / "08_digest" / it["scenario"] / it["unit_id"] / "digest_evidence.json"
    try: return {e["id"] for e in json.loads(p.read_text(encoding="utf-8"))["evidence"]}
    except (OSError, ValueError, KeyError): return None


def run_paths(unit, tag, scenario, uid, strategy) -> dict:
    d = config.unit_dir(unit) / "11_llm" / tag / scenario / uid
    return {"dir": d, "json": d / f"{strategy}.json", "txt": d / f"{strategy}.txt", "failed": d / f"{strategy}.failed.json"}


def valid_run(p: Path):
    try:
        d = json.loads(p.read_text(encoding="utf-8")); return d if d.get("status") == OK else None
    except (OSError, ValueError): return None


def estimate_cost(items, snapshot) -> dict:
    """Estimasi biaya cloud: token masuk = karakter/4 x token_factor_estimate; token keluar = MAX_TOKENS (batas atas)."""
    tot = 0.0; per = {}; seen = set()
    for it in items:
        m = it["model"]
        if m["backend"] != "openrouter" or (m["tag"], it["prompt_sha256"]) in seen: continue
        seen.add((m["tag"], it["prompt_sha256"])); s = snapshot["models"].get(m["model"])
        if not s or not s.get("available"): raise ValueError(f"{m['model']} tidak tersedia di snapshot OpenRouter")
        tin = len(it["prompt_path"].read_text(encoding="utf-8")) / 4 * m.get("token_factor_estimate", 1.6); tout = lc.MAX_TOKENS
        c = tin * s["usd_per_token_input"] + tout * s["usd_per_token_output"]; tot += c
        v = per.setdefault(m["tag"], {"calls": 0, "est_input_tokens": 0, "max_output_tokens": 0, "est_usd": 0.0})
        v["calls"] += 1; v["est_input_tokens"] += int(tin); v["max_output_tokens"] += tout; v["est_usd"] += c
    return {"total_est_usd_upper_bound": round(tot, 6), "per_model": {k: dict(v, est_usd=round(v["est_usd"], 6)) for k, v in per.items()}}


def cloud_gate(st, items, confirm: bool) -> dict:
    cloud = [it for it in items if it["model"]["backend"] == "openrouter"]
    if not cloud: return {"needed": False}
    if not confirm: raise PermissionError("model OpenRouter diminta tanpa --confirm-cloud. Jalankan --dry-run dulu, periksa estimasi biaya, lalu ulangi dengan --confirm-cloud.")
    if not os.environ.get(st["openrouter_api_key_env"]): raise PermissionError(f"{st['openrouter_api_key_env']} tidak diset")
    sp = config.RESULTS / "10_models" / "openrouter_snapshot.json"
    if not sp.exists(): raise PermissionError(f"{sp} belum ada: jalankan stage 10 --cloud")
    snap = json.loads(sp.read_text(encoding="utf-8")); age_d = (datetime.now(timezone.utc) - datetime.strptime(snap["checked_utc"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)).total_seconds() / 86400
    lim = st["cloud_guard"]
    if age_d > lim["max_snapshot_age_days"]: raise PermissionError(f"snapshot OpenRouter berumur {age_d:.1f} hari (> {lim['max_snapshot_age_days']}): jalankan ulang stage 10 --cloud")
    est = estimate_cost(cloud, snap)
    if est["total_est_usd_upper_bound"] > lim["max_estimated_cost_usd"]: raise PermissionError(f"estimasi biaya {est['total_est_usd_upper_bound']} USD > batas {lim['max_estimated_cost_usd']} (config/pipeline.json cloud_guard)")
    return {"needed": True, "snapshot_checked_utc": snap["checked_utc"], "snapshot_age_days": round(age_d, 2), "estimate": est}


def call(m, prompt, st, key):
    """Satu panggilan, perilaku sama dengan one_run lama (premeasure opsional, cek GAGAL_KONTEKS Ollama). -> (status, r|None, extra)."""
    pre = eff = None
    try:
        if m["backend"] == "ollama":
            eff = lc.NUM_PREDICT
            if m.get("premeasure"):
                pre = lc.premeasure(m, prompt, st["ollama_url"]); eff = min(lc.NUM_PREDICT, m["num_ctx"] - pre - lc.CTX_MARGIN)
                if eff < lc.MIN_OUTPUT_TOKENS: raise lc.LLMError(lc.FAIL_CTX, f"prompt_eval_count {pre}: num_predict efektif {eff} < {lc.MIN_OUTPUT_TOKENS}; tidak ada jawaban yang dihasilkan")
            r = lc.call_ollama(m, prompt, st["ollama_url"], num_predict=eff)
        else:
            r = lc.call_openrouter(m, prompt, st["openrouter_url"], key)
        status, note = OK, None
        if m["backend"] == "ollama" and r["prompt_tokens"] + r["parameters"]["num_predict"] > m["num_ctx"]:
            status = lc.FAIL_CTX; note = f"prompt_eval_count {r['prompt_tokens']} + num_predict {r['parameters']['num_predict']} > num_ctx {m['num_ctx']}: prompt kemungkinan dipotong diam-diam oleh Ollama"
        if status == OK and rv.is_blank(r["text"]):                  # MIN-02: HTTP/API berhasil tetapi tidak ada teks laporan (None/''/whitespace) = kegagalan eksplisit, bukan OK
            status = rv.FAIL_EMPTY; note = f"respons model kosong/whitespace/null (finish_reason={r['finish_reason']}); bukan laporan"
        return status, r, {"note": note, "num_predict_effective": eff, "prompt_eval_count_premeasured": pre}
    except lc.LLMError as e:
        return e.status, None, {"note": e.message, "http_status": e.http_status, "attempts": e.attempts, "num_predict_effective": eff, "prompt_eval_count_premeasured": pre}


def execute(st, unit, items, force=False, log=print) -> dict:
    """Keputusan resume/skip dan kriteria status OK/gagal TIDAK diubah dari V2 (lihat `cur and not force and cur.get(...)`
    di bawah - baris yang sama persis). PERBAIKAN V3 hanya menambah: nomor progres i/N, baris [RUNNING]/[SKIP]/[WAITING]
    yang terlihat, dan penangkapan error tak terduga per-job (try/except Exception di sekitar satu job - BUKAN di
    sekitar seluruh loop, jadi job lain tetap lanjut) tanpa mengubah format `.failed.json` (lihat UNEXPECTED_FAIL_STATUS)."""
    key = os.environ.get(st["openrouter_api_key_env"], ""); counts = {}; done = {}          # (tag, prompt_sha) -> path run sah
    total = len(items)
    for i, it in enumerate(items, 1):
        m = it["model"]; P = run_paths(unit, m["tag"], it["scenario"], it["unit_id"], it["strategy"]); k = (m["tag"], it["prompt_sha256"])
        ident = _ident(m, it); prog = f"[{i}/{total}]"
        cur = valid_run(P["json"])
        if cur and not force and cur.get("prompt_sha256") == it["prompt_sha256"]:                 # TIDAK diubah dari V2: kriteria skip yang sama persis
            done.setdefault(k, P["json"]); counts["SKIP_SUDAH_SAH"] = counts.get("SKIP_SUDAH_SAH", 0) + 1
            log(f"{prog} SKIP — sudah berhasil dijalankan sebelumnya | {ident}"); continue
        try:
            prompt = it["prompt_path"].read_text(encoding="utf-8")
            if lc.sha(prompt) != it["prompt_sha256"]: raise ValueError(f"{it['prompt_path']} tidak cocok dengan prompts_index.json (jalankan ulang stage 09)")
            base = {"scenario": it["scenario"], "unit": unit, "unit_id": it["unit_id"], "strategy": it["strategy"], "model_tag": m["tag"], "backend": m["backend"],
                    "model_requested": m["model"], "prompt_sha256": it["prompt_sha256"]}
            src = done.get(k)
            if src and src != P["json"]:                                                    # prompt identik sudah dijalankan: pakai ulang, tanpa panggilan
                rec = dict(json.loads(Path(src).read_text(encoding="utf-8")), **base, reused_from=str(src), llm_call=False)
                P["dir"].mkdir(parents=True, exist_ok=True); lc.write_atomic(P["json"], json.dumps(rec, indent=1, ensure_ascii=False) + "\n"); shutil.copyfile(Path(src).with_suffix(".txt"), P["txt"])
                counts["REUSED"] = counts.get("REUSED", 0) + 1; log(f"{prog} REUSED dari {src} | {ident}"); continue
            log(f"{prog} RUNNING | {ident}")
            t0 = time.time(); started = now(); stop = threading.Event()
            hb = threading.Thread(target=_heartbeat, args=(stop, f"{prog} {ident}", t0, log), daemon=True); hb.start()
            try: status, r, extra = call(m, prompt, st, key)       # TIDAK diubah: timeout/retry/payload sama persis (llm.py)
            finally: stop.set(); hb.join()      # PERBAIKAN V3: heartbeat SELALU berhenti - sukses, gagal, atau Ctrl-C (BaseException tetap memicu finally)
            rec = dict(base, status=status, llm_call=True, started_utc=started, finished_utc=now(), duration_s=round(time.time() - t0, 2), **{k_: v for k_, v in extra.items() if v is not None})
            if m["backend"] == "ollama": rec.update(ollama_version=lc.ollama_version(st["ollama_url"]), num_ctx=m["num_ctx"])
            else: rec["provider_service"] = "OpenRouter"
            if r: rec.update(model_served=r["model_served"], provider=r["provider"], parameters=r["parameters"], prompt_tokens=r["prompt_tokens"], completion_tokens=r["completion_tokens"],
                             finish_reason=r["finish_reason"], attempts=r["attempts"], response_raw=r["raw"], text=r["text"])
            if status == OK:                                                                 # kriteria OK lama + respons tidak kosong (MIN-02); validasi v2 dicatat terpisah
                rec["validation"] = rv.validate_report(r["text"], r["finish_reason"], _evidence_ids(unit, it))
                lc.write_atomic(P["txt"], r["text"].rstrip("\n") + "\n"); lc.write_atomic(P["json"], json.dumps(rec, indent=1, ensure_ascii=False) + "\n")
                if P["failed"].exists(): P["failed"].unlink()
                done[k] = P["json"]
            else: lc.write_atomic(P["failed"], json.dumps(rec, indent=1, ensure_ascii=False) + "\n")
            counts[status] = counts.get(status, 0) + 1
            line = {k_: rec.get(k_) for k_ in ("finished_utc", "model_tag", "scenario", "unit_id", "strategy", "status", "duration_s", "prompt_tokens", "completion_tokens", "finish_reason", "provider", "note")}
            lp = config.unit_dir(unit) / "11_llm" / "run_log.jsonl"; lp.parent.mkdir(parents=True, exist_ok=True)
            with open(lp, "a", encoding="utf-8") as f: f.write(json.dumps(line, ensure_ascii=False) + "\n")
            log(f"{prog} {status} | {ident} | {rec['duration_s']}s in={rec.get('prompt_tokens')} out={rec.get('completion_tokens')} finish={rec.get('finish_reason')}" + (f" - {extra['note']}" if extra.get("note") else ""))
        except Exception as e:                                        # PERBAIKAN V3: error TAK TERDUGA (bukan LLMError, mis. IO/bug) - job lain tetap lanjut
            note = f"{type(e).__name__}: {e}"
            rec = {"scenario": it["scenario"], "unit": unit, "unit_id": it["unit_id"], "strategy": it["strategy"], "model_tag": m["tag"], "backend": m["backend"],
                   "model_requested": m["model"], "prompt_sha256": it["prompt_sha256"], "status": UNEXPECTED_FAIL_STATUS, "llm_call": False, "note": note, "finished_utc": now()}
            try: lc.write_atomic(P["failed"], json.dumps(rec, indent=1, ensure_ascii=False) + "\n")      # format sama dengan .failed.json biasa - tetap kompatibel Stage 12
            except Exception: pass
            counts[UNEXPECTED_FAIL_STATUS] = counts.get(UNEXPECTED_FAIL_STATUS, 0) + 1
            log(f"{prog} {UNEXPECTED_FAIL_STATUS} | {ident} | {note}")
    return counts


def main(argv=None):
    try: sys.stdout.reconfigure(line_buffering=True)        # PERBAIKAN V3: baris progres/[WAITING] langsung tampil (per baris), tidak menunggu buffer penuh - terutama penting saat dijalankan lewat run.py (pipe, bukan TTY)
    except (AttributeError, ValueError): pass
    st = config.load_settings()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--unit", choices=["task", "scenario"], default=st["unit_default"]); ap.add_argument("--scenario", choices=["1", "2", "3", "all"], default="all")
    ap.add_argument("--strategy", choices=["P1", "P2", "P3", "all"], default="all"); ap.add_argument("--model", action="append", help="tag model (boleh berulang)")
    ap.add_argument("--backend", choices=["ollama", "openrouter"]); ap.add_argument("--limit", type=int, help="hanya N unit pertama per skenario (pilot)")
    ap.add_argument("--unit-id", action="append", help="hanya unit ini (boleh berulang)"); ap.add_argument("--variant", help="baca prompt/tulis laporan di results/unit_<unit>__<variant> (baseline tidak tersentuh)")
    ap.add_argument("--dry-run", action="store_true"); ap.add_argument("--confirm-cloud", action="store_true"); ap.add_argument("--force", action="store_true")
    a = ap.parse_args(argv); config.set_variant(a.variant)
    tags = {m["tag"] for m in st["models"]}
    if a.model and set(a.model) - tags: print("tag model tidak dikenal; yang valid: " + ", ".join(sorted(tags))); return 2
    strategies = list(st["strategies"]) if a.strategy == "all" else [a.strategy]
    items = plan(st, a.unit, config.scenario_list(a.scenario), strategies, a.model, a.backend, a.limit, set(a.unit_id) if a.unit_id else None)
    distinct = len({(it["model"]["tag"], it["prompt_sha256"]) for it in items})
    print(f"rencana: {len(items)} laporan (model x unit x strategi), {distinct} panggilan LLM berbeda (prompt identik dipakai ulang); unit={a.unit}")
    if a.dry_run:
        sp = config.RESULTS / "10_models" / "openrouter_snapshot.json"; cloud = [it for it in items if it["model"]["backend"] == "openrouter"]
        if cloud and sp.exists(): print("estimasi biaya cloud (batas atas):", json.dumps(estimate_cost(cloud, json.loads(sp.read_text(encoding="utf-8"))), ensure_ascii=False))
        elif cloud: print("estimasi biaya cloud: jalankan stage 10 --cloud dulu (snapshot harga belum ada)")
        for it in items[:400]:
            n = len(it["prompt_path"].read_text(encoding="utf-8")); m = it["model"]; est = int(n / 4 * m.get("token_factor_estimate", 1.55))
            warn = (" PERINGATAN_KONTEKS" if m["backend"] == "ollama" and est + lc.NUM_PREDICT > m["num_ctx"] else "")
            print(f"  {m['tag']:14s} {it['scenario']} {it['unit_id']:36s} {it['strategy']} chars={n} ~tok={est}{warn} sah={'ya' if valid_run(run_paths(a.unit, m['tag'], it['scenario'], it['unit_id'], it['strategy'])['json']) else 'belum'}")
        return 0
    try: gate = cloud_gate(st, items, a.confirm_cloud)
    except PermissionError as e: print(f"DITOLAK: {e}"); return 3
    if gate["needed"]:
        print(f"cloud: snapshot {gate['snapshot_checked_utc']} (umur {gate['snapshot_age_days']} hari); estimasi batas atas {gate['estimate']['total_est_usd_upper_bound']} USD")
        gp = config.unit_dir(a.unit) / "11_llm" / f"cloud_gate_{now().replace(':', '')}.json"; gp.parent.mkdir(parents=True, exist_ok=True); gp.write_text(json.dumps(gate, indent=1), encoding="utf-8")
    try:
        counts = execute(st, a.unit, items, a.force, log=print)
    except KeyboardInterrupt:                    # PERBAIKAN V3: berhenti rapi, bukan traceback mentah; progres yang sudah tersimpan tetap valid untuk resume
        print("\nDIHENTIKAN oleh pengguna (Ctrl-C). Progres yang sudah tersimpan tetap sah - jalankan ulang perintah yang sama untuk melanjutkan (kombinasi yang sudah selesai otomatis di-SKIP).")
        return 130
    print("ringkasan:", counts); return 1 if any(k not in (OK, "SKIP_SUDAH_SAH", "REUSED") for k in counts) else 0


if __name__ == "__main__":
    sys.exit(main())
