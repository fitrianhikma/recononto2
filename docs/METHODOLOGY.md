# Keputusan metodologi V1

V1 adalah **refactoring** pipeline tesis yang sudah ada, bukan pembangunan ulang eksperimen. Keputusan lama D1–D32 (`docs/legacy/DECISIONS.md`) tetap berlaku kecuali yang disebut di bawah.

## Keputusan yang disetujui peneliti

| # | Keputusan | Implementasi |
|---|---|---|
| (a) | M0–M8 dipertahankan penuh; `task_hit` tidak ditambahkan; format laporan lama untuk semua skenario; metrik baru hanya kolom tambahan | `src/report_metrics.py` (identik dengan evaluator lama) + `src/extra_metrics.py` |
| (b) | P2 = top-5 korelasi; P3 = satu laporan contoh lengkap sintetis; prompt lama diarsipkan; bagian prompt lain tidak diubah; tanpa kebocoran | `prompts/templates/` (rules, P1, P2, P3, correlation_scale tidak berubah), `prompts/archive_v0/`, pemeriksaan di `src/09_prompts.py` |
| (c) | S1: semantik himpunan, identitas (tipe, detik, evidence_source ternormalisasi); jumlah mentah/unik dan recall berbobot dilaporkan; peringatan presisi S1 = batas bawah | `src/tasks.py`, `src/extra_metrics.py`, `eval_report.md` |
| (d) | `unit=task` utama; `unit=scenario` untuk kompatibilitas | `--unit`; hasil di `results/unit_task/` dan `results/unit_scenario/` (tidak pernah tercampur) |
| — | Model: Qwen2.5 0.5B dan 1.5B (Ollama); `meta-llama/llama-3.1-8b-instruct` dan `qwen/qwen-2.5-7b-instruct` (OpenRouter) | `config/pipeline.json` |
| — | Harga dan ketersediaan OpenRouter diperiksa sebelum eksperimen cloud | stage 10 `--cloud` (snapshot), stage 11 menolak tanpa snapshot baru, `--confirm-cloud`, dan estimasi di bawah batas |

## Unit dan perhitungan eksperimen

| | S1 | S2 | S3 | Total |
|---|---|---|---|---|
| Berkas events | 15 | 7 | 5 | 27 |
| Tugas (berkas GT resmi) = unit tugas | 14 | 7 | 5 | **26** |
| Berkas events tanpa GT (ikut RDF/korelasi, bukan tugas) | 8-firefox-install | – | – | 1 |
| Isi berkas tugas berbeda (unit data) | 14 | 7 | 3 | 24 |
| Unit tanpa event berwaktu valid (digest tidak dapat dibangun) | – | – | exe, OneDrive | 2 |
| Unit dengan digest/prompt | 14 | 7 | 3 | **24** |
| Set prompt berbeda (perkiraan; angka pasti dicetak stage 09) | 14 | 7 | 2 | **23** |

> **Catatan riwayat (V2):** angka 23/276 di bawah ini awalnya hanya diverifikasi lewat sampel 500 baris/berkas.
> Run data PENUH pertama (sebelum perbaikan V2) sempat mencetak 24 set prompt/288 panggilan, karena bug teknis
> pada ringkasan korelasi P2 untuk unit berkas isi-identik (`4616-with-regex`/`4616-without-regex`) - lihat
> `docs/CHANGELOG_V2.md` bagian 1. Setelah diperbaiki, run data penuh kembali menghasilkan 23/276 seperti di
> bawah, kini terverifikasi langsung terhadap data penuh, bukan hanya sampel.

Perhitungan panggilan dan laporan:

| | Rumus | Jumlah |
|---|---|---|
| Panggilan LLM per model | 23 × 3 strategi | 69 |
| Panggilan LLM total | 69 × 4 model | **276** (138 lokal + 138 cloud) |
| Laporan yang dievaluasi | 24 × 3 × 4 | **288** |
| Tugas tanpa laporan LLM | exe, OneDrive | 2 tugas S3; dievaluasi di tingkat pengambilan SPARQL (stage 06) |

Penjelasan:
- **Isi identik.** `exe.csv` = `OneDrive.csv` dan `4616-with-regex.csv` = `4616-without-regex.csv` (SHA-256 sama). Preprocessing dan RDF tidak diduplikasi secara logika: satu graf per skenario, seperti pipeline lama. Setiap tugas tetap punya GT, digest, prompt, dan evaluasi sendiri.
- **Prompt identik.** Prompt kedua tugas 4616 identik, karena aturan prompt lama tidak memuat instruksi khusus tugas. LLM dipanggil sekali, lalu laporan yang sama dievaluasi terhadap GT masing-masing (`llm_call=False`, `reused_from`).
- **Tanpa event berwaktu.** `exe.csv` dan `OneDrive.csv` berisi 2.000 baris tanpa timestamp valid (1.996 `0000-00-00`, 4 FILETIME nol; diperiksa langsung dari berkas). Aturan digest lama (D3/D8) hanya memakai event berwaktu, sehingga digest per tugas tidak dapat dibangun **tanpa mengubah aturan digest**. V1 tidak mengubahnya. Unit ditandai `NO_TIMED_EVENTS` dan dilewati di stage 09/11. Pada `unit=scenario` (perilaku lama), baris ini hanya muncul sebagai hitungan di digest S3.
- **Mode `unit=scenario`.** 3 unit × 3 × 4 = 36 laporan (pipeline lama tanpa TinyLlama dan Qwen-72B). Digest dan P1 identik byte-per-byte dengan pipeline lama; P2/P3 berbeda sesuai keputusan (b).

## Metrik per jenis tugas

| Skenario / tugas | Metrik utama | Metrik lain | BLEU/ROUGE |
|---|---|---|---|
| S1 event summarization | M0–M8; `t_precision` (batas bawah, vs GT multiple), `t_recall` (vs single), `tm_recall` (vs multiple), `t_f1` | `t_recall_weighted`, `t_recall_conditional`, `t_recall_mention` | **ya**, bila `reference_valid` |
| S2 keyword analysis | M0–M8; `t_precision`, `t_recall`, `t_f1` (deterministik vs GT) | idem; stage 06: P/R/F1 pengambilan SPARQL | tidak |
| S3 grep | M0–M8; `t_precision`, `t_recall`, `t_f1` | idem; stage 06: P/R/F1 pengambilan SPARQL (termasuk exe 362 baris) | tidak |

Rincian rumus: `REFERENCE.md` bagian 1.

## Ground truth dan dataset

Dataset dan GT hanya dibaca. Tidak ada GT baru, termasuk `scenario1.txt` dan narasi buatan peneliti. Folder `results/` di `tasks.zip` adalah keluaran ChatGPT dari paper dataset, bukan GT, dan tidak dipakai.

Cacat format berkas resmi ditangani pembaca lama di memori dan dilaporkan stage 01/02:
- `windows-firewall-disabled-evtx.csv`: header menyatu dengan baris data;
- `OneDrive.csv` dan `exe.csv`: header ganda.

## Hal yang memerlukan keputusan peneliti (tidak diubah di V1)

1. **Tugas S3 tanpa event berwaktu (exe, OneDrive).** Biarkan tanpa laporan LLM (V1). Alternatifnya digest varian untuk event tanpa waktu, yang mengubah aturan digest.
2. **Instruksi tugas di prompt.** Prompt lama tidak memuat pertanyaan tugas: kata kunci S2 dan pola grep S3 tidak diberikan ke model. Model menulis laporan insiden umum dan dievaluasi lewat cakupan GT. Ini sama dengan pipeline lama. Paper dataset (`main.pdf`) memakai prompt khusus tugas dengan/tanpa *additional knowledge*. Menambah instruksi tugas adalah perubahan prompt dan belum dilakukan.
3. **Rumus korelasi** (Chabot vs SIET) dan ambang ">" vs "≥": lihat `REFERENCE.md` bagian 3.
4. **Pola grep OneDrive** `OneDrive|OneDrive\.exe` disimpulkan dari teks paper yang terpotong (cocok 6/6 dengan GT).
5. **Kata kunci S2 literal-bracket** adalah operasionalisasi V1, ditambahkan berdampingan dengan metode lama (`src/keywords.py`).

## Keterbatasan LIM-01: blok korelasi pada prompt P2 hampir selalu kosong

Blok `CORRELATIONS` pada P2 hanya memuat pasangan yang **kedua event-nya ada di evidence digest** (`src/09_prompts.py`, `correlation_block`). Evidence hanya 0,05%-0,9% dari event kanonik, sehingga pada eksperimen beku 288 slot: 21 dari 24 unit tanpa pasangan, total 5 pasangan (4 aturan pakar) sampai ke LLM. Skor korelasi dihitung benar (Stage 07; pemetaan lewat `row_hash` memberi top-5 identik pada 24/24 unit), tetapi hampir tidak memengaruhi prompt.

Akibat: selisih P2 terhadap P1 pada sebagian besar unit tidak dapat ditafsirkan sebagai efek korelasi ORDi. Klaim bahwa alur ORDi terimplementasi dan terverifikasi tetap berlaku. Tidak ada pasangan tambahan yang dibuat secara artifisial; implementasi tidak diubah.

## Validasi laporan `validation_v2` (MIN-02) dan perbaikan R1 (MIN-01)

- Status `OK` Stage 11 berarti **respons diterima dan tidak kosong**, bukan "laporan valid". Respons kosong/whitespace/`null` pada run baru menjadi `GAGAL_RESPON_KOSONG`. Validitas laporan dinilai terpisah (`src/report_validation.py`; keluaran tambahan `report_validity.csv` dari Stage 12) pada empat tingkat: transport, keberadaan respons, struktur, ID evidence. Metrik M0-M8 dan `pure` tidak berubah.
- MIN-01: event aturan pakar R1 dipetakan lewat `row_hash` ke IRI kanonik unit (`digest.ek_to_unit_canonical`). Baseline 288 slot dihasilkan SEBELUM perbaikan ini; hasil verifikasi ditulis ke folder varian terpisah (lihat `docs/FINAL_REFACTOR_AND_FIX_REPORT.md`).
