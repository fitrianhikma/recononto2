# Referensi metode dan metrik

Dokumen ini menjelaskan cara pipeline mengevaluasi laporan LLM, dasar strategi prompting, dan verifikasi rumus korelasi. Keputusan metodologi ada di `METHODOLOGY.md`; cara menjalankan ada di `RUN_GUIDE.md`.

1. [Metrik evaluasi](#1-metrik-evaluasi)
2. [Dasar strategi prompting](#2-dasar-strategi-prompting)
3. [Verifikasi rumus korelasi terhadap Chabot et al. (2015)](#3-verifikasi-rumus-korelasi-terhadap-chabot-et-al-2015)

---

## 1. Metrik evaluasi

Semua metrik dihitung di stage 12 (`src/12_evaluate.py`). Satu run per kondisi: seluruh angka bersifat deskriptif, tanpa uji signifikansi.

### 1.1 Metrik inti M0–M8

Dihitung oleh `report_metrics.evaluate_run`. Metrik ini mencakup pembacaan judul bagian laporan, validitas sitasi `[Exx]`, dan pemetaan butir ground truth (GT) ke `rowHash`. Definisi lengkap ada di `DECISIONS.md` dan keterbatasannya di `LIMITATIONS.md`.

Pada unit=task, setiap unit hanya memiliki satu tugas, sehingga `m5_recall_*` per unit bernilai 0 atau 1. Rata-ratanya atas unit adalah proporsi tugas yang tercakup.

### 1.2 Metrik tugas tambahan (kolom `t_*`, `tm_*`)

Notasi per unit: butir GT unik `g` dengan himpunan rowHash `H_g` dan multiplisitas `m_g`; bukti digest `E`; ID sah yang dikutip laporan `C` (cara M1); ID yang "disebut" `C'` (cara M3b: dikutip atau waktunya muncul).

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

**Identitas butir (semantik himpunan):**
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
- **Mean** (`mean_bleu_rouge`) = (BLEU + ROUGE-1 + ROUGE-2 + ROUGE-L) / 4, mengikuti kolom Mean pada Tabel 4 SIET.
- **Pembanding pustaka** (`lib_*`): diisi bila `nltk` dan `rouge-score` terpasang. nltk memakai token yang sama. rouge-score memakai tokenizer bawaannya (memecah `00:34:59` dan `firefox.exe`), sehingga selisih terhadap `rouge*_f` bisa mencapai sekitar 0,15 pada data S1; dengan tokenizer yang sama, selisihnya nol.
- **Panjang:** `ref_tokens` dan `hyp_tokens` dicatat karena referensi beberapa tugas panjang (mis. `4-open-mozilla-org`: 47 baris unik, 329 token), sedangkan laporan dibatasi 220 kata. Recall leksikal pada tugas seperti itu terbatas oleh desain.

### 1.4 Validitas pengambilan SPARQL (stage 06, tanpa LLM)

Precision, recall, dan F1 dihitung per tugas dan per metode:
- **S2:** regex apa adanya (Q13), literal (Q14), struktur provider + EventID (Q12), dan regex literal-bracket (Q13).
- **S3:** literal nama berkas (Q14), struktur dari GT (Q12), dan pola grep dari paper dataset (Q17).

Unit S3 tanpa event berwaktu (exe, OneDrive) tetap dievaluasi penuh di sini.

### 1.5 Subset dan selisih

- Subset: `all`, `pure` (tidak terpotong dan bukan degenerate_echo), `paired` (unit yang P1, P2, P3 semuanya sah untuk model yang sama), dan `paired_pure`.
- Perbandingan strategi memakai `paired`.
- `summary_deltas.csv`: selisih P2−P1 dan P3−P1 per unit.

---

## 2. Dasar strategi prompting

Tiga strategi prompting (P1, P2, P3) mengikuti kerangka SIET (Nurulhikmah & Studiawan; §3.2–3.6, Tabel 1 dan 4). Dataset dan protokol evaluasi mengikuti Studiawan, Breitinger & Scanlon (2025), *Towards a standardized methodology and dataset for evaluating LLM-based digital forensic timeline analysis* (Forensic Science International: Digital Investigation 54).

### 2.1 Pemetaan strategi

| Label | Strategi SIET | Definisi | Implementasi |
|---|---|---|---|
| P1 | Baseline ("no additional knowledge") | digest + templat keluaran terstruktur | aturan + EVIDENCE (digest); templat laporan 4 bagian |
| P2 | ORD2I-augmented ("with ORD2I context") | digest + top-5 hasil korelasi dengan label sumber artefak | P1 + blok CORRELATIONS: top-5 pasangan (skor + komponen T/S/O, penanda aturan pakar R1, Δt, label parser tiap event) |
| P3 | Few-shot ("few-shot template") | digest + satu laporan contoh lengkap; model meniru struktur, bukan menyalin | P1 + satu laporan contoh lengkap sintetis + instruksi "follow its structure ..., do not copy its names, times or facts" |

P1–P3 adalah label strategi, bukan skenario dataset (S1–S3). Di kode, nama S1/S2/S3 hanya dipakai untuk skenario.

### 2.2 Catatan desain

- **Format laporan:** empat bagian (SUMMARY / TIMELINE / FINDINGS / LIMITATIONS), maksimal 220 kata, sitasi `[Exx]`. Format ini yang membuat metrik M0–M8 dapat dihitung.
- **Blok korelasi P2:** hanya memuat skor, komponen, Δt, dan label sumber. Tidak ada narasi kausal, karena skor korelasi bukan bukti kausal.
- **Contoh P3:** sintetis (nama rekaan, ID `[E90]`–`[E94]`) agar tidak membocorkan fakta atau ID dari data nyata. Kebocoran diperiksa otomatis di stage 09 dan diukur lewat M6c. Contoh tidak beranotasi, karena anotasi menambah kata dan berisiko disalin.
- **Ground truth:** GT resmi per tugas dari dataset Zenodo (`tasks.zip`). Tidak ada GT buatan.
- **Metrik S2/S3:** keluaran S2 dan S3 tidak berbentuk ringkasan, sehingga BLEU/ROUGE hanya dihitung untuk S1; S2 dan S3 dievaluasi dengan P/R/F1.
- **Query:** Q01–Q10 sepadan dengan Q1–Q10 pada SIET; Q01b dan Q11–Q17 adalah tambahan (lihat kolom `siet` di `queries/catalog.json`).

---

## 3. Verifikasi rumus korelasi terhadap Chabot et al. (2015)

Sumber: Chabot et al., *Digital Investigation* 15 (2015), 83–100, bagian *Timeline analysis*, Listing 3, Tabel 2, Tabel 4, dan studi kasus. Implementasi yang diperiksa: `src/correlation.py`.

**Kesimpulan:** implementasi sesuai dengan teks Chabot pada butir inti (rata-rata tiga skor, aturan pakar menjadikan skor maksimal, contoh CorrS 0,5, nilai objek dekat 0,25). Ada dua ketidakcocokan antara teks dan tabel paper itu sendiri, satu perbedaan ambang ">" vs "≥", dan beberapa operasionalisasi yang tidak dirinci paper. Semuanya dicatat di bawah.

| # | Aspek | Paper Chabot 2015 | Implementasi | Status |
|---|---|---|---|---|
| 1 | Skor keseluruhan | Pers. (1) tercetak `Corr = CorrT + CorrS + CorrO`; teks: tiap skor 0–1 setelah normalisasi, "in this study, all scores are equivalently weighted", skor keseluruhan "the average of the three scores" | `(CorrT + CorrS + CorrO) / 3` | **Sesuai teks.** Pers. (1) tanpa pembagi tidak konsisten dengan kalimat "average" di halaman yang sama. |
| 2 | Aturan pakar | "If two events satisfy a certain given rule, the overall correlation score between them is maximal" | EK terpenuhi → skor = 1,0 | **Sesuai.** |
| 3 | CorrT | Hanya kualitatif: waktu sama → 1,0; makin dekat makin tinggi. Bentuk fungsi tidak diberikan | `min(1, 1/Δt detik)`, Δt = 0 → 1 | **Operasionalisasi.** Cocok dengan Tabel 2 untuk Δt kecil saja (lihat 3.1). |
| 4 | CorrS | Dua event dengan proses sama tetapi pengguna berbeda → 0,5 | `\|Se ∩ Sx\| / max(\|Se\|, \|Sx\|)` → {chrome, A} vs {chrome, B} = 1/2 | **Sesuai contoh.** |
| 5 | CorrO | Objek sama dan objek "berdekatan" (hostname/path sama) menaikkan skor; nilai tidak disebut di teks | objek sama → rasio irisan; objek berbeda tetapi host/direktori sama → 0,25 | **0,25 dari Tabel 2** (kolom O baris 2–4); definisi "dekat" = operasionalisasi. |
| 6 | Ambang | Teks: "significant correlations (score > 0.5)" dua kali; tabel hasil: "Correlations (≥0.5)"; Gambar 6: tepi tebal ≥ 0,6 | `score ≥ 0,5` | **Ambiguitas di paper.** Implementasi memakai ≥ (sesuai tabel hasil). Pasangan bernilai tepat 0,5 ikut terhitung. |
| 7 | Aturan pakar yang dipakai | Dua contoh: (a) unduh executable → eksekusi file yang sama; (b) buat bookmark → kunjungi halaman itu lewat bookmark | Hanya R1: executable (basename) sama pada dua parser berbeda dalam ≤ 60 s | **Ekstensi penelitian.** Dua aturan Chabot tidak diimplementasikan karena tidak ada dukungan artefak di data Zenodo. |
| 8 | Bobot | Dapat diubah pengguna | dikunci (1,1,1); program menolak bila diubah | Pembangkitan kandidat hanya lengkap untuk bobot sama dan τ ≥ 0,5. |

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
- **Kolom Ov Tabel 2 tidak dapat direproduksi dengan rata-rata yang dinyatakan teks** pada 6 dari 7 baris tanpa aturan pakar. Ini inkonsistensi internal paper, bukan kesalahan implementasi. Tidak ada rumus di teks yang menghasilkan kolom itu, sehingga implementasi mengikuti teks.
- **CorrT = 1/Δt** cocok untuk Δt 1–4 s. Untuk Δt 35–70 s, nilai tabel lebih kecil dari 1/Δt, sehingga fungsi asli kemungkinan menurun lebih cepat (bentuknya tidak diberikan). Dengan τ = 0,5 dan bobot sama, kandidat hanya dibangkitkan untuk objek sama dalam Δt ≤ 2 s, subjek sama, atau R1. Perbedaan pada Δt besar hanya mengubah skor pasangan yang sudah jauh di bawah ambang.

Untuk menghitung pasangan bernilai tepat 0,5 setelah stage 07:

```bash
python3 -c "import csv;print(sum(1 for r in csv.DictReader(open('results/07_correlation/scenario1/pairs.csv')) if abs(float(r['score'])-0.5)<1e-9))"
```
