# Simplified -> Simplified V2: audit, perbaikan, dan bukti

Dasar: `ord2i_pipeline_simplified` (hasil penyederhanaan folder, sudah diuji Anda di VM dengan dataset penuh).
Status persetujuan: **disetujui oleh peneliti pada 2026-11-02** (lihat catatan audit V2 yang tidak disertakan di repositori ini
untuk audit lengkap; dokumen ini hanya mencatat perubahan kode yang benar-benar dilakukan setelah persetujuan).
**Tidak ada perubahan pada: rumus korelasi (`correlation.py`), kanonikalisasi event duplikat
(`correlation.load_events`), aturan digest (`digest.py`), skema RDF, SPARQL, ground truth, atau desain evaluasi.**

## 1. Perbaikan: ringkasan korelasi P2 untuk unit berkas isi-identik (scenario3: 4616-with-regex / 4616-without-regex)

### 1.1 Akar masalah (dikonfirmasi dengan bukti nyata, bukan hipotesis)

`correlation.py::load_events()` mengkanonikalisasi event dengan `hasRowHash` sama (baris CSV identik persis, lintas
berkas) menjadi **satu** event yang dipertahankan di graf korelasi (`by_hash.setdefault(h, iri)` - hanya kemunculan
IRI pertama menurut urutan string yang disimpan). Ini desain yang baik dan disengaja: mencegah penggandaan skor
korelasi akibat catatan yang "direstating" lewat dua berkas sumber identik. Dilaporkan jujur lewat
`duplicate_copies_excluded` di `correlation_report.json`.

Konsekuensinya (dibuktikan langsung dari `pairs.csv` hasil run nyata Anda, scenario3): KESELURUHAN 384 pasangan
yang melibatkan "4616" tercatat dengan IRI berlabel `4616-with-regex` saja - **nol** baris berlabel
`4616-without-regex` (diverifikasi: `grep -c "4616-without-regex" pairs.csv` = 0). Event-event unit
`4616-without-regex` **disingkirkan total** dari pembentukan pasangan, bukan dipindah IRI-nya - digest/evidence
unit `4616-without-regex` sendiri (dibangun langsung dari RDF per-berkas di Stage 08, independen dari
kanonikalisasi Stage 07) tetap memuat IRI miliknya sendiri (`.../4616-without-regex/00500`, dst.) secara utuh.

`09_prompts.py::correlation_block()` menghitung kalimat ringkasan P2 ("`X of Y pairs scored >= tau ...`") dengan
memfilter `pairs.csv` berdasarkan nama berkas **nominal** unit. Karena tidak ada satu baris pun di `pairs.csv`
yang berlabel `4616-without-regex`, filter ini selalu menghasilkan himpunan kosong untuk unit itu -> "0 of 0
pairs" - padahal bukti (digest) unit ini **identik** dengan `4616-with-regex` yang benar-benar punya 384 pasangan
(377 di antaranya objek sama). Akibat kedua: hash P2 kedua unit berbeda (2717 vs 2713 karakter) sehingga dedup
pemanggilan LLM berbasis SHA-256 prompt gagal untuk pasangan ini (hanya di P2; P1/P3 sudah identik sejak awal).

**Klasifikasi**: kesalahan teknis implementasi Stage 09 (kesalahan yang murni berkaitan dengan BAGAIMANA Stage 09
mengetahui "berkas mana yang menjadi sumber pasangan korelasi suatu unit"), bukan perubahan metodologi. Tidak
menyentuh rumus, bobot, atau aturan apa pun di `correlation.py`/`digest.py`.

### 1.2 Perbaikan yang dilakukan

Stage 01 (`01_audit_data.py`, tidak diubah) sudah mendeteksi kelompok berkas isi-identik per skenario dan
menuliskannya di `results/01_audit/audit_{scenario}.json` (`identical_content_groups`, mis.
`[["4616-with-regex.csv","4616-without-regex.csv"], ["OneDrive.csv","exe.csv"]]` untuk scenario3). Deteksi ini
sudah dipakai sebelumnya di `audit_summary.md` ("kelompok isi identik"); V2 ini pertama kalinya hasil deteksi itu
juga dipakai oleh Stage 09.

Dua fungsi baru di `src/09_prompts.py`:

- `load_duplicate_groups(scenario, root)`: membaca `results/01_audit/audit_{scenario}.json` (hanya dibaca, TIDAK
  menghitung ulang dengan metode independen). Jika berkas tidak ada/tidak terbaca: kembalikan `source="MISSING"`
  dan `groups=[]` - **dicatat sebagai peringatan** di `prompts_index.json` (`duplicate_content_groups_source`),
  TIDAK diam-diam dianggap berarti tidak ada duplikat.
- `expand_with_duplicate_groups(source_files, dup_groups)`: memperluas nama berkas nominal unit dengan anggota
  kelompok isi-identik yang relevan. Untuk unit yang bukan bagian dari kelompok apa pun, hasilnya **identik**
  dengan sebelumnya (tidak ada perubahan perilaku).

`run_scenario()` memanggil `load_duplicate_groups()` sekali per skenario, lalu `expand_with_duplicate_groups()` per
unit sebelum memanggil `build_prompts()`/`correlation_block()`. `correlation_block()` sendiri tidak berubah
logikanya (hanya field pelaporan baru `scope_files_effective`); `prompts_report.json` kini juga mencatat
`scope_files_nominal` (sebelum diperluas) agar keduanya bisa dibandingkan sebagai bukti.

### 1.3 Bukti sebelum/sesudah (dijalankan ulang terhadap `pairs.csv`/digest hasil run nyata Anda, bukan data sintetis)

| | SEBELUM (hasil run Anda) | SESUDAH (kode V2, data sama) |
|---|---|---|
| `4616-with-regex` P2 | 2717 char, `pairs_ge_tau_in_scope=384` | 2717 char, `pairs_ge_tau_in_scope=384` (**tidak berubah**) |
| `4616-without-regex` P2 | 2713 char, `pairs_ge_tau_in_scope=0` | **2717 char** (sama persis dgn with-regex), `pairs_ge_tau_in_scope=384` |
| P2 kedua unit | berbeda (hash berbeda) | **identik byte-per-byte** (`diff` kosong) |
| P1/P3 kedua unit, 22 unit lain di scenario1/2/3 | - | **tidak berubah sama sekali** (diverifikasi: 23/24 unit prompts_report.json byte-identik dgn hasil run Anda; hanya `4616-without-regex/P2` yang berbeda) |
| `unit=24, set prompt berbeda=?` (ringkasan stage 09, data penuh 3 skenario) | **24**, panggilan=24x3=72, total=288 | **23** (kembali seperti dokumentasi lama), panggilan=23x3=69, total=**276** |

Berkas bukti mentah (sebelum/sesudah, disertakan bersama pengiriman ini):
`evidence_before/{with-regex,without-regex}_{P2,prompts_report}.BEFORE.{txt,json}` dan
`evidence_after/{with-regex,without-regex}_{P2,prompts_report}.AFTER.{txt,json}`.

**Kesimpulan penting**: setelah diperbaiki, data PENUH (bukan sampel) menghasilkan **23 set prompt berbeda / 276
panggilan LLM** - sama persis dengan angka yang sudah terdokumentasi di `docs/METHODOLOGY.md`/`REFERENCE.md` sejak
pengujian sampel 500-baris dulu. Jadi dokumentasi lama itu **benar** untuk desain yang dimaksud; yang salah adalah
implementasi Stage 09 pada kasus berkas isi-identik, dan kesalahan itu baru kelihatan di data penuh (sampel 500
baris saya dulu tidak memuat baris yang memicu kasus ini). Tidak perlu lagi "menghitung ulang dan tidak
mengasumsikan 288" seperti pesan audit sebelumnya - 276 sudah diverifikasi langsung dari kode terhadap data nyata.

### 1.4 Pengujian

- `python3 -m unittest discover -s tests` -> **22/22 lulus** (16 lama + 6 baru khusus perbaikan ini, 1 dilewati
  karena `data/tasks` belum diekstrak di lingkungan pengujian ini - sama seperti sebelumnya).
- Uji baru (`TestDuplicateContentGroups`, di `tests/test_v1.py`): `expand_with_duplicate_groups()` (none-passthrough,
  unit tak terkait tak berubah, unit terkait diperluas), `load_duplicate_groups()` (berkas hilang dilaporkan bukan
  diasumsikan kosong; berkas ada dibaca benar), dan uji sintetis yang menirukan persis kasus 4616 - membuktikan
  bug SEBELUM perbaikan (`cb_a_broken`/`cb_b_broken` beda) dan perbaikannya SESUDAH (`cb_a_fixed`/`cb_b_fixed`
  sama) dalam satu uji yang sama.
- Dijalankan ulang terhadap **pairs.csv dan digest hasil run nyata Anda** (bukan sampel) untuk scenario 1, 2, 3
  sekaligus (`python3 src/09_prompts.py --scenario all --unit task`) - lihat tabel Bagian 1.3.
- `RegisteredApplications` (scenario3, bukan bagian kelompok isi-identik 4616) dan kedua unit `OneDrive`/`exe`
  (juga kelompok isi-identik, tapi status `NO_TIMED_EVENTS` sehingga dilewati Stage 09/11 sejak sebelum perbaikan
  ini) diverifikasi **tidak terdampak** sama sekali.

### 1.5 Yang TIDAK diuji ulang di sini (jujur dilaporkan)

Stage 11 (pemanggilan LLM nyata dengan prompt baru hasil perbaikan ini) **tidak dijalankan** - sesuai permintaan
Anda ("Tidak perlu menjalankan Stage 11 atau membuat panggilan LLM baru"). Prompt P2 baru untuk
`4616-without-regex` belum pernah dikirim ke model sungguhan; `prompt_sha256` barunya akan berbeda dari yang
tercatat di `run_log.jsonl` run Anda sebelumnya (yang hanya mencakup scenario1/2, tidak scenario3), sehingga tidak
ada run lama yang menjadi basi akibat perbaikan ini.

---

## 2. Dokumentasi diperbarui (angka 23/276, bukan perubahan kode pipeline)

`docs/METHODOLOGY.md` dan `docs/REFERENCE.md` yang menyebut "23 set prompt berbeda / 276 panggilan total" **tidak
diubah angkanya** - angka itu sudah benar dan sekarang terverifikasi ulang terhadap data penuh (Bagian 1.3).
Ditambahkan catatan singkat di kedua dokumen yang menjelaskan riwayat singkat: angka ini awalnya hanya diverifikasi
lewat sampel 500 baris; run data penuh Anda sempat menunjukkan 24/288 akibat bug Bagian 1; setelah perbaikan,
data penuh kembali menghasilkan 23/276 - lihat `CHANGELOG_V2.md` untuk detail dan bukti lengkap.

---

## 3. `ord2i_full_tanpa_env.zip` (kode historis SIET/konferensi) - hanya referensi, bukan basis V2

Diterima dan diekstrak: 5 skrip monolitik (`01_preprocess_all.py` .. `06_merge_results.py`) + beberapa varian LLM
(`05_llm_report_*`, `reevaluate_*`) + data contoh (`all_events.csv`, `scenario1_ord2i_full.ttl`,
`unified_evaluation_final.csv`, dll.) + README + dua tangkapan terminal. Sesuai instruksi Anda, arsip ini
**tidak** dijadikan basis kode dan **tidak** diikuti persis strukturnya; `03_OLD_CODE` dari sesi sebelumnya juga
tidak dipakai sebagai substitusi apa pun (sesuai permintaan). Dipakai hanya sebagai referensi pembanding
implementasi metodologi SIET bila diperlukan di pembahasan tesis; tidak ada perbandingan baris-demi-baris yang
dilakukan terhadap arsip ini pada V2 ini karena tidak ada temuan Simplified yang memerlukannya.

---

## 4. Ringkasan berkas yang berubah dari Simplified -> Simplified V2

| Berkas | Perubahan |
|---|---|
| `src/09_prompts.py` | + `load_duplicate_groups()`, + `expand_with_duplicate_groups()`; `run_scenario()` memanggil keduanya sebelum `build_prompts()`; `correlation_block()` field pelaporan baru (`scope_files_effective`, tanpa ubah logika penghitungan selain argumen yang diterimanya sekarang sudah diperluas oleh pemanggil); `prompts_report.json` kini juga mencatat `scope_files_nominal` |
| `tests/test_v1.py` | + `TestDuplicateContentGroups` (6 uji baru, lihat Bagian 1.4) |
| `docs/METHODOLOGY.md`, `docs/REFERENCE.md` | + catatan riwayat singkat (angka tidak berubah) |
| `docs/CHANGELOG_V2.md` | baru (dokumen ini) |
| `docs/RUN_GUIDE.md` | diperbarui/dilengkapi untuk V2 (lihat berkas itu) |

Tidak ada berkas lain yang disentuh. `correlation.py`, `digest.py`, `llm.py`, skema RDF/SPARQL, `rules/`,
`cases/correlation_cases.json`, `prompts/templates/`, dan seluruh ground truth di `data/tasks/` **tidak diubah**.
