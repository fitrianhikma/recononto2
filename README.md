# Pipeline ORD2I + SIET untuk tiga skenario forensik Zenodo

Pipeline 14 tahap (00–13) yang dapat dijalankan satu per satu untuk menguji analisis timeline forensik berbasis LLM. Alurnya:
events Plaso → preprocessing → RDF (konsep ORD2I) → validasi → SPARQL → korelasi → digest → prompt P1/P2/P3 → LLM → evaluasi.

Eksperimen memakai tiga skenario dataset forensik Zenodo, unit evaluasi per tugas, tiga strategi prompt (P1 baseline, P2 dengan konteks korelasi top-5, P3 dengan satu contoh laporan lengkap), dan empat model (dua lokal, dua cloud).

- Panduan menjalankan: **[docs/RUN_GUIDE.md](docs/RUN_GUIDE.md)**
- Keputusan dan hitungan eksperimen: [docs/METHODOLOGY.md](docs/METHODOLOGY.md)

## Mulai cepat

```bash
python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
python3 tools/setup_data.py --zips /path/ke/02_DATASET
python3 run.py --list
python3 run.py --stage 00
python3 run.py --stage 01
```

## Tahap

| No | Skrip | Fungsi | Jaringan |
|---|---|---|---|
| 00 | `00_check_env.py` | cek Python, rdflib, data, templat | – |
| 01 | `01_audit_data.py` | audit data dan GT (hanya membaca), diagnosis kata kunci S2, reproduksi grep S3, hitungan unit | – |
| 02 | `02_preprocess.py` | klasifikasi event (rule v2), status timestamp | – |
| 03 | `03_build_rdf.py` | satu graf N-Triples per skenario (CKL/SKL/TKL) | – |
| 04 | `04_validate_rdf.py` | validasi V0–V7, lokalisasi GT | – |
| 05 | `05_sparql.py` | Q01–Q17 + analisis query kosong | – |
| 06 | `06_retrieval_eval.py` | P/R/F1 pengambilan SPARQL vs GT (S2, S3) | – |
| 07 | `07_correlate.py` | korelasi gaya Chabot + uji kasus | – |
| 08 | `08_digest.py` | digest per unit (`--unit task|scenario`) | – |
| 09 | `09_prompts.py` | prompt P1/P2/P3 + cek kebocoran contoh | – |
| 10 | `10_models_check.py` | cek Ollama; snapshot harga OpenRouter | ya |
| 11 | `11_run_llm.py` | menjalankan LLM (cloud perlu `--confirm-cloud`) | ya |
| 12 | `12_evaluate.py` | M0–M8 + P/R/F1 + BLEU/ROUGE (S1) | – |
| 13 | `13_sbert.py` | opsional: kemiripan semantik SBERT (S1); dijalankan sendiri, tidak ikut rentang | – (model dari cache lokal) |

## Stage 13: SBERT (opsional, skenario 1)

Stage 13 hanya membaca hasil stage 08, 11, dan 12 serta ground truth, lalu menulis ke `results/unit_task/13_sbert/`. Hasil stage 00–12 tidak diubah.

```bash
source .venv/bin/activate
pip install torch --index-url https://download.pytorch.org/whl/cpu   # torch versi CPU
pip install -r requirements-sbert.txt
hf download sentence-transformers/all-MiniLM-L6-v2 --revision 1110a243fdf4706b3f48f1d95db1a4f5529b4d41   # sekali saja; stage 13 tidak mengunduh
python src/13_sbert.py --revision 1110a243fdf4706b3f48f1d95db1a4f5529b4d41 --verify-determinism
# atau lewat orkestrator (tidak pernah ikut rentang):
python run.py --stage 13 -- --revision 1110a243fdf4706b3f48f1d95db1a4f5529b4d41 --verify-determinism
```

Keluaran di `results/unit_task/13_sbert/`: `sbert_per_report.csv`, `sbert_summary_by_cell.csv`, `sbert_baselines.csv`, dan `sbert_report.json` (revisi model, versi pustaka, hasil pemeriksaan). Kode keluar 1 jika ada pemeriksaan yang gagal: hash `results/` berubah, referensi terhadap dirinya tidak ≈ 1, ada skor di luar [−1, 1], atau dua kali perhitungan tidak identik. Unit test tanpa model: `python -m unittest tests.test_sbert -v`.

## Struktur

```
run.py                 orkestrator + log per eksekusi (logs/)
config/pipeline.json   satu berkas pengaturan operasional (model, unit, pola grep S3, penjaga biaya)
src/                   kode (NN_*.py per tahap + modul pustaka)
queries/               Q01–Q17 (.rq) + catalog.json (padanan SIET, alasan query kosong)
prompts/templates/     templat prompt P1/P2/P3 dan bagian pendukungnya
rules/                 event_rules(_v2).csv, digest_weights.csv
cases/                 definisi uji kewajaran korelasi
acceptance/            nilai acuan hasil (untuk tools/check_legacy.py)
tools/                 setup_data.py, check_legacy.py
tests/                 unit test kecil (tanpa data/jaringan)
docs/                  metodologi, panduan, referensi metrik, keputusan, keterbatasan
data/                  dataset (diisi tools/setup_data.py; hanya dibaca)
results/, logs/        keluaran (tidak disertakan di repositori)
```

## Model

| Tag | Backend | ID |
|---|---|---|
| qwen2.5-0.5b | Ollama | `qwen2.5:0.5b` |
| qwen2.5-1.5b | Ollama | `qwen2.5:1.5b` |
| llama-3.1-8b | OpenRouter | `meta-llama/llama-3.1-8b-instruct` |
| qwen-2.5-7b | OpenRouter | `qwen/qwen-2.5-7b-instruct` |

Harga awal OpenRouter (informasi saja; dari halaman OpenRouter yang terindeks mesin pencari pada 2 November 2026, bukan lewat API):

| Model | Input | Output | Konteks |
|---|---|---|---|
| Llama 3.1 8B | US$0,02 / 1 juta token | US$0,05 / 1 juta token | 16.384 |
| Qwen2.5 7B | US$0,10 / 1 juta token | US$0,20 / 1 juta token | 32.768 |

Harga yang dipakai pipeline adalah snapshot stage 10. Parameter generasi: temperatur 0, seed 42, `num_ctx` 4.096 untuk model lokal, keluaran maksimal 900 token.

## Dokumen

- [docs/RUN_GUIDE.md](docs/RUN_GUIDE.md): langkah menjalankan tiap tahap, LLM lokal dan cloud, dan cara melanjutkan run yang terhenti.
- [docs/METHODOLOGY.md](docs/METHODOLOGY.md): keputusan desain, unit dan hitungan panggilan, metrik per tugas, dan batasan desain.
- [docs/REFERENCE.md](docs/REFERENCE.md): rumus semua metrik, dasar strategi prompting (SIET), dan verifikasi rumus korelasi terhadap Chabot (2015).
- [docs/DECISIONS.md](docs/DECISIONS.md): keputusan metodologis rinci beserta alasannya.
- [docs/LIMITATIONS.md](docs/LIMITATIONS.md): keterbatasan data, korelasi, digest, LLM, dan evaluasi.

## Ringkasan hasil dan keterbatasan

Hasil lengkap ada di `results/unit_task/` (manifest: `results/unit_task/MANIFEST_SHA256_unit_task.txt`); folder ini tidak disertakan di repositori dan dirilis terpisah.

- 288 laporan LLM (24 unit × 4 model × 3 strategi) dievaluasi; 0 gagal. `report_validity.csv` menandai **211 VALID dan 77 INVALID**. Rinciannya 48 `INVALID_EVIDENCE_ID`, 23 `INCOMPLETE_STRUCTURE`, dan 6 `TRUNCATED`. Semua laporan INVALID dipertahankan dan tetap ikut dalam agregat subset `all`.
- Hasil bersifat deskriptif. Satu run per kondisi (temperatur 0), tanpa uji signifikansi. Hasil tidak mendukung klaim keunggulan model, strategi prompt, atau backend (backend tercampur dengan ukuran model).
- Subset `pure`/`paired_pure` dan `summary_overall.csv` bukan penyaring mutu atau ringkasan yang layak untuk kesimpulan.
- BLEU/ROUGE hanya tersedia untuk skenario 1. Dua unit skenario 3 (`OneDrive`, `exe`) tidak punya laporan LLM.
- Stage 12 perlu dijalankan dengan `.venv` agar kolom pembanding `lib_*` (nltk, rouge-score) terisi.
