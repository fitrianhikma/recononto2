# Keterbatasan

## Data dan input

- Input adalah potongan ±2.000 baris per berkas `timeline/events`, bukan sesi utuh. S3 bukan sesi, dan 4.000 barisnya tidak bertanggal valid (`zero_date` 3.992, `filetime_zero` 8); baris itu hanya dihitung. Digest S3 menampilkan jam tanpa tanggal padahal rentang event berwaktu ±1 minggu (aturan label hanya `HH:MM:SS`; tanggal ada di baris Scope).
- Tiga cacat format berkas resmi ditangani pembaca di memori (header menyatu di S2; header ganda di S3 `OneDrive.csv` dan `exe.csv`; pemisah spasi di S1) dan dilaporkan, tidak diubah.
- Angka timeline penuh (±2,2 juta baris per skenario) di `acceptance/legacy_expected.json` tidak dapat diverifikasi ulang tanpa `timeline.csv` penuh; angka itu dicatat apa adanya.
- Kunci grep S3 diasumsikan dari nama berkas ground truth. Satu item ground truth S2 bertanggal tidak konsisten dengan berkas events (isi identik dan unik, waktu berbeda); ditangani sebagai tingkat terpisah berlabel.
- Ground truth S1 dan S2 tidak memuat `timestamp_desc`, sehingga baris kembar yang hanya beda itu tidak terbedakan (S1 93 dari 279 butir, S2 8 dari 13 butir memetakan ke > 1 `rowHash`); M5 memakai semantik himpunan.

## Representasi dan korelasi

- Subjek sangat sedikit (2–3 akun); CorrS hampir tidak berperan. Relasi objek (creates/removes/modifies/uses) belum dibedakan di RDF (hanya `hasObject`); `usnjrnl` hanya nama berkas (satu-satunya `Unclassified`).
- Hampir semua pasangan skor ≥ 0,5 adalah "objek sama dalam ≤ 2 detik" (artefak file system); korelasi pada data ini praktis berarti itu. Hanya pasangan R1 yang melewati 0,7 (3 di S1, 3 di S2, 0 di S3). Interval Allen, relasi *composes/causes*, dan aturan inferensi pengguna pada Chabot (2015) tidak diimplementasikan.
- Tidak ada ground truth korelasi; uji kasus (trio `regedit` S2) adalah uji kewajaran, bukan precision/recall. R1 adalah ekstensi penelitian, bukan aturan Chabot. Skor bukan probabilitas dan bukan bukti kausal.
- Nama proses pada baris 9707 (`app_name`) terisi di CSV, tetapi pembangun RDF tidak membuat objek untuk `ProcessCreate`, sehingga nama itu belum tampil di RDF, SPARQL, atau digest. Dua baris S1 9707 berisi nomor versi dan tetap kosong.

## Digest dan prompt

- Digest hanya ±30 baris dari puluhan ribu event, sehingga cakupan ground truth parsial **secara desain** (terukur: S1 7/14, S2 6/7, S3 2/5 tugas tercakup). Event dalam grup `(xN)` diwakili satu `rowHash` saja; baris GT yang bukan perwakilan grup dihitung tidak tercakup oleh M5.
- Blok korelasi pada P2 hampir selalu kosong: hanya pasangan yang kedua event-nya ada di evidence digest yang ikut (lihat LIM-01 di `METHODOLOGY.md`). Selisih P2 terhadap P1 pada sebagian besar unit tidak dapat ditafsirkan sebagai efek korelasi.
- Prompt tidak memuat pertanyaan tugas (kata kunci S2, pola grep S3). Model menulis laporan insiden umum dan dievaluasi lewat cakupan ground truth.
- **Token nyata vs perkiraan.** Anggaran digest dan peringatan `--dry-run` memakai karakter/4, sedangkan token nyata ≈ 1,55× perkiraan itu untuk Qwen (URL, GUID, path), sesuai `token_factor_estimate` di `config/pipeline.json`. Yang menentukan `GAGAL_KONTEKS` adalah `prompt_eval_count` nyata; run yang tidak muat ditandai gagal dan digest tidak diperkecil khusus untuk satu model.

## LLM dan eksekusi

- Model kecil (0,5B–1,5B) cenderung mengarang atau mengulang; itu temuan, bukan alasan mengubah prompt per model.
- **Model kecil menyalin dan jarang mengutip.** Skor "tak berdukung = 0" pada keluaran yang menyalin tidak berarti model jujur. Itu sebabnya ada M6b (`degenerate_echo`), M3b/M5b (penyebutan), dan subset murni; ini temuan penelitian.
- Temperatur 0 dan seed tidak menjamin determinisme penyedia OpenRouter; model atau penyedia dapat berubah antar-waktu (dicatat per run).
- **Provider OpenRouter tidak dikunci.** Model yang sama dapat dilayani provider berbeda antar-panggilan (Llama-3.1-8B: DeepInfra 48, Groq 23, Cloudflare 1 dari 72 laporan; Qwen-2.5-7B seluruhnya Phala). Temperatur 0 dan seed tidak menjamin hasil identik antar-provider (kuantisasi, implementasi seed). Provider tercatat per run (`provider`), tetapi variasi antar-provider tidak dapat dipisahkan dari variasi antar-strategi atau skenario pada Llama-8B tanpa mengulang dengan provider terkunci.
- Backend tercampur dengan ukuran model (model lokal 0,5B–1,5B, model cloud 7B–8B), sehingga perbandingan backend tidak dapat dipisahkan dari ukuran model.
- Satu run deterministik per kondisi: tanpa uji signifikansi; perbandingan model × strategi bersifat deskriptif.

## Evaluasi

- **Cakupan metrik bukan kualitas.** Cakupan bukti (M3/M3b) dan M5/M5b dapat naik karena laporan melanggar batas 10 butir TIMELINE atau menyalin baris digest. Baca bersama `m8_*`, `m6b`, dan `m6d`.
- M3b/M5b: dua bukti yang berwaktu sama ditandai "disebut" bersamaan oleh satu kemunculan waktu; ukuran ini lebih longgar daripada sitasi dan dilaporkan berdampingan, tidak menggantikannya. M6b memakai himpunan trigram kata (bukan multiset); ambang 0,70 adalah operasionalisasi.
- **`m7` adalah batas bawah konservatif** dan leksikal: parafrasa nama alat tidak dikreditkan (mis. "registry editor" untuk `regedit.exe`). Kata tipe event umum (user, file, app, web, page, …) tidak cukup sebagai syarat.
- `m4b` hanya menilai kalimat yang punya jangkar leksikal; sisanya tak tertentukan dan tidak dihitung. `m6c` hanya menangkap waktu templat dan nama bertanda kutip pada contoh format; frasa contoh lain ("Invented sample") tidak dihitung.
- **M0 hanya mengukur keberadaan judul** (dengan hiasan diterima); kepatuhan format dilaporkan terpisah (`m0_format_exact`, `m0_order_unique`, `m8_*`).
- BLEU/ROUGE hanya untuk S1; referensi beberapa tugas panjang (mis. 329 token) sedangkan laporan dibatasi 220 kata, sehingga recall leksikal pada tugas seperti itu terbatas oleh desain.
- Presisi S1 adalah batas bawah: GT `multiple` hanya mencakup 8 jenis event tingkat tinggi.
- Runner dan evaluator diuji dengan server Ollama tiruan dan laporan sintetis (unit test); pemanggilan model nyata tercatat pada log dan hasil eksperimen.
