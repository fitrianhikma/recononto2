"""Parameter runner LLM (Phase 7B, nilai TIDAK diubah). Daftar model: config/pipeline.json. Kunci API TIDAK pernah di sini: hanya env OPENROUTER_API_KEY.
Seluruh nilai adalah operasionalisasi penelitian (rancangan: docs/PHASE6A_DESIGN.md §4).

Digabung dari llm_config.py (parameter) + llm_client.py (klien) saat refactoring folder (lihat docs/REFERENCE.md (bagian 4)).
Tidak ada isi fungsi atau nilai parameter yang diubah; dipanggil sebagai satu modul `llm` oleh 10_models_check.py dan 11_run_llm.py
(dulu dua alias terpisah `lc`/`lcfg` untuk dua modul; perubahan hanya baris impor dan alias, bukan logika).

Klien LLM (kode lama 07_run_llm.py: http_json, call_ollama, premeasure, call_openrouter TIDAK diubah; parameter di atas).
Driver lama (run_paths, one_run, do_check, do_dry_run, main) diganti 10_models_check.py dan 11_run_llm.py.

PHASE 7B - Runner LLM (Ollama lokal + OpenRouter). stdlib saja (urllib). LLM hanya untuk menulis laporan dari prompt.

    python3 src/11_run_llm.py --dry-run [--scenario N]      # cetak ukuran prompt dan nama keluaran; TANPA memanggil model
Keluaran sah: results/llm/scenarioN/<tag>/P#.json + P#.txt. Kegagalan: P#.failed.json (BUKAN hasil). Kunci API hanya dari env OPENROUTER_API_KEY; tidak pernah ditulis/dicetak.
Ollama memotong prompt yang terlalu panjang secara diam-diam: run ditandai GAGAL_KONTEKS bila prompt_eval_count + num_predict > num_ctx.
"""
import hashlib, json, os, sys, time, urllib.error, urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# --- parameter (dulu llm_config.py), nilai tidak diubah ---
OLLAMA_BASE = "http://localhost:11434"                       # endpoint chat: <base>/api/chat (stream:false)
OPENROUTER_BASE = "https://openrouter.ai/api/v1"             # endpoint chat: <base>/chat/completions
API_KEY_ENV = "OPENROUTER_API_KEY"

TEMPERATURE = 0
SEED = 42
NUM_PREDICT = 900            # token keluaran maksimum, lokal (Ollama); patch v2 (v1: 500 -> 19/24 laporan terpotong)
MAX_TOKENS = 900             # token keluaran maksimum, cloud (OpenRouter)
MIN_OUTPUT_TOKENS = 350      # model dengan pra-ukur: bila num_predict efektif < 350 -> GAGAL_KONTEKS tanpa menghasilkan jawaban
CTX_MARGIN = 32              # sisa konteks yang dijaga saat menghitung num_predict efektif
PREMEASURE_KEEP_ALIVE = 0    # panggilan pra-ukur (num_predict=1) memuat lalu membuang model segera
TOKEN_FACTOR = {"tinyllama-1.1b": 1.8, "qwen2.5-0.5b": 1.55, "qwen2.5-1.5b": 1.55}   # token nyata / (karakter/4) terukur dari run v1; hanya untuk peringatan --dry-run
TIMEOUT_S = {"ollama": 900, "openrouter": 180}              # timeout eksplisit per panggilan (detik); CPU-only lokal bisa lambat
RETRIES = 3                  # percobaan ulang maksimum untuk 429/5xx dan kegagalan jaringan sementara
BACKOFF_BASE_S = 2.0         # jeda eksponensial: 2, 4, 8 detik
CHECK_PROMPT = "Reply with the single word: ok"
CHECK_TOKENS = 8

# V1: daftar model (tag, backend, ID, num_ctx) dipindah ke config/pipeline.json. TinyLlama tidak dipakai lagi; logika premeasure tetap
# tersedia untuk model mana pun yang diberi "premeasure": true di pipeline.json. Nilai parameter di atas TIDAK diubah dari run lama.

lc = sys.modules[__name__]  # kompatibilitas: fungsi di bawah memakai 'lc.RETRIES' dst. (dulu modul llm_config terpisah)

OK, FAIL_CTX, FAIL_HTTP, FAIL_NET, FAIL_FMT = "OK", "GAGAL_KONTEKS", "GAGAL_HTTP", "GAGAL_JARINGAN", "GAGAL_FORMAT"


class LLMError(Exception):
    def __init__(self, status, message, http_status=None, attempts=1): super().__init__(message); self.status, self.message, self.http_status, self.attempts = status, message, http_status, attempts


def http_json(url, payload=None, headers=None, timeout=60, retries=lc.RETRIES, sleep=time.sleep, method=None):
    """-> (json, attempts). Retry maksimal `retries` kali untuk 429/5xx dan galat jaringan sementara dengan jeda eksponensial; 4xx lain gagal langsung."""
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    hdr = {"Content-Type": "application/json"}; hdr.update(headers or {})
    last = None
    for attempt in range(1, retries + 2):
        try:
            req = urllib.request.Request(url, data=data, headers=hdr, method=method or ("POST" if data is not None else "GET"))
            with urllib.request.urlopen(req, timeout=timeout) as r: body = r.read().decode("utf-8")
            try: return json.loads(body), attempt
            except ValueError: raise LLMError(FAIL_FMT, f"respons bukan JSON: {body[:200]!r}", attempts=attempt)
        except urllib.error.HTTPError as e:
            msg = e.read().decode("utf-8", "replace")[:300]; last = LLMError(FAIL_HTTP, f"HTTP {e.code}: {msg}", http_status=e.code, attempts=attempt)
            if not (e.code == 429 or 500 <= e.code < 600): raise last
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            last = LLMError(FAIL_NET, f"galat jaringan/timeout: {e}", attempts=attempt)
        if attempt <= retries: sleep(lc.BACKOFF_BASE_S * (2 ** (attempt - 1)))
    last.attempts = retries + 1; raise last


def ollama_version(base, sleep=time.sleep):
    try: return http_json(base.rstrip("/") + "/api/version", timeout=10, retries=0, sleep=sleep)[0].get("version")
    except LLMError: return None


def call_ollama(cfg, prompt, base, num_predict=lc.NUM_PREDICT, sleep=time.sleep, timeout=None, keep_alive=None):
    opts = {"temperature": lc.TEMPERATURE, "seed": lc.SEED, "num_predict": num_predict, "num_ctx": cfg["num_ctx"]}
    payload = {"model": cfg["model"], "messages": [{"role": "user", "content": prompt}], "stream": False, "options": opts}
    if keep_alive is not None: payload["keep_alive"] = keep_alive
    raw, attempts = http_json(base.rstrip("/") + "/api/chat", payload, timeout=timeout or lc.TIMEOUT_S["ollama"], sleep=sleep)
    try:
        text = raw["message"]["content"]; pec = int(raw.get("prompt_eval_count", 0)); ec = int(raw.get("eval_count", 0))
    except (KeyError, TypeError, ValueError): raise LLMError(FAIL_FMT, f"respons Ollama tidak dikenali: {str(raw)[:200]}")
    return {"raw": raw, "text": text, "model_served": raw.get("model", cfg["model"]), "provider": None, "prompt_tokens": pec, "completion_tokens": ec,
            "finish_reason": raw.get("done_reason"), "parameters": opts, "attempts": attempts}


def premeasure(cfg, prompt, base, sleep=time.sleep, timeout=None) -> int:
    """prompt_eval_count NYATA lewat panggilan num_predict=1, keep_alive=0 (tanpa menghasilkan jawaban)."""
    r = call_ollama(cfg, prompt, base, num_predict=1, sleep=sleep, timeout=timeout, keep_alive=lc.PREMEASURE_KEEP_ALIVE)
    return int(r["prompt_tokens"])


def call_openrouter(cfg, prompt, base, key, max_tokens=lc.MAX_TOKENS, sleep=time.sleep, timeout=None):
    params = {"temperature": lc.TEMPERATURE, "seed": lc.SEED, "max_tokens": max_tokens}
    payload = dict({"model": cfg["model"], "messages": [{"role": "user", "content": prompt}]}, **params)
    raw, attempts = http_json(base.rstrip("/") + "/chat/completions", payload, headers={"Authorization": f"Bearer {key}"}, timeout=timeout or lc.TIMEOUT_S["openrouter"], sleep=sleep)
    try:
        ch = raw["choices"][0]; text = ch["message"]["content"]; u = raw.get("usage", {})
    except (KeyError, IndexError, TypeError): raise LLMError(FAIL_FMT, f"respons OpenRouter tidak dikenali: {str(raw)[:200]}")
    return {"raw": raw, "text": text, "model_served": raw.get("model", cfg["model"]), "provider": raw.get("provider"), "prompt_tokens": u.get("prompt_tokens"),
            "completion_tokens": u.get("completion_tokens"), "finish_reason": ch.get("finish_reason"), "parameters": params, "attempts": attempts}


def write_atomic(path: Path, data: str):
    path.parent.mkdir(parents=True, exist_ok=True); tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(data, encoding="utf-8", newline="\n"); os.replace(tmp, path)
    finally:
        if tmp.exists(): tmp.unlink()


def sha(s: str) -> str: return hashlib.sha256(s.encode("utf-8")).hexdigest()
