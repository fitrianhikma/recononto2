# Keputusan metodologis

Label: **literatur** = mengikuti definisi sumber yang dirujuk; **operasionalisasi penelitian** = keputusan implementasi atau penelitian ini (bukan definisi sumber). Skor korelasi bukan probabilitas dan bukan bukti kausal.

Keputusan dikelompokkan menurut tahap pipeline: data dan representasi, korelasi, digest dan prompt, pelaksanaan LLM, dan evaluasi.

## A. Data dan representasi

| # | Keputusan | Label | Alasan |
|---|---|---|---|
| D1 | Input resmi per skenario = gabungan `timeline/events/*.csv` Zenodo (DOI 10.5281/zenodo.15493424); ground truth = `tasks.zip` resmi. Tanpa filter buatan, tanpa dedup, tanpa ground truth buatan | operasionalisasi penelitian | Mengikuti protokol dataset; ground truth buatan sendiri tidak dapat dipertanggungjawabkan |
| D2 | Satu baris berkas = satu individu `Event`; duplikat tidak dihapus, tiap event diberi `hasRowHash` (SHA-1 delapan kolom mentah) | operasionalisasi penelitian | Duplikat (S1 8.790, S2 3.617, S3 4.011) dikelompokkan secara eksplisit, bukan dibuang diam-diam |
| D3 | **Event kanonik** = satu per `hasRowHash` unik yang punya `hasTimestamp` (kemunculan pertama menurut urutan IRI); baris tanpa waktu valid hanya dihitung | operasionalisasi penelitian | Korelasi dan digest bekerja pada event berwaktu; angka kanonik 23.088 / 10.390 / 3.992 |
| D4 | **Subjek ketat**: hanya bila data menyatakan akun (EVTX 4624/4625/4647, BAM); kepemilikan lewat path `\Users\x\` bukan subjek | operasionalisasi penelitian | Menghindari subjek yang disimpulkan; konsekuensinya CorrS hampir tak berperan (2–3 akun) |
| D5 | Klasifikasi event memakai tabel rule v2: 36 rule dasar (`event_rules.csv`) ditambah 8 rule berdasar dokumentasi dataset (`event_rules_v2.csv`, 44 rule); tipe `FileMetadata` untuk `pe` dan `olecf/*` | operasionalisasi penelitian | Di S3 `Unclassified` turun dari 36% ke praktis nol kecuali `usnjrnl` |
| D6 | Parameter pencarian dipetakan per mesin berdasarkan hostname (google/bing/duckduckgo/ecosia: `q`; yahoo: `p`; yandex: `text`; baidu: `wd`) | operasionalisasi penelitian | URL pengalihan Bing (`/ck/a`, parameter `p` berisi hash) tidak boleh terbaca sebagai pencarian; S1 memiliki 6 baris `WebSearch` |
| D7 | `app_name` untuk winevtx (provider `Microsoft-Windows-Shell-Core`, Event ID 9707) = `Strings[0]` sampai dan termasuk `.exe` (huruf asli, path penuh bila ada; tanda kutip dan argumen dibuang). Pola tidak cocok → kosong (mis. nomor versi). Terukur: S1 8 dari 10 baris 9707 terisi, S2 2 dari 2, S3 0. Pembangun RDF hanya membuat `ExeFile` untuk AppExecution/AppPresence, sehingga nama proses ini tidak tampil di RDF | operasionalisasi penelitian | Mengisi nama proses yang kosong tanpa menebak |
| D8 | ORD2I sebagai **dasar konseptual**; namespace implementasi `https://example.org/thesis-ord2i#` bukan IRI resmi dan bukan klaim ontologi baru. Lapisan: Common KL, Specialised KL, Traceability KL | literatur (konsep) + operasionalisasi (IRI/kelas implementasi) | Chabot et al. (2015) |
| D9 | Satu graf N-Triples per skenario, tidak pernah digabung | operasionalisasi penelitian | Pemisahan skenario diverifikasi (V7) |
| D10 | Event tanpa timestamp valid tetap `Event` tanpa `xsd:dateTime` (string mentah + status) | operasionalisasi penelitian | S3: 3.992 `zero_date` + 8 `filetime_zero` |

## B. Korelasi

| # | Keputusan | Label | Alasan |
|---|---|---|---|
| D11 | Skor korelasi = **rata-rata** CorrT, CorrS, CorrO berbobot sama | literatur (Chabot 2015) | Sesuai teks Chabot |
| D12 | Bila aturan pakar (EK) terpenuhi, skor = **1,0** | literatur (Chabot 2015) | Sesuai teks Chabot |
| D13 | Ambang **τ = 0,5**, tidak boleh lebih rendah (kandidat tidak lagi lengkap) | literatur (Chabot 2015) untuk nilai; operasionalisasi bila diubah | Program menolak berjalan bila τ < 0,5 atau bobot diubah |
| D14 | **CorrT = 1/Δt detik** (Δt = 0 → 1; dibatasi 1) | operasionalisasi penelitian | Bentuk fungsi tidak diberikan di teks Chabot (2015); 1/Δt cocok untuk Δt kecil pada Tabel 2 (lihat `REFERENCE.md` bagian 3.1) |
| D15 | CorrS = \|Se ∩ Sx\| / max(\|Se\|,\|Sx\|); CorrO = 1 objek sama, **0,25** objek berbeda tetapi hostname/direktori sama, selain itu 0 | literatur (nilai 0,25 dari Tabel 2) + operasionalisasi (definisi "dekat") | |
| D16 | **R1** = dua event berparser berbeda memuat executable bernama sama (basename huruf kecil) dalam ≤ 60 detik → EK. Ekstensi penelitian, bukan aturan Chabot | operasionalisasi penelitian | Dua aturan contoh Chabot tidak punya dukungan data di Zenodo |
| D17 | Pasangan *restating* (objek sama dan timestamp sama) dikeluarkan dari keluaran, tetap dihitung | operasionalisasi penelitian | Artefak MACB satu berkas |
| D18 | Pembangkitan kandidat: (A) objek sama dan Δt ≤ 2 s, (B) berbagi subjek, (C) pasangan R1; lengkap untuk τ ≥ 0,5 dan bobot sama | operasionalisasi penelitian | Menghindari O(n²) |
| D19 | Evaluasi SPARQL = validitas pengambilan terhadap ground truth resmi (S2 keyword-analysis, S3 grep: precision/recall/F1) | operasionalisasi penelitian | |
| D20 | Evaluasi korelasi = studi kasus + sensitivitas + ablasi; bukan precision/recall | literatur (praktik Chabot 2015) | Tidak ada ground truth korelasi |

## C. Digest dan prompt

| # | Keputusan | Label | Alasan |
|---|---|---|---|
| D21 | **Digest**: event kanonik; kelas massal (> 2%) hanya diringkas; pengisian menurut bobot tipe (`rules/digest_weights.csv`, dengan alasan) lalu jumlah menaik; maks 3 baris per tipe; (tipe, label) identik dikolaps `(xN)`; event R1 dari `pairs.csv` selalu masuk (maks 6); anggaran 3.800 karakter, bila lebih buang bobot terendah dulu dan laporkan | operasionalisasi penelitian | Aturan dan bobot dibekukan sebelum mengukur cakupan ground truth |
| D22 | Label digest UserLogon/UserLogonFailed memuat `logon_type=N` bila `hasLogonType` ada. Butir berlabel kosong tidak diitemkan dan jumlahnya tetap di "Not itemised (counts)" (tipe berbobot yang semua labelnya kosong ikut terdaftar). Kalimat korelasi memakai jumlah eksak ("N of M pairs scored >= 0.5 are the same object within 2 s; K by expert rule") | operasionalisasi penelitian | Label yang jelas dan jumlah yang tidak dibulatkan |
| D23 | **Prompt**: P1 = aturan + evidence; P2 = P1 + blok CORRELATIONS dari `pairs.csv` (top-5, tidak dihitung ulang); P3 = P1 + satu laporan contoh lengkap sintetis tanpa istilah dari skenario mana pun | operasionalisasi penelitian | P2 − P1 mengisolasi efek informasi korelasi |
| D24 | **Templat prompt**: maksimum 220 kata, teks polos (tanpa markdown/tabel), empat bagian persis (SUMMARY ≤ 2 kalimat; TIMELINE ≤ 10 butir, satu baris per butir, diawali sitasi `[Exx] HH:MM:SS`; FINDINGS ≤ 3; LIMITATIONS ≤ 2), "tulis dengan kata sendiri; jangan menyalin baris EVIDENCE". Templat tidak boleh memuat waktu atau istilah dari skenario mana pun (diuji otomatis) | operasionalisasi penelitian | Mengurangi pemotongan dan penyalinan baris digest |

## D. Pelaksanaan LLM

| # | Keputusan | Label | Alasan |
|---|---|---|---|
| D25 | **Runner**: temperatur 0, seed 42, `num_ctx` 4.096 untuk model lokal; run ditandai `GAGAL_KONTEKS` bila `prompt_eval_count + num_predict > num_ctx` | operasionalisasi penelitian | Ollama memotong prompt panjang secara diam-diam |
| D26 | **Anggaran keluaran**: `num_predict`/`max_tokens` = 900 (cloud dan lokal). Untuk model yang diberi bendera `premeasure` di `config/pipeline.json`: pra-ukur `num_predict=1`, `keep_alive=0` → `prompt_eval_count` nyata; `num_predict` efektif = min(900, `num_ctx` − `prompt_eval_count` − 32); bila < 350 → `GAGAL_KONTEKS` tanpa menghasilkan jawaban. `num_predict_effective`, `prompt_eval_count`, dan `finish_reason` dicatat per run. Digest tidak diperkecil untuk satu model | operasionalisasi penelitian | Run gagal tidak menghabiskan waktu CPU; keluaran tidak terpotong oleh batas buatan |
| D27 | **Provider OpenRouter tidak dikunci.** Runner tidak menetapkan `provider.order`/`allow_fallbacks`; provider yang melayani tiap panggilan dicatat di JSON run. Terukur pada 72 laporan per model: Llama-3.1-8B dilayani DeepInfra (48), Groq (23), dan Cloudflare (1); Qwen-2.5-7B seluruhnya oleh Phala (72) | operasionalisasi penelitian | Menghindari ketergantungan pada satu provider; konsekuensinya ada di `LIMITATIONS.md` |

## E. Evaluasi

| # | Keputusan | Label | Alasan |
|---|---|---|---|
| D28 | **Metrik inti** M0–M5 berbasis evidence dan ground truth resmi. Metrik berbasis teks (BLEU/ROUGE dan SBERT) hanya dihitung untuk S1, karena hanya S1 yang berbentuk ringkasan. Tanpa uji signifikansi (satu run deterministik per kondisi) | operasionalisasi penelitian | Ground truth resmi per tugas dipakai sebagai acuan |
| D29 | **Pemetaan ground truth → `rowHash`** (M5) memakai identitas baris sepenuh yang tersedia, hasilnya **himpunan** `rowHash`: S3 hash delapan kolom persis (378/378); S2 waktu + pesan penuh (setelah normalisasi escape backslash); S1 berkas + waktu + parser + `evidence_source` penuh. Tugas "tercakup" bila ≥ 1 baris GT-nya beririsan dengan bukti | operasionalisasi penelitian | Peta lokalisasi banyak-ke-satu. Terukur: baris GT ambigu (> 1 `rowHash`, beda hanya `timestamp_desc`) S1 93/279, S2 8/13, S3 0/378; tak terpetakan 0 |
| D30 | **Metrik tambahan** (kolom terpisah dari M0–M5): M6a terpotong (`finish_reason=length`); M6b rasio trigram kata laporan yang ada di prompt, `degenerate_echo` bila ≥ 0,70 atau memuat `RULES`/"evidence below"; M2n bilangan bulat ≥ 3 digit tak berdukung digest; M3b/M5b cakupan berbasis penyebutan (ID dikutip **atau** waktu `HH:MM:SS` bukti muncul persis); `citations_total`; ringkasan untuk (i) semua run sah dan (ii) subset murni (tidak terpotong dan bukan echo), keduanya dengan `n`; sel kosong = tidak terdefinisi, bukan nol; nilai mentah dilaporkan, tidak ada run yang dibuang | operasionalisasi penelitian | Sitasi saja tidak mengukur apa yang model gunakan; keluaran terpotong atau menyalin tidak boleh terbaca sebagai kemampuan |
| D31 | **Detektor judul M0** menerima judul berhiaskan di awal baris: `[TIMELINE]`, `### TIMELINE`, `**TIMELINE**`, `**TIMELINE:**`, `1. TIMELINE`, `1) TIMELINE:`, `- **TIMELINE:**`, `TIMELINE:`, tanpa membedakan huruf besar/kecil. Syarat bentuk judul: hiasan opsional + NAMA + (titik dua atau akhir baris); kata itu di tengah kalimat, atau kalimat yang hanya diawali kata itu ("Timeline shows that …"), **bukan** judul. `m0_structure` adalah versi longgar (empat judul ada); ditambah `m0_format_exact` (format persis `NAMA:` huruf besar tanpa hiasan) dan `m0_order_unique` (urutan benar, tiap judul sekali; menangkap bagian tertukar dan contoh format yang ditempel ulang di akhir) | operasionalisasi penelitian | Judul valid tetapi berhiaskan tidak boleh terbaca sebagai bagian yang hilang |
| D32 | **Metrik kepatuhan dan kualitas** (kolom tambahan): `m6c_template_leak` = jumlah waktu `HH:MM:SS` dari templat dan nama bertanda kutip pada contoh format yang muncul di laporan tetapi tidak ada di digest (istilah dibaca dari templat, bukan dari kode); `m6d_timeline_verbatim_ratio` = bagian baris TIMELINE yang identik dengan baris digest; `m4b_id_label_mismatch_rate` = sitasi yang menunjuk butir keliru (token berciri butir lain muncul, token butir yang disitir tidak; kalimat tanpa jangkar leksikal tidak dihitung); `m7_key_event_conclusion_recall` = tugas ground truth yang tercakup digest dan disebut di SUMMARY+FINDINGS (ID dikutip, token label berciri, atau kata tipe event dalam satu kalimat); `m8_*` = kepatuhan batas butir/kalimat/kata, teks polos, dan TIMELINE diawali ID | operasionalisasi penelitian | Metrik berbasis sitasi saja tidak menangkap penyalinan digest, nomor ID yang bergeser, peristiwa kunci yang hilang, dan pelanggaran batas butir |
