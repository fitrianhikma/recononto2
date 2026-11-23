# Changelog V3

V3 adalah iterasi audit-lalu-perbaiki di atas V2 (`docs/CHANGELOG_V2.md`), dengan ruang lingkup yang
sangat sempit dan disetujui sebelum coding dimulai. **Satu perubahan fungsional saja**: visibilitas dan
kestabilan orkestrasi Stage 11 (`src/11_run_llm.py`). Tidak ada perubahan metodologi, format data, atau
logika evaluasi di mana pun.

## Mengapa

Pengguna melaporkan Stage 11 **belum pernah berhasil selesai** pada run nyata: proses terlihat diam
("frozen") selama menunggu respons Ollama (durasi nyata yang teramati: 51–337+ detik per panggilan),
tidak ada tanda proses mana yang sedang berjalan, dan ketika proses berhenti di tengah jalan (lihat
`586e1d15-unit_task.tar.xz` - 52 entri OK di `run_log.jsonl`, berhenti bersih tanpa baris error),
tidak ada cara untuk memastikan dari output run itu sendiri bahwa run selanjutnya akan melanjutkan
dengan aman, bukan mengulang dari awal.

## Audit: apa yang TIDAK menjadi penyebab (dan karenanya TIDAK diubah)

- `llm.py` - timeout (`TIMEOUT_S`), retry (`RETRIES=3`), backoff (`BACKOFF_BASE_S=2.0`), payload
  permintaan (`"stream": False`, parameter model) - semua sudah ada dan sudah memadai. **Tidak disentuh.**
- Logika resume/skip (`cur and not force and cur.get("prompt_sha256") == it["prompt_sha256"]`) dan
  kriteria status OK (`status == OK` dari `lc.OK`) - **baris kode persis sama** dengan V2, hanya kini
  disertai baris log yang terlihat. Lihat `execute()` di `src/11_run_llm.py`.
- Stage 00-09 dan Stage 12 - **tidak ada satu baris pun yang diubah** (dikonfirmasi `diff -rq` terhadap
  V2, lihat bagian "Verifikasi" di bawah).

## Akar masalah (3 faktor independen, semua di layer tampilan/orkestrasi)

1. **Tidak ada indikasi proses sedang berjalan.** `one_run`/`execute` lama langsung memanggil
   `call_ollama()` (HTTP blocking tunggal via `urlopen`) tanpa mencetak apa pun sebelumnya atau selama
   menunggu - total diam 51-337+ detik per panggilan terasa seperti macet.
2. **Tidak ada pesan untuk kombinasi yang di-SKIP.** Resume yang sudah bekerja dengan benar di V2 tidak
   pernah terlihat bekerja, sehingga sulit membedakan "melewati yang sudah sah" dari "diam karena macet".
3. **Kemungkinan buffering stdout saat dipipa.** `run.py` memanggil skrip tahap lewat
   `subprocess.Popen(..., stdout=PIPE, bufsize=1, text=True)`; tanpa `line_buffering` eksplisit pada sisi
   anak (`11_run_llm.py`), baris yang sudah dicetak bisa tertahan di buffer dan tidak langsung terlihat
   oleh proses induk/terminal.

## Perbaikan (hanya `src/11_run_llm.py`)

Semua perubahan dibungkus komentar `# PERBAIKAN V3` di kode agar mudah ditelusuri baris per baris.

1. **Nomor progres `[i/N]`** pada setiap baris log per job (RUNNING/SKIP/REUSED/status akhir).
2. **Baris `[RUNNING]`** dicetak tepat sebelum memanggil `call()` (Ollama/OpenRouter) - jadi terlihat
   model, skenario, unit, dan strategi (P1/P2/P3) mana yang sedang diproses.
3. **Heartbeat `[WAITING]`** setiap `HEARTBEAT_INTERVAL_S` (20 detik) selama menunggu satu respons,
   dengan elapsed time (`elapsed=Ns`). Berjalan di **thread terpisah** (`_heartbeat()`) yang hanya
   mencetak - tidak membaca/menulis apa pun dan tidak menyentuh `call()`/timeout/retry sama sekali.
4. **Baris `[SKIP] ... SKIP — sudah berhasil dijalankan sebelumnya`** (teks persis ini) untuk kombinasi
   yang sudah sah - sebelumnya dilewati tanpa pesan apa pun.
5. **Heartbeat berhenti aman dalam semua kondisi** (ketentuan eksplisit #2 dari pengguna): panggilan
   `call()` dibungkus `try/finally` dengan `stop.set(); hb.join()` di `finally` - sehingga berjalan baik
   saat sukses, saat `LLMError` tertangkap, saat exception tak terduga, **maupun saat Ctrl-C**
   (`KeyboardInterrupt` adalah `BaseException`, bukan `Exception`, sehingga tetap memicu blok `finally`
   lalu menjalar ke atas, bukan tertelan diam-diam).
6. **Isolasi error tak terduga per job.** `except Exception` dipasang di sekitar **satu job**, bukan
   seluruh loop: bug/IO/disk-penuh pada satu kombinasi tidak lagi menghentikan seluruh sisa rencana.
   Dicatat sebagai `status: "GAGAL_TAK_TERDUGA"` (konstanta `UNEXPECTED_FAIL_STATUS`) ke
   `P#.failed.json` dengan **skema field yang sama** dengan kegagalan biasa
   (`model_tag`, `scenario`, `unit_id`, `strategy`, `status`, `note`) - ketentuan eksplisit #1 dari
   pengguna, dijamin tetap kompatibel dibaca `collect()` di `src/12_evaluate.py` (lihat Verifikasi).
7. **`sys.stdout.reconfigure(line_buffering=True)`** di awal `main()` - baris langsung tampil saat
   dipipa oleh `run.py`, bukan menunggu buffer penuh.
8. **`KeyboardInterrupt` di `main()`** ditangani rapi: mencetak pesan bahwa progres yang tersimpan tetap
   sah dan run yang sama bisa diulang untuk melanjutkan, lalu `return 130` - bukan traceback mentah.

## Yang TIDAK diubah (ketentuan eksplisit pengguna)

- Logika resume/skip dan kriteria status OK/gagal: **baris kode sama persis** dengan V2.
- Format `.failed.json`: field inti sama; `collect()` Stage 12 tetap membacanya tanpa perubahan.
- `llm.py` (timeout/retry/payload), Stage 00-09, Stage 12: **tidak disentuh sama sekali**.
- Tidak ada inferensi LLM nyata dan tidak ada run pipeline penuh yang dijalankan untuk membuat V3 ini -
  seluruh pengujian memakai server Ollama tiruan (`_Mock`, lihat `tests/test_v1.py`).
- V2 (`/ord2i_pipeline_simplified_v2/`) tetap utuh; seluruh perubahan berada di folder V3 yang terpisah.

## Pengujian (terarah, dengan Ollama tiruan - tanpa jaringan/model nyata)

Kelas baru di `tests/test_v1.py`: `TestV3Stage11Progress` dan `TestV3Main`, menggunakan mock HTTP server
`_Mock` yang sudah ada (dipakai juga oleh `TestRunner`). Dicakup:

| Uji | Memverifikasi |
|---|---|
| `test_progress_numbers_and_running_reused_skip_messages` | Nomor `[i/N]` benar di setiap baris; teks `[RUNNING]`/`[REUSED]`/status akhir benar; teks **verbatim** `SKIP — sudah berhasil dijalankan sebelumnya` pada run kedua (resume penuh, 0 panggilan baru) |
| `test_heartbeat_waits_then_stops_cleanly_on_success` | `[WAITING]` muncul selama respons lambat (mock server ditunda 0.25s); eksekusi tetap lanjut (tidak macet) |
| `test_heartbeat_helper_stops_immediately_when_stop_is_set` | `_heartbeat()` berhenti (`hb.is_alive()` False) segera setelah `stop.set()` |
| `test_unexpected_error_isolated_per_job_and_stage12_compatible_failed_json` | Exception tak terduga pada satu job (disuntik via monkeypatch `s11.call`) tidak menghentikan job lain; `.failed.json` yang dihasilkan memuat semua field yang dibaca `collect()` Stage 12 |
| `test_ctrl_c_during_execute_is_reported_not_raised_raw` | `KeyboardInterrupt` tetap menjalar keluar dari `execute()` (tidak tertelan `except Exception`), dan tidak tercatat sebagai `GAGAL_TAK_TERDUGA` |
| `test_main_returns_130_on_keyboard_interrupt_without_traceback` | `main()` mengembalikan kode 130 dan pesan rapi, tanpa traceback, saat `execute()` melempar `KeyboardInterrupt` |

Hasil: **28 uji, 27 lulus, 1 dilewati** (`test_units_counts_if_data_present` - dilewati karena
`data/tasks` belum diekstrak di lingkungan audit ini; sama seperti baseline V2, bukan regresi).
Dijalankan dengan:

```bash
python3 -m unittest discover -s tests -v
```

## Verifikasi tambahan

```bash
diff -rq ord2i_pipeline_simplified_v2 ord2i_pipeline_simplified_v3 --exclude=results --exclude=__pycache__
# hanya 2 berkas berbeda: src/11_run_llm.py dan tests/test_v1.py - semua berkas lain (termasuk Stage 00-09
# dan Stage 12) identik byte-per-byte dengan V2.
```

## Berkas yang berubah di V3

| Berkas | Perubahan |
|---|---|
| `src/11_run_llm.py` | Satu-satunya berkas kode yang diubah. Lihat daftar 8 poin "Perbaikan" di atas. |
| `tests/test_v1.py` | Ditambahkan `TestV3Stage11Progress` (5 uji) dan `TestV3Main` (1 uji) + `import time`. Tidak ada uji V2 yang diubah/dihapus. |
| `docs/CHANGELOG_V3.md` | Baru (dokumen ini). |
| `docs/RUN_GUIDE.md` | Diperbarui: instruksi Stage 11 V3 (tampilan baru, resume setelah berhenti di tengah jalan). |

Semua berkas lain (termasuk `src/00_env.py` ... `src/09_prompts.py`, `src/12_evaluate.py`,
`src/correlation.py`, `src/digest.py`, `src/llm.py`, `config/`, `prompts/`, `rules/`, `queries/`,
`cases/`) **identik byte-per-byte** dengan V2.

## Cara menjalankan Stage 11 di V3

Lihat bagian "2. LLM lokal (Ollama)" di `docs/RUN_GUIDE.md` (diperbarui) untuk perintah lengkap dan
contoh tampilan baris log V3. Ringkasnya, perintah **sama persis** dengan V2/V1 - tidak ada argumen baru:

```bash
python3 run.py --stage 11 -- --backend ollama
# atau langsung:
python3 src/11_run_llm.py --backend ollama
```

Bila proses berhenti di tengah jalan (Ctrl-C, listrik mati, SSH putus, dsb.), jalankan ulang **perintah
yang sama persis** - kombinasi yang sudah punya hasil sah otomatis tercatat sebagai
`[i/N] SKIP — sudah berhasil dijalankan sebelumnya` dan tidak memanggil LLM lagi; hanya kombinasi yang
belum selesai yang diproses. Ini **bukan fitur baru** (logika resume tidak diubah dari V2) - yang baru
di V3 adalah baris `[SKIP]` tersebut kini benar-benar terlihat, sehingga bisa dipastikan secara visual
bahwa resume berjalan sebagaimana mestinya.
