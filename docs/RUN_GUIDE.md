# Panduan menjalankan pipeline

Panduan ini ditulis untuk Ubuntu (VM atau komputer lokal). Semua perintah dijalankan dari folder utama proyek. Setiap `python3 run.py ...` menulis log lengkap ke `logs/<waktu>_stageNN_*.log` (perintah, versi Python, SHA-256 `config/pipeline.json`, keluaran, kode keluar, durasi).

## Struktur folder (ringkas)

```
├── run.py                  # orkestrator: python3 run.py --stage NN[-MM] [--scenario ...] [-- <argumen skrip>]
├── config/pipeline.json    # pengaturan operasional (model, strategi, parameter prompt)
├── src/NN_nama.py          # satu skrip per tahap (00–13), bisa dijalankan langsung: python3 src/NN_nama.py --scenario N
├── src/correlation.py      # rumus korelasi (Chabot et al., 2015) dan kanonikalisasi event duplikat
├── src/digest.py           # aturan pemilihan evidence untuk digest
├── src/llm.py              # klien Ollama dan OpenRouter
├── prompts/templates/      # P1/P2/P3.txt, rules.txt, correlation_scale.txt, format_example.txt
├── rules/, queries/        # aturan klasifikasi event, query SPARQL Q01–Q17
├── cases/correlation_cases.json   # definisi uji kewajaran korelasi (stage 07)
├── acceptance/             # nilai acuan hasil, dipakai stage 00 dan tools/check_legacy.py
├── data/                   # dataset (scenario1–3/events, tasks/); tidak pernah ditulis oleh pipeline
├── results/                # seluruh keluaran tahap (lihat "Lokasi hasil")
├── logs/                   # satu .log per eksekusi run.py
├── tests/                  # unit test (tanpa data dan tanpa jaringan)
├── tools/                  # setup_data.py, check_legacy.py
└── docs/                   # METHODOLOGY, REFERENCE, RUN_GUIDE, DECISIONS, LIMITATIONS
```

## 0. Persiapan (sekali)

```bash
sudo apt-get install -y python3-venv          # bila belum ada
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt               # rdflib==7.5.0 (wajib); nltk, rouge-score (opsional, pembanding metrik)
python3 tools/setup_data.py --zips /path/ke/02_DATASET   # mengekstrak 4 ZIP ke data/ dan menulis DATA_MANIFEST.json
python3 -m unittest discover -s tests -v      # tanpa jaringan
python3 run.py --stage 00                     # cek lingkungan dan tata letak data
```

Gunakan `.venv`. Stage 12 membaca `nltk` dan `rouge_score` bila terpasang; tanpa keduanya, kolom `lib_*` pada `runs_wide.csv` kosong. `run.py` memakai `sys.executable`, jadi aktifkan venv sebelum menjalankan.

Empat ZIP yang diharapkan `setup_data.py`: `events scenario1.zip`, `events scenario2.zip`, `events scenario3.zip`, dan `tasks.zip`.

## 1. Tahap data (tanpa LLM, tanpa jaringan)

Jalankan satu per satu dan periksa keluarannya sebelum lanjut:

```bash
python3 run.py --stage 01     # audit data dan GT (hanya membaca): results/01_audit/audit_summary.md
python3 run.py --stage 02     # preprocessing dan klasifikasi event
python3 run.py --stage 03     # bangun RDF
python3 run.py --stage 04     # validasi RDF
python3 run.py --stage 05     # SPARQL Q01–Q17 (dengan uji determinisme); periksa baris "kosong ..."
python3 run.py --stage 06     # validitas pengambilan S2/S3 (P/R/F1)
python3 run.py --stage 07     # korelasi dan uji kasus regedit S2
python3 run.py --stage 08     # digest unit=task
python3 run.py --stage 09     # prompt unit=task; baris RINGKASAN = jumlah panggilan LLM pasti
```

- Satu skenario saja: tambahkan `--scenario 2`.
- Rentang sekaligus: `python3 run.py --stage 02-09`. Tahap 10, 11, dan 13 tidak pernah ikut rentang; jalankan sendiri-sendiri.
- Verifikasi hasil terhadap nilai acuan (disarankan):

```bash
python3 run.py --stage 08 --unit scenario
python3 run.py --stage 09 --unit scenario
python3 tools/check_legacy.py                 # semua baris harus COCOK; keluaran di results/legacy_check.json
```

`check_legacy.py` membandingkan hash dan jumlah baris keluaran stage 02, 03, 05, 07, dan 08 dengan nilai di `acceptance/`. Hasil `BEDA` berarti data masukan atau kode berbeda dari yang dipakai untuk nilai acuan.

## 2. LLM lokal (Ollama)

```bash
ollama pull qwen2.5:0.5b && ollama pull qwen2.5:1.5b
python3 run.py --stage 10 -- --local --probe                                     # model terpasang + satu generasi kecil
python3 run.py --stage 11 -- --dry-run --backend ollama                           # rencana, ukuran prompt, PERINGATAN_KONTEKS
python3 run.py --stage 11 -- --backend ollama --model qwen2.5-0.5b --scenario 2 --limit 1   # pilot: 1 unit × 3 strategi
python3 run.py --stage 12                                                         # evaluasi pilot
python3 run.py --stage 11 -- --backend ollama                                     # semua unit lokal (dapat dihentikan dan dilanjutkan)
python3 run.py --stage 12
```

Opsi pemilihan pada stage 11:

| Opsi | Fungsi |
|---|---|
| `--model <tag>` | hanya model tertentu (boleh berulang) |
| `--scenario N` | hanya skenario tertentu |
| `--strategy P1\|P2\|P3` | hanya satu strategi |
| `--unit-id ID` | hanya unit tertentu (boleh berulang) |
| `--limit N` | hanya N unit pertama per skenario (untuk pilot) |
| `--force` | mengulang paksa run yang sudah sah |
| `--dry-run` | hanya mencetak rencana |

Run yang sudah sah (status `OK`, hash prompt cocok) dilewati otomatis saat diulang (`SKIP_SUDAH_SAH` di ringkasan akhir). Hasil `GAGAL` atau yang belum lengkap tetap dijalankan ulang tanpa `--force`.

### Membaca progres stage 11

Contoh keluaran di terminal:

```
rencana: 69 laporan (model x unit x strategi), 69 panggilan LLM berbeda (prompt identik dipakai ulang); unit=task
[1/69] RUNNING | qwen2.5-0.5b | scenario1 | 0-launch-edge | P1
[1/69] OK | qwen2.5-0.5b | scenario1 | 0-launch-edge | P1 | 42.17s in=812 out=256 finish=stop
[2/69] RUNNING | qwen2.5-0.5b | scenario1 | 0-launch-edge | P2
[2/69] [WAITING] [2/69] qwen2.5-0.5b | scenario1 | 0-launch-edge | P2 | elapsed=20s
[2/69] OK | qwen2.5-0.5b | scenario1 | 0-launch-edge | P2 | 51.43s in=940 out=300 finish=stop
...
[37/69] SKIP — sudah berhasil dijalankan sebelumnya | qwen2.5-0.5b | scenario2 | reg-launch-prefetch | P1
...
ringkasan: {'OK': 66, 'SKIP_SUDAH_SAH': 3}
```

- `[i/N]` adalah nomor job saat ini dari total rencana, diikuti model, skenario, unit, dan strategi.
- `RUNNING` dicetak tepat sebelum memanggil Ollama atau OpenRouter untuk job itu.
- `[WAITING] ... elapsed=Ns` dicetak setiap 20 detik selama menunggu satu respons, sehingga proses yang terlihat diam (respons LLM lokal bisa 50–300+ detik) tetap terlihat berjalan.
- `SKIP` menandai kombinasi yang sudah punya hasil sah.
- Error tak terduga pada satu job (misalnya disk penuh) dicatat sebagai `GAGAL_TAK_TERDUGA` ke `P#.failed.json`, dan job lain tetap lanjut.

### Bila stage 11 berhenti di tengah jalan

Jalankan ulang **perintah yang sama persis** (listrik mati, SSH putus, Ctrl-C, dan sebagainya). Setiap kombinasi (model, skenario, unit, strategi) yang sudah punya hasil sah dilewati tanpa panggilan LLM baru; hanya yang belum selesai yang diproses. Ctrl-C yang disengaja juga aman: proses mencetak `DIHENTIKAN oleh pengguna (Ctrl-C)`, keluar dengan kode 130, dan progres yang tersimpan tetap sah.

### Mengevaluasi ulang hasil LLM yang sudah ada

```bash
python3 src/12_evaluate.py --scenario all        # tidak memanggil LLM
```

Stage 12 hanya membaca ulang `results/unit_task/11_llm/**/P*.json`, `08_digest/`, dan `09_prompts/`. Jalankan kapan pun ada hasil LLM baru dan hasilnya ingin masuk ke `eval_report.md`, `metrics_long.csv`, dan `runs_wide.csv`.

## 3. LLM cloud (OpenRouter)

Jalankan setelah hasil lokal ditinjau dan estimasi biaya disetujui.

```bash
export OPENROUTER_API_KEY=...                                   # tidak pernah ditulis ke berkas atau log
python3 run.py --stage 10 -- --cloud                            # snapshot harga/konteks/ketersediaan + validasi kunci (tanpa generasi)
python3 run.py --stage 11 -- --dry-run --backend openrouter     # estimasi biaya batas atas dari snapshot
python3 run.py --stage 11 -- --backend openrouter --confirm-cloud --scenario 2 --limit 1   # pilot cloud
python3 run.py --stage 11 -- --backend openrouter --confirm-cloud
python3 run.py --stage 12
```

Stage 11 cloud menolak berjalan bila:
- `--confirm-cloud` tidak ada;
- kunci API tidak diset;
- snapshot harga lebih tua dari 7 hari;
- estimasi biaya melebihi `cloud_guard.max_estimated_cost_usd` (`config/pipeline.json`, default 1 USD).

Provider OpenRouter tidak dikunci; provider tiap panggilan dicatat pada kolom `provider`.

## 4. SBERT (opsional, hanya skenario 1)

Stage 13 menghitung kemiripan semantik antara laporan dan referensi. Stage ini tidak ikut rentang dan hanya membaca hasil stage 08, 11, dan 12. Petunjuk pemasangan dan perintahnya ada di `README.md` (bagian "Stage 13: SBERT").

## 5. Menjalankan ulang sebagian ke folder varian

`--variant NAMA` (stage 08, 09, 11, 12) menulis ke `results/unit_task__NAMA` tanpa menyentuh hasil utama. `--unit-id ID` (stage 08, 11, 12) membatasi proses ke satu unit dan wajib disertai `--variant`.

Agregat stage 12 (`summary_overall.csv`, `summary_by_scenario.csv`, `eval_report.md`) tidak dapat digabung dari hasil satu unit; ketiganya harus dihitung ulang dari seluruh laporan.

## 6. Berkas hasil yang perlu disimpan

- `logs/*.log` dari tahap yang dijalankan: perintah persis, waktu, dan ringkasan tiap tahap.
- `results/01_audit/audit_summary.md`: audit data dan GT, termasuk kelompok berkas isi-identik.
- `results/unit_task/12_eval/eval_report.md`, `metrics_long.csv`, dan `runs_wide.csv`: hasil evaluasi LLM (M0–M8, P/R/F1, dan BLEU/ROUGE bila `reference_valid`). Simpan `metrics_long.csv` dan `runs_wide.csv` secara utuh agar kolom per run dapat diperiksa satu per satu.
- `results/unit_task/12_eval/failures.csv`: daftar run yang gagal atau tidak lengkap (kosong berarti tidak ada kegagalan).
- `results/legacy_check.json`: hanya ada bila `tools/check_legacy.py` dijalankan.
- Laporan per tahap bila diperlukan: `results/04_validate/validation_scenarioN.json`, `results/05_sparql/scenarioN/sparql_report.json`, `results/07_correlation/scenarioN/correlation_report.json`, dan `results/unit_task/09_prompts/scenarioN/<unit>/prompts_report.json`.

## Lokasi hasil

| Tahap | Folder |
|---|---|
| 00–07 | `results/00_env` … `results/07_correlation` |
| 08–12 | `results/unit_task/` (utama) atau `results/unit_scenario/` |
| 10 | `results/10_models/` |
| 13 | `results/unit_task/13_sbert/` |

Dataset di `data/` tidak pernah ditulis oleh pipeline.

## Verifikasi unit berkas isi-identik

Tugas `4616-with-regex` dan `4616-without-regex` (skenario 3) berisi berkas yang sama, sehingga prompt P2 keduanya harus identik:

```bash
python3 src/09_prompts.py --scenario 3 --unit task
diff results/unit_task/09_prompts/scenario3/4616-with-regex/P2.txt \
     results/unit_task/09_prompts/scenario3/4616-without-regex/P2.txt     # harus kosong (identik)
grep "4616" logs/<waktu>_stage09_*.log        # baris "prompt identik ...: [['4616-with-regex', '4616-without-regex']]"
python3 -m unittest tests.test_v1.TestDuplicateContentGroups -v
```
