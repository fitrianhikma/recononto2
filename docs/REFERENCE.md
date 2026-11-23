# Referensi V1 (gabungan)

Satu berkas, empat bagian, digabung dari `EVALUATION_METRICS.md`, `SIET_ALIGNMENT.md`, `CORRELATION_VERIFICATION.md`, dan `CHANGES_FROM_OLD.md`
saat penyederhanaan struktur folder (lihat `METHODOLOGY.md` untuk keputusan metodologi, bukan struktur berkas). Tidak ada isi yang dihapus,
hanya disusun ulang sebagai satu dokumen; rujukan nama berkas kode di dalamnya diperbarui ke nama baru (lihat Bagian 4).

1. [Metrik evaluasi](#1-metrik-evaluasi)
2. [Keselarasan dengan paper SIET](#2-keselarasan-dengan-paper-siet-dan-perbedaan-yang-masih-ada)
3. [Verifikasi rumus korelasi terhadap Chabot et al. (2015)](#3-verifikasi-rumus-korelasi-terhadap-chabot-et-al-2015)
4. [Perubahan terhadap kode lama (pemetaan berkas)](#4-perubahan-v1-terhadap-kode-lama-03_old_code)

> **V2:** satu bug teknis Stage 09 (ringkasan korelasi P2 untuk unit berkas isi-identik scenario3) ditemukan dan
> diperbaiki setelah audit data PENUH (bukan sampel) - lihat `docs/CHANGELOG_V2.md`. Tidak mengubah apa pun di
> bagian 1–4 dokumen ini (rumus korelasi, metrik, keselarasan SIET semuanya tetap seperti semula); angka
> "23 set prompt / 276 panggilan" di `METHODOLOGY.md` kini terverifikasi ulang terhadap data penuh.

---

## 1. Metrik evaluasi

Semua metrik dihitung di stage 12 (`src/12_evaluate.py`). Satu run per kondisi: seluruh angka deskriptif, tanpa uji signifikansi.

### 1.1 M0–M8 (lama, tidak diubah)

Dihitung oleh `report_metrics.evaluate_run`, yang identik dengan `eval/08_evaluate_reports.py` lama (diverifikasi dengan `diff`; hanya driver yang dipindah). Rumus, normalisasi, pembacaan judul, sitasi, dan pemetaan GT → rowHash (D24) sama. Definisi lengkap: `docs/legacy/DECISIONS.md` D23–D31 dan `docs/legacy/LIMITATIONS.md`.

Konsekuensi unit=task: setiap unit punya tepat satu tugas, sehingga `m5_recall_*` per unit bernilai 0 atau 1. Rata-ratanya atas unit = proporsi tugas yang tercakup, setara dengan M5 lama per skenario.

### 1.2 Metrik tugas tambahan (kolom `t_*`, `tm_*`)

Notasi per unit: butir GT unik `g` dengan himpunan rowHash `H_g` (pemetaan lama), multiplisitas `m_g`; bukti digest `E`; ID sah yang dikutip laporan `C` (cara M1); ID yang "disebut" `C'` (cara M3b: dikutip atau waktunya muncul).

| Kolom | Definisi |
|---|---|
| `t_gt_items_raw`, `t_gt_items_unique` | jumlah butir GT mentah dan unik (identitas di bawah) |
| `t_gt_unique_in_digest` | butir unik yang rowHash-nya ada di digest (batas atas recall yang mungkin) |
| `t_recall` | \|{g : H_g ∩ hash(C) ≠ ∅}\| / jumlah butir unik |
| `t_recall_weighted` | sama, berbobot m_g (informasi multiplisitas) |
| `t_recall_conditional` | dibagi butir unik yang ada di digest |
| `t_recall_mention` | memakai C' |
| `t_precision` | \|{c ∈ C : hash(c) ∈ himpunan relevan}\| / \|C\|; kosong bila laporan tidak mengutip apa pun |
| `t_f1` | rata-rata harmonik `t_precision` dan `t_recall` |
| `tm_*` (S1) | recall terhadap GT `multiple` berkas yang sama |

**Identitas butir (semantik himpunan, keputusan (c)):**
- S1: (tipe, `date_time_min` sampai detik, `evidence_source` dengan spasi diringkas dan deret backslash dipadatkan).
- S2: (`datetime` sampai mikrodetik, `message` dinormalisasi sama).
- S3: baris CSV utuh.

**Himpunan relevan untuk presisi:**
- S1: GT `multiple` berkas yang sama. **Presisi S1 adalah batas bawah**: GT hanya mencakup 8 jenis event tingkat tinggi dftpl, sehingga event valid di luar jenis itu dihitung bukan-GT.
- S2/S3: GT tugas itu. GT lengkap untuk aturan atau kata kuncinya.

**Unit=scenario:** butir GT semua tugas skenario digabung. Presisi dihitung terhadap gabungannya.

### 1.3 BLEU dan ROUGE (hanya S1)

- **Referensi:** baris teks unik dari GT `single` tugas unit, satu baris `HH:MM:SS <type>: <description>`, urut waktu lalu tipe. Kolom `evidence_source`, `supporting`, `plugin`, `files`, `keys` tidak dipakai karena bukan bahasa laporan. Deduplikasi memakai teks baris tersebut (mengabaikan huruf besar/kecil dan spasi), bukan identitas butir P/R/F1, sehingga butir yang hanya berbeda `evidence_source` menjadi satu baris.
- **Gerbang validitas:** `reference_valid = 1` bila ada ≥ 1 butir dan ≥ `min_reference_tokens` (5) token. Jika tidak, semua skor kosong.
- **Hipotesis:** laporan utuh setelah membuang sitasi `[Exx]` dan judul bagian (aturan judul M0). Varian `tl_*` hanya memakai bagian TIMELINE.
- **Tokenisasi:** huruf kecil; token = `HH:MM:SS` utuh atau deret alfanumerik yang boleh disambung `.`, `_`, `-` (mis. `firefox.exe`).
- **BLEU** (Papineni et al., 2002): BLEU-4 kalimat, bobot sama, presisi n-gram terpotong, brevity penalty `exp(1 − r/c)` bila c ≤ r.
  - `bleu`: tanpa smoothing (satu presisi nol → 0).
  - `bleu_smooth1`: Chen & Cherry method1 (ε = 0,1), setara `nltk SmoothingFunction().method1`.
- **ROUGE** (Lin, 2004):
  - `rouge1_f`, `rouge2_f`: F1 tumpang-tindih n-gram terpotong.
  - `rougeL_f`: F1 LCS atas seluruh teks (setara `rougeL`, bukan `rougeLsum`). Tanpa stemming.
- **Mean** (`mean_bleu_rouge`) = (BLEU + ROUGE-1 + ROUGE-2 + ROUGE-L)/4, sesuai kolom Mean Tabel 4 SIET (diverifikasi aritmetis: 0,0657 + 0,3892 + 0,1463 + 0,2177 = 0,8189, dan 0,8189/4 = 0,2047).
- **Pembanding pustaka** (`lib_*`): diisi bila `nltk` / `rouge-score` terpasang. nltk memakai token yang sama. rouge-score memakai tokenizer bawaannya (memecah `00:34:59` dan `firefox.exe`), sehingga selisih terhadap `rouge*_f` bisa mencapai sekitar 0,15 pada data S1 nyata; dengan tokenizer yang sama, selisihnya nol.
- **Panjang:** `ref_tokens` dan `hyp_tokens` dicatat karena referensi beberapa tugas panjang (mis. `4-open-mozilla-org`: 47 baris unik, 329 token), sedangkan laporan dibatasi 220 kata. Recall leksikal pada tugas seperti itu terbatas oleh desain.

### 1.4 Validitas pengambilan SPARQL (stage 06, tanpa LLM)

Precision/recall lama ditambah F1, per tugas dan per metode:
- **S2:** regex as-is (Q13), literal (Q14), struktur provider+EventID (Q12), dan baru: regex literal-bracket (Q13).
- **S3:** literal nama berkas (Q14, lama), struktur dari GT (Q12, lama), dan baru: pola grep paper (Q17).

Identitas baris sama dengan kode lama. Unit S3 tanpa event berwaktu (exe, OneDrive) tetap dievaluasi penuh di sini.

### 1.5 Subset dan selisih

- Subset: `all`, `pure` (tidak terpotong dan bukan degenerate_echo; definisi lama), `paired` (unit yang P1, P2, P3 semuanya sah untuk model yang sama), dan `paired_pure`.
- Perbandingan strategi memakai `paired`.
- `summary_deltas.csv`: selisih P2−P1 dan P3−P1 per unit.

---

## 2. Keselarasan dengan paper SIET dan perbedaan yang masih ada

Sumber: `01_PAPERS/_SIET__Ontology_forensic_recon FINAL.pdf` (Nurulhikmah & Studiawan; §3.2–3.6, Tabel 1 dan 4).
Catatan identitas berkas: `main.pdf` **bukan** paper SIET. Isinya Studiawan, Breitinger & Scanlon (2025), *Towards a standardized methodology and dataset for evaluating LLM-based digital forensic timeline analysis* (FSI: Digital Investigation 54), yaitu paper dataset/protokol evaluasi. Teks paper SIET tidak memuat kata "SIET"; identitasnya mengikuti penamaan peneliti.

### 2.1 Pemetaan strategi prompting (diverifikasi dari teks SIET §3.6 dan catatan Tabel 4)

| Label V1 | SIET | Definisi SIET | Implementasi V1 |
|---|---|---|---|
| P1 | S1 Baseline ("no additional knowledge") | digest + templat keluaran terstruktur | aturan + EVIDENCE (digest); templat 4 bagian dari pipeline lama |
| P2 | S2 ORD2I-augmented ("with ORD2I context") | digest + top-5 hasil korelasi (skor, Δt, CorrEK, interpretasi kausal) dengan label sumber artefak | P1 + blok CORRELATIONS: top-5 pasangan (skor + komponen T/S/O, penanda aturan pakar R1, Δt, label parser tiap event) |
| P3 | S3 Few-shot ("few-shot template") | digest + satu laporan contoh lengkap beranotasi; model diminta meniru struktur, bukan menyalin | P1 + satu laporan contoh lengkap sintetis + instruksi "follow its structure ..., do not copy its names, times or facts" |

P1–P3 adalah label strategi, bukan skenario dataset. Di kode tidak ada nama S1/S2/S3 untuk strategi.

### 2.2 Perbedaan yang masih ada

| Aspek | SIET | V1 | Alasan / status |
|---|---|---|---|
| Bagian laporan P1 | executive summary / full timeline / key findings / conclusion | SUMMARY / TIMELINE / FINDINGS / LIMITATIONS, maks 220 kata, sitasi [Exx] | Dipertahankan dari pipeline lama agar M0–M8 tetap berlaku (keputusan (a)). |
| Interpretasi kausal di P2 | ada | **tidak ada** | Skor korelasi bukan bukti kausal (keputusan lama D9–D12). Narasi kausal otomatis tidak diturunkan dari data. |
| Anotasi pada contoh P3 | "annotated" | tanpa anotasi | Anotasi menambah kata dan berisiko disalin. Bentuk anotasi SIET tidak dijelaskan di paper. |
| Asal contoh P3 | tidak dijelaskan | sintetis, nama rekaan, ID [E90]–[E94] | Mencegah kebocoran fakta/ID; diperiksa otomatis di stage 09 dan diukur M6c. |
| Digest | 2.197 karakter, empat fase berlabel, satu untuk seluruh skenario 1 | aturan digest lama (≤ 3.800 karakter), otomatis, per tugas (unit=task) atau per skenario (unit=scenario) | Unit per tugas disetujui (keputusan (d)); aturan digest tidak diubah. |
| Rumus korelasi | `(T+S+O)/3 + CorrEK`, CorrEK 1,0/0,7, CorrT eksponensial, jendela 300/600 s | Chabot: rata-rata; EK → 1,0; CorrT = 1/Δt; R1 | Keputusan lama D9–D14; lihat Bagian 3. |
| Ground truth | satu laporan referensi manual untuk semua model | GT resmi Zenodo per tugas (`tasks.zip`) | Tidak ada GT buatan. |
| Metrik | BLEU, ROUGE-1/2/L, Mean | M0–M8 (lama) + P/R/F1 per tugas + BLEU/ROUGE-1/2/L + Mean (S1 saja) | S2/S3 tidak berbentuk ringkasan; BLEU/ROUGE tidak sebanding di sana. |
| Implementasi BLEU | tidak disebut (pustaka, smoothing, tokenisasi) | implementasi eksplisit; `bleu` tanpa smoothing (konsisten dengan nilai 0,0000 di Tabel 4 SIET, **disimpulkan, bukan dinyatakan paper**), `bleu_smooth1` method1, pembanding nltk/rouge-score bila terpasang | Lihat Bagian 1.3. |
| Model | 6 (tinyllama, qwen2.5 0.5B/1.5B, llama-3.1-8b, qwen-2.5-7b, qwen-2.5-72b) | 4 (qwen2.5 0.5B/1.5B lokal; llama-3.1-8b, qwen-2.5-7b cloud) | Keputusan peneliti; qwen-2.5-72b tidak dipakai (biaya). |
| Data | Skenario 1 saja, `all_events.csv` (31.878 event) | Skenario 1–3, berkas `timeline/events/*.csv` | Perluasan tesis. |
| Query | Q1–Q10 | Q01–Q10 (padanan langsung) + Q01b, Q11–Q17 | Lihat `queries/catalog.json` (kolom `siet`). |
| Pipeline | 5 skrip | 13 tahap (00–12) | Dipecah agar dapat dijalankan per tahap. |
| Klasifikasi event | 18 tipe, aturan substring | tabel rule v2 (44 rule) dari pipeline lama | Keputusan lama D5; tidak diubah. |
| Akhir sesi Skenario 1 | "UserLogon 00:48:26" | catatan lama: itu notifikasi Winlogon 811/812; akhir sesi = 4647 pada 00:48:27 | Temuan pipeline lama; belum diverifikasi ulang di V1. |

---

## 3. Verifikasi rumus korelasi terhadap Chabot et al. (2015)

Sumber: `01_PAPERS/paper utama.pdf` (Digital Investigation 15, 2015, 83–100), bagian *Timeline analysis*, Listing 3, Tabel 2, Tabel 4, dan bagian studi kasus.
Implementasi yang diperiksa: `src/correlation.py` (digabung dari `correlation_core.py` + `correlation_config.py` lama saat penyederhanaan struktur folder — **isi fungsi dan nilai konstanta identik byte-per-byte dengan kode lama**, tidak diubah di V1 maupun saat penggabungan ini; lihat Bagian 4).

**Kesimpulan: tidak ada rumus yang diubah.** Implementasi lama sesuai dengan teks Chabot pada butir inti (rata-rata tiga skor, aturan pakar menjadikan skor maksimal, contoh CorrS 0,5, nilai objek dekat 0,25). Ada dua ketidakcocokan antara teks dan tabel paper itu sendiri, satu perbedaan ambang ">" vs "≥", dan satu klaim di `DECISIONS.md` lama yang hanya benar sebagian. Semuanya dilaporkan di bawah; keputusan tetap pada peneliti.

| # | Aspek | Paper Chabot 2015 | Implementasi (lama = V1) | Status |
|---|---|---|---|---|
| 1 | Skor keseluruhan | Pers. (1) tercetak `Corr = CorrT + CorrS + CorrO`; teks: tiap skor 0–1 setelah normalisasi, "in this study, all scores are equivalently weighted", skor keseluruhan "the average of the three scores" | `(CorrT + CorrS + CorrO) / 3` | **Sesuai teks.** Pers. (1) tanpa pembagi tidak konsisten dengan kalimat "average" di halaman yang sama. |
| 2 | Aturan pakar | "If two events satisfy a certain given rule, the overall correlation score between them is maximal" | EK terpenuhi → skor = 1,0 | **Sesuai.** |
| 3 | CorrT | Hanya kualitatif: waktu sama → 1,0; makin dekat makin tinggi. Bentuk fungsi tidak diberikan | `min(1, 1/Δt detik)`, Δt = 0 → 1 | **Operasionalisasi.** Cocok dengan Tabel 2 untuk Δt kecil saja (lihat tabel uji di bawah). Klaim D12 lama "1/Δt cocok dengan Tabel 2" hanya benar sebagian. |
| 4 | CorrS | Dua event dengan proses sama tetapi pengguna berbeda → 0,5 | `|Se ∩ Sx| / max(|Se|, |Sx|)` → {chrome, A} vs {chrome, B} = 1/2 | **Sesuai contoh.** |
| 5 | CorrO | Objek sama dan objek "berdekatan" (hostname/path sama) menaikkan skor; nilai tidak disebut di teks | objek sama → rasio irisan; objek berbeda tetapi host/direktori sama → 0,25 | **0,25 dari Tabel 2** (kolom O baris 2–4); definisi "dekat" = operasionalisasi. |
| 6 | Ambang | Teks: "significant correlations (score > 0.5)" dua kali; tabel hasil: "Correlations (≥0.5)"; Gambar 6: tepi tebal ≥ 0,6 | `score ≥ 0,5` | **Ambiguitas di paper.** Implementasi memakai ≥ (sesuai tabel hasil). Pasangan bernilai tepat 0,5 ikut terhitung. |
| 7 | Aturan pakar yang dipakai | Dua contoh: (a) unduh executable → eksekusi file yang sama; (b) buat bookmark → kunjungi halaman itu lewat bookmark | Hanya R1: executable (basename) sama pada dua parser berbeda dalam ≤ 60 s | **Ekstensi penelitian** (D14 lama). Dua aturan Chabot tidak diimplementasikan karena tidak ada dukungan artefak di data Zenodo. |
| 8 | Bobot | Dapat diubah pengguna | dikunci (1,1,1); program menolak bila diubah | Pembangkitan kandidat lama hanya lengkap untuk bobot sama dan τ ≥ 0,5. |

### 3.1 Uji Tabel 2 Chabot dengan stempel waktu Listing 3

Waktu (Listing 3): E2 08:13:24, E3 08:13:27, E4 08:13:28, E5 08:14:12, E6 08:14:37, E7 08:14:47.

| Pasangan | Δt (s) | T di Tabel 2 | 1/Δt | (T+S+O)/3 dari baris tabel | Ov di Tabel 2 |
|---|---|---|---|---|---|
| E5–E4 | 44 | 0,01 | 0,023 | 0,503 (EK = 1 → 1,0) | 1,0 |
| E4–E3 | 1 | 1,0 | 1,0 | 0,75 | **1,0** |
| E2–E3 | 3 | 0,33 | 0,333 | 0,527 | **0,7** |
| E4–E2 | 4 | 0,24 | 0,25 | 0,497 | **0,66** |
| E5–E7 | 35 | 0,02 | 0,029 | 0,34 | **0,45** |
| E4–E6 | 69 | 0,0 | 0,014 | 0,333 | **0,45** |
| E3–E6 | 70 | 0,0 | 0,014 | 0,333 | **0,45** |

Temuan:
- **Kolom Ov Tabel 2 tidak dapat direproduksi dengan rata-rata yang dinyatakan teks** pada 6 dari 7 baris tanpa aturan pakar. Ini inkonsistensi internal paper, bukan kesalahan implementasi. Tidak ada rumus di teks yang menghasilkan kolom itu, sehingga implementasi tetap mengikuti teks.
- **CorrT = 1/Δt** cocok untuk Δt 1–4 s. Untuk Δt 35–70 s, nilai tabel lebih kecil dari 1/Δt, sehingga fungsi asli kemungkinan menurun lebih cepat (bentuknya tidak diberikan). Dengan τ = 0,5 dan bobot sama, kandidat lama hanya dibangkitkan untuk objek sama dalam Δt ≤ 2 s, subjek sama, atau R1. Perbedaan pada Δt besar hanya mengubah skor pasangan yang sudah jauh di bawah ambang.

### 3.2 Perbedaan dengan paper SIET (bukan dengan Chabot)

SIET §3.5 memakai `Corr = (CorrT + CorrS + CorrO)/3 + CorrEK`, dengan CorrEK 1,0/0,7, CorrT eksponensial `e^(−|Δt|/W)` dengan jendela 300/600 s, dan CorrS bertingkat 1,0/0,7/0,6/0,4/0,3. Pipeline lama (D9–D13) sengaja mengikuti Chabot, bukan SIET. V1 mempertahankannya. Mengganti ke rumus SIET adalah perubahan metodologi yang memerlukan persetujuan peneliti.

Untuk menghitung pasangan bertepatan 0,5 setelah stage 07:
`python3 -c "import csv;print(sum(1 for r in csv.DictReader(open('results/07_correlation/scenario1/pairs.csv')) if abs(float(r['score'])-0.5)<1e-9))"`

---

## 4. Perubahan V1 terhadap kode lama (`03_OLD_CODE`)

### 4.1 Pemetaan berkas (lama → V1, setelah penyederhanaan struktur folder)

| Lama (`03_OLD_CODE`) | V1 | Perubahan |
|---|---|---|
| `src/02_preprocess.py` baris 1–241 (pustaka) | `src/classifier.py` | **identik** (hanya docstring ditambah) |
| `src/02b_preprocess_events.py` | `src/02_preprocess.py` | import pustaka langsung, lokasi laporan |
| `src/03_build_rdf.py` | `src/03_build_rdf.py` | lokasi masukan laporan stage 02 |
| `src/03_validate_rdf.py` | `src/04_validate_rdf.py` | import builder langsung, lokasi keluaran `results/04_validate/` |
| `src/04_sparql_run.py` | `src/05_sparql.py` | + analisis query kosong (`queries/catalog.json`) + perbandingan jumlah baris lama |
| `src/04_eval_retrieval.py` | `src/06_retrieval_eval.py` | + metode S2 literal-bracket, + metode S3 pola paper (Q17), + F1 |
| `src/05_correlate.py` + `05_check_cases.py` | `src/07_correlate.py` (uji kasus digabung langsung ke berkas ini) | uji kasus dijalankan dalam stage 07 sejak awal V1; digabung ke dalam berkas yang sama (dulu `correlation_cases.py` terpisah) saat penyederhanaan folder — isi fungsi tidak diubah |
| `src/correlation_core.py` + `src/correlation_config.py` | `src/correlation.py` | **identik** (hanya digabung jadi satu berkas saat penyederhanaan folder; isi fungsi dan konstanta tidak diubah, lihat Bagian 3) |
| `src/06_build_digest.py` | `src/08_digest.py` (aturan di `src/digest.py`) | **aturan identik**; tambahan filter berkas sumber (unit=task) dan graf dibaca sekali; `digest_core.py` + `digest_config.py` lama digabung jadi `digest.py` saat penyederhanaan folder |
| `src/07_prompts.py` | `src/09_prompts.py` | P2 top-5 + label parser; P3 contoh lengkap; pemeriksaan kebocoran; per unit |
| `src/07_run_llm.py` | `src/10_models_check.py` + `src/11_run_llm.py` (klien di `src/llm.py`) | fungsi panggilan identik; driver baru: pemakaian ulang prompt identik, penjaga biaya cloud, snapshot harga; `llm_client.py` + `llm_config.py` lama digabung jadi `llm.py` saat penyederhanaan folder |
| `eval/08_evaluate_reports.py` | `src/report_metrics.py` + `src/extra_metrics.py` + `src/12_evaluate.py` | **M0–M8 identik**; driver baru; metrik tambahan sebagai kolom baru |
| `src/events_reader.py`, `rdf_nt.py`, `search_engines.py`, `evtx_fields.py`, `sparql_common.py` | sama (nama tidak berubah) | identik; `sparql_common`: + Q17 di daftar templat, + F1 |
| `run_pipeline.py`, `verify_all.py`, 40+ skrip `diagnostics/`, `tests/test_phase*.py` | `run.py`, `tools/check_legacy.py`, `tests/test_v1.py` | diganti; diagnostik fase lama tidak dibawa |
| `src/phase1_ingest.py`, bagian CLI `02_preprocess.py` | – | tidak dibawa (khusus `timeline.csv` penuh yang tidak dipakai) |

Penyederhanaan struktur folder (lihat juga `README.md`) mengganti nama berkas tahap dari `stageNN_nama.py` menjadi `NN_nama.py` (kosmetik, isi tidak berubah) dan menggabungkan tiga pasang modul konstanta+inti (`correlation_config`+`correlation_core` → `correlation.py`; `digest_config`+`digest_core` → `digest.py`; `llm_config`+`llm_client` → `llm.py`), serta memindahkan `correlation_cases.py` ke dalam `07_correlate.py`. Semua penggabungan ini hanya memindahkan kode dan memperbarui baris impor pemanggil; tidak ada fungsi, konstanta, atau nilai yang diubah (dibuktikan dengan `diff` isi fungsi sebelum/sesudah, lihat bagian bukti kesetaraan di bawah).

### 4.2 Bukti kesetaraan (diperiksa saat pembangunan V1, tanpa dataset penuh; diperiksa ulang saat penyederhanaan folder)

Kode lama dan V1 dijalankan pada **sampel kecil** yang sama (12 berkas × ±400 baris, termasuk berkas berheader menyatu dan berheader ganda). Hasil:
- SHA-256 identik untuk CSV terproses, `.nt`, dan `pairs.csv` di ketiga skenario.
- Vonis validasi RDF V0–V7 sama.
- `digest.txt`, `digest_evidence.json`, dan `P1.txt` (unit=scenario) identik.
- `report_metrics.py` identik dengan bagian fungsi evaluator lama (`diff`).

Pada dataset penuh, jalankan `python3 tools/check_legacy.py` setelah stage 02–08 (`--unit scenario`). Alat ini membandingkan dengan hash dan jumlah baris terverifikasi pipeline lama (`acceptance/legacy_expected.json`).

Saat penyederhanaan folder (penggabungan `correlation.py`/`digest.py`/`llm.py`, penggantian nama `NN_nama.py`, dan pemindahan `correlation_cases.py`), V1-sebelum-penyederhanaan dan V1-sesudah-penyederhanaan dijalankan ulang pada sampel kecil yang sama; hasilnya cocok.

### 4.3 Yang belum dapat diuji di lingkungan pembangunan

- **SPARQL (stage 05–06):** rdflib tidak dapat dipasang karena PyPI diblokir di sandbox. Logika stage 06 diuji dengan emulasi templat di Python, bukan rdflib.
- **Ollama dan OpenRouter sungguhan:** runner diuji dengan server Ollama tiruan lokal; tidak ada panggilan OpenRouter.
- **Dataset penuh:** tidak diproses, sesuai instruksi.
