# Keputusan metodologi

Dokumen ini merangkum keputusan desain eksperimen: apa yang dievaluasi, berapa unit dan laporan yang dihasilkan, metrik apa yang dipakai untuk tiap jenis tugas, serta batasan yang perlu diketahui saat membaca hasil. Definisi metrik ada di `REFERENCE.md`; keputusan metodologis rinci ada di `DECISIONS.md`; cara menjalankan ada di `RUN_GUIDE.md`.

## Keputusan desain

| # | Keputusan | Implementasi |
|---|---|---|
| (a) | Metrik inti M0–M8 dipertahankan penuh dengan format laporan yang sama untuk semua skenario. Metrik tugas ditambahkan sebagai kolom terpisah. | `src/report_metrics.py`, `src/extra_metrics.py` |
| (b) | P2 memakai top-5 pasangan korelasi. P3 memakai satu laporan contoh lengkap yang sintetis. Tidak ada kebocoran fakta atau ID dari data nyata ke contoh. | `prompts/templates/` (rules, P1, P2, P3, correlation_scale, format_example), pemeriksaan di `src/09_prompts.py` |
| (c) | Evaluasi S1 memakai semantik himpunan. Identitas butir = (tipe, detik, `evidence_source` ternormalisasi). Jumlah mentah dan unik serta recall berbobot dilaporkan. Presisi S1 adalah batas bawah. | `src/tasks.py`, `src/extra_metrics.py`, `eval_report.md` |
| (d) | `unit=task` sebagai unit utama; `unit=scenario` tersedia sebagai pembanding. Hasil keduanya disimpan terpisah. | opsi `--unit`; `results/unit_task/` dan `results/unit_scenario/` |
| (e) | Model: Qwen2.5 0.5B dan 1.5B (Ollama); `meta-llama/llama-3.1-8b-instruct` dan `qwen/qwen-2.5-7b-instruct` (OpenRouter). | `config/pipeline.json` |
| (f) | Harga dan ketersediaan OpenRouter diperiksa sebelum eksperimen cloud. | stage 10 `--cloud` (snapshot); stage 11 menolak jika snapshot tidak baru, tanpa `--confirm-cloud`, atau estimasi biaya melebihi batas |

## Unit dan perhitungan eksperimen

| | S1 | S2 | S3 | Total |
|---|---|---|---|---|
| Berkas events | 15 | 7 | 5 | 27 |
| Tugas (berkas GT resmi) = unit tugas | 14 | 7 | 5 | **26** |
| Berkas events tanpa GT (ikut RDF dan korelasi, bukan tugas) | 8-firefox-install | – | – | 1 |
| Isi berkas tugas berbeda (unit data) | 14 | 7 | 3 | 24 |
| Unit tanpa event berwaktu valid (digest tidak dapat dibangun) | – | – | exe, OneDrive | 2 |
| Unit dengan digest dan prompt | 14 | 7 | 3 | **24** |
| Set prompt berbeda (perkiraan; angka pasti dicetak stage 09) | 14 | 7 | 2 | **23** |

Perhitungan panggilan dan laporan:

| | Rumus | Jumlah |
|---|---|---|
| Panggilan LLM per model | 23 × 3 strategi | 69 |
| Panggilan LLM total | 69 × 4 model | **276** (138 lokal + 138 cloud) |
| Laporan yang dievaluasi | 24 × 3 × 4 | **288** |
| Tugas tanpa laporan LLM | exe, OneDrive | 2 tugas S3; dievaluasi di tingkat pengambilan SPARQL (stage 06) |

Penjelasan:
- **Isi identik.** `exe.csv` = `OneDrive.csv` dan `4616-with-regex.csv` = `4616-without-regex.csv` (SHA-256 sama). Preprocessing dan RDF tidak diduplikasi secara logika: satu graf per skenario. Setiap tugas tetap punya GT, digest, prompt, dan evaluasi sendiri.
- **Prompt identik.** Prompt kedua tugas 4616 identik, karena templat prompt tidak memuat instruksi khusus tugas. LLM dipanggil sekali, lalu laporan yang sama dievaluasi terhadap GT masing-masing (`llm_call=False`, `reused_from`).
- **Tanpa event berwaktu.** `exe.csv` dan `OneDrive.csv` berisi 2.000 baris tanpa timestamp valid (1.996 `0000-00-00`, 4 FILETIME nol; diperiksa langsung dari berkas). Aturan digest hanya memakai event berwaktu, sehingga digest per tugas tidak dapat dibangun tanpa mengubah aturan digest. Unit ditandai `NO_TIMED_EVENTS` dan dilewati di stage 09 dan 11. Pada `unit=scenario`, baris ini hanya muncul sebagai hitungan di digest S3.
- **Mode `unit=scenario`.** 3 unit × 3 strategi × 4 model = 36 laporan.

## Metrik per jenis tugas

| Skenario / tugas | Metrik utama | Metrik lain | BLEU/ROUGE |
|---|---|---|---|
| S1 event summarization | M0–M8; `t_precision` (batas bawah, vs GT multiple), `t_recall` (vs single), `tm_recall` (vs multiple), `t_f1` | `t_recall_weighted`, `t_recall_conditional`, `t_recall_mention` | **ya**, bila `reference_valid` |
| S2 keyword analysis | M0–M8; `t_precision`, `t_recall`, `t_f1` (deterministik vs GT) | idem; stage 06: P/R/F1 pengambilan SPARQL | tidak |
| S3 grep | M0–M8; `t_precision`, `t_recall`, `t_f1` | idem; stage 06: P/R/F1 pengambilan SPARQL (termasuk exe, 362 baris) | tidak |

Rincian rumus: `REFERENCE.md` bagian 1.

## Ground truth dan dataset

Dataset dan GT hanya dibaca. Tidak ada GT baru, termasuk `scenario1.txt` dan narasi buatan peneliti. Folder `results/` di `tasks.zip` adalah keluaran ChatGPT dari paper dataset (Studiawan, Breitinger & Scanlon, 2025), bukan GT, dan tidak dipakai.

Cacat format berkas resmi ditangani pembaca di memori dan dilaporkan stage 01 dan 02:
- `windows-firewall-disabled-evtx.csv`: header menyatu dengan baris data;
- `OneDrive.csv` dan `exe.csv`: header ganda.

## Keputusan terbuka dan batasan desain

1. **Tugas S3 tanpa event berwaktu (exe, OneDrive).** Saat ini tidak diberi laporan LLM. Alternatifnya adalah digest varian untuk event tanpa waktu, yang berarti mengubah aturan digest.
2. **Instruksi tugas di prompt.** Prompt tidak memuat pertanyaan tugas: kata kunci S2 dan pola grep S3 tidak diberikan ke model. Model menulis laporan insiden umum dan dievaluasi lewat cakupan GT. Paper dataset memakai prompt khusus tugas dengan dan tanpa *additional knowledge*; menambah instruksi tugas akan mengubah prompt dan belum dilakukan.
3. **Rumus korelasi dan ambang** ">" vs "≥": lihat `REFERENCE.md` bagian 3.
4. **Pola grep OneDrive** `OneDrive|OneDrive\.exe` disimpulkan dari teks paper yang terpotong (cocok 6/6 dengan GT).
5. **Kata kunci S2 literal-bracket** adalah operasionalisasi penelitian, dijalankan berdampingan dengan metode regex apa adanya (`src/keywords.py`).

## Keterbatasan LIM-01: blok korelasi pada prompt P2 hampir selalu kosong

Blok `CORRELATIONS` pada P2 hanya memuat pasangan yang **kedua event-nya ada di evidence digest** (`src/09_prompts.py`, `correlation_block`). Evidence hanya 0,05%–0,9% dari event kanonik, sehingga pada 288 laporan: 21 dari 24 unit tanpa pasangan, dan total 5 pasangan (4 aturan pakar) sampai ke LLM. Skor korelasi dihitung benar (stage 07; pemetaan lewat `row_hash` memberi top-5 identik pada 24 dari 24 unit), tetapi hampir tidak memengaruhi prompt.

Akibatnya, selisih P2 terhadap P1 pada sebagian besar unit tidak dapat ditafsirkan sebagai efek korelasi ORD2I. Alur ORD2I tetap terimplementasi dan terverifikasi. Tidak ada pasangan tambahan yang dibuat secara artifisial.

## Validasi laporan dan pemetaan aturan pakar

- **Validasi laporan.** Status `OK` pada stage 11 berarti **respons diterima dan tidak kosong**, bukan "laporan valid". Respons kosong, whitespace, atau `null` menjadi `GAGAL_RESPON_KOSONG`. Validitas laporan dinilai terpisah (`src/report_validation.py`; keluaran `report_validity.csv` dari stage 12) pada empat tingkat: transport, keberadaan respons, struktur, dan ID evidence. Metrik M0–M8 dan subset `pure` tidak bergantung pada status ini.
- **Pemetaan aturan pakar.** Event aturan pakar R1 dipetakan lewat `row_hash` ke IRI kanonik unit (`digest.ek_to_unit_canonical`), sehingga pasangan yang sama dikenali di tingkat unit.
