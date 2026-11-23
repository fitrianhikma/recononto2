# Panduan eksekusi di VM Ubuntu (Simplified V3)

Semua perintah dari folder proyek. Setiap `python3 run.py ...` menulis log lengkap ke `logs/<waktu>_stageNN_*.log`. **Log itulah yang dikirim** untuk analisis.
V2 memperbaiki satu bug teknis di Stage 09 (ringkasan korelasi P2 untuk unit berkas isi-identik) - lihat
`docs/CHANGELOG_V2.md`. V3 memperbaiki visibilitas dan kestabilan orkestrasi Stage 11 saja (progres
real-time, heartbeat selama menunggu respons, isolasi error tak terduga per job) - **tanpa mengubah
metodologi, resume/skip, atau kriteria status apa pun** - lihat `docs/CHANGELOG_V3.md`. Seluruh alur,
nama tahap, dan perintah di bawah **sama seperti Simplified sebelumnya**; tidak ada argumen baru.

## Struktur folder (ringkas)

```
ord2i_pipeline_simplified_v3/
├── run.py                  # orkestrator: python3 run.py --stage NN[-MM] [--scenario ...] [-- <argumen skrip>]
├── config/pipeline.json    # pengaturan operasional (model, strategi, parameter prompt) - BUKAN parameter metodologi
├── src/NN_nama.py          # satu skrip per tahap (00-12), bisa dijalankan langsung: python3 src/NN_nama.py --scenario N
├── src/correlation.py      # rumus korelasi (Chabot et al. 2015) + kanonikalisasi event duplikat - TIDAK diubah di V2/V3
├── src/digest.py           # aturan digest (pengembangan tesis) - TIDAK diubah di V2/V3
├── src/llm.py              # klien Ollama/OpenRouter - TIDAK diubah di V3 (timeout/retry/payload sama)
├── src/11_run_llm.py       # Stage 11 - SATU-SATUNYA berkas kode yang diubah di V3 (progres/heartbeat, lihat CHANGELOG_V3)
├── prompts/templates/      # P1/P2/P3.txt, rules.txt, correlation_scale.txt, format_example.txt
├── rules/, queries/        # aturan klasifikasi event, kueri SPARQL Q01-Q16
├── cases/correlation_cases.json   # definisi uji kewajaran korelasi (stage 07)
├── data/                   # dataset (scenario1-3/events, tasks/) - TIDAK PERNAH ditulis oleh pipeline
├── results/                # seluruh keluaran tahap 00-12 (lihat "Lokasi hasil" di bawah)
├── logs/                   # satu .log per eksekusi run.py
├── tests/test_v1.py        # python3 -m unittest discover -s tests (termasuk uji khusus V3, Ollama tiruan)
└── docs/{METHODOLOGY,REFERENCE,RUN_GUIDE,CHANGELOG_V2,CHANGELOG_V3}.md
```

## 0. Persiapan (sekali)

```bash
sudo apt-get install -y python3-venv          # bila belum ada
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt               # rdflib==7.5.0 (wajib); nltk, rouge-score (opsional, pembanding metrik)
python3 tools/setup_data.py --zips /path/ke/02_DATASET   # mengekstrak 4 ZIP ke data/ + DATA_MANIFEST.json
python3 -m unittest discover -s tests -v      # tanpa jaringan; 47 fungsi uji terdaftar (test_v1.py 33, test_fixes.py 14)
python3 run.py --stage 00                     # cek lingkungan dan tata letak data
```

## 1. Tahap data (tanpa LLM, tanpa jaringan)

Jalankan satu per satu dan periksa keluarannya sebelum lanjut:

```bash
python3 run.py --stage 01                     # audit data + GT (hanya membaca): results/01_audit/audit_summary.md
python3 run.py --stage 02                     # preprocessing
python3 run.py --stage 03                     # RDF
python3 run.py --stage 04                     # validasi RDF
python3 run.py --stage 05                     # SPARQL Q01-Q16 (+ uji determinisme); periksa baris "kosong ..."
python3 run.py --stage 06                     # validitas pengambilan S2/S3 (P/R/F1)
python3 run.py --stage 07                     # korelasi + uji kasus regedit S2
python3 run.py --stage 08                     # digest unit=task
python3 run.py --stage 09                     # prompt unit=task; baris RINGKASAN = jumlah panggilan LLM pasti
```

- Satu skenario saja: tambahkan `--scenario 2`.
- Rentang sekaligus: `python3 run.py --stage 02-09`.
- Bukti refactoring (disarankan):

```bash
python3 run.py --stage 08 --unit scenario
python3 run.py --stage 09 --unit scenario
python3 tools/check_legacy.py                 # semua harus COCOK; kirim keluarannya bila ada BEDA
```

## 2. LLM lokal (Ollama)

```bash
ollama pull qwen2.5:0.5b && ollama pull qwen2.5:1.5b
python3 run.py --stage 10 -- --local --probe                                     # model terpasang + satu generasi kecil
python3 run.py --stage 11 -- --dry-run --backend ollama                           # rencana, ukuran prompt, PERINGATAN_KONTEKS
python3 run.py --stage 11 -- --backend ollama --model qwen2.5-0.5b --scenario 2 --limit 1   # pilot: 1 unit x 3 strategi
python3 run.py --stage 12                                                         # evaluasi pilot
python3 run.py --stage 11 -- --backend ollama                                     # semua unit lokal (dapat dihentikan dan dilanjutkan)
python3 run.py --stage 12
```

Satu kombinasi tertentu saja (satu model, satu skenario, satu unit): tambahkan `--model <tag> --scenario N --limit 1`
setelah memastikan unit yang diinginkan berada di urutan pertama untuk skenario itu di `prompts_index.json` (`--limit`
membatasi JUMLAH unit yang diproses pada run itu, bukan memilih unit tertentu secara langsung - belum ada flag
`--unit-id`/`--strategy` per Bagian 7C proposal V2 awal; **ini masih item yang belum dikerjakan**, lihat catatan
di akhir dokumen ini).

Run yang sudah sah (status `OK`, hash prompt cocok) dilewati otomatis saat diulang (`SKIP_SUDAH_SAH` di ringkasan
akhir). Hasil `GAGAL`/belum lengkap tetap bisa dijalankan ulang tanpa `--force`. Pakai `--force` untuk mengulang
paksa run yang sudah sah. Logika resume/skip ini **tidak diubah dari V2**; yang baru di V3 adalah baris log
per-job yang membuatnya terlihat langsung di terminal (lihat `docs/CHANGELOG_V3.md`):

```
rencana: 69 laporan (model x unit x strategi), 69 panggilan LLM berbeda (prompt identik dipakai ulang); unit=task
[1/69] RUNNING | qwen2.5-0.5b | scenario1 | 0-launch-edge | P1
[1/69] OK | qwen2.5-0.5b | scenario1 | 0-launch-edge | P1 | 42.17s in=812 out=256 finish=stop
[2/69] RUNNING | qwen2.5-0.5b | scenario1 | 0-launch-edge | P2
[2/69] [WAITING] [2/69] qwen2.5-0.5b | scenario1 | 0-launch-edge | P2 | elapsed=20s
[2/69] [WAITING] [2/69] qwen2.5-0.5b | scenario1 | 0-launch-edge | P2 | elapsed=40s
[2/69] OK | qwen2.5-0.5b | scenario1 | 0-launch-edge | P2 | 51.43s in=940 out=300 finish=stop
...
[37/69] SKIP — sudah berhasil dijalankan sebelumnya | qwen2.5-0.5b | scenario2 | reg-launch-prefetch | P1
...
ringkasan: {'OK': 66, 'SKIP_SUDAH_SAH': 3}
```

- `[i/N]` di awal setiap baris = nomor job saat ini dari total rencana - sehingga selalu terlihat model, skenario,
  task/unit, dan strategi (P1/P2/P3) mana yang sedang diproses, dan berapa banyak sisa yang belum dikerjakan.
- `[RUNNING]` dicetak tepat sebelum memanggil Ollama/OpenRouter untuk job itu.
- `[WAITING] ... elapsed=Ns` dicetak setiap 20 detik **selama** menunggu satu respons yang belum kembali - jadi
  proses yang terlihat diam cukup lama (respons LLM lokal bisa 50-300+ detik) tetap terlihat berjalan, bukan macet.
- `[i/N] SKIP — sudah berhasil dijalankan sebelumnya | ...` untuk kombinasi yang sudah punya hasil sah - **baris
  inilah yang membuktikan secara visual bahwa resume bekerja** saat run diulang setelah berhenti di tengah jalan.
- Bila ada error tak terduga pada satu job (bukan error LLM biasa, mis. bug/disk penuh), job itu dicatat sebagai
  `GAGAL_TAK_TERDUGA` ke `P#.failed.json` (tetap kompatibel dibaca Stage 12) dan **job-job lain tetap lanjut** -
  satu kegagalan tak terduga tidak lagi menghentikan seluruh sisa rencana.

### Bila Stage 11 berhenti di tengah jalan (listrik mati, SSH putus, Ctrl-C, dll.)

Jalankan ulang **perintah yang sama persis**. Setiap kombinasi (model, skenario, unit, strategi) yang sudah punya
hasil sah dari run sebelumnya otomatis dilewati (`[i/N] SKIP — sudah berhasil dijalankan sebelumnya`, tanpa
panggilan LLM baru); hanya kombinasi yang belum selesai yang diproses. Ini logika resume V1/V2 yang tidak diubah
- V3 hanya membuatnya terlihat. Menekan Ctrl-C secara sengaja juga aman: pesan
`DIHENTIKAN oleh pengguna (Ctrl-C). Progres yang sudah tersimpan tetap sah ...` dicetak, proses keluar dengan kode
130 (bukan traceback), dan perintah yang sama bisa dijalankan ulang kapan saja untuk melanjutkan.

### Mengevaluasi ulang hasil LLM yang SUDAH ADA (tanpa panggilan LLM baru)

Bila Anda sudah punya hasil `results/unit_task/11_llm/<model>/scenarioN/<unit>/P*.json` dari run sebelumnya dan
hanya ingin mengevaluasi ulang (mis. setelah jeda waktu, atau karena `results/unit_task/12_eval/` sebelumnya
dijalankan sebelum semua hasil selesai ditulis):

```bash
python3 src/12_evaluate.py --scenario all        # TIDAK memanggil LLM; hanya membaca ulang P*.json yang sudah ada
```

Ini tidak membuat panggilan baru - `12_evaluate.py` murni membaca ulang berkas `results/unit_task/11_llm/**/P*.json`
yang sudah ada di disk dan `results/unit_task/08_digest|09_prompts/`. Jalankan ini kapan pun Anda menambah hasil
LLM baru secara manual dan ingin melihatnya di `eval_report.md`/`metrics_long.csv`/`runs_wide.csv` terbaru.

## 3. LLM cloud (OpenRouter), setelah hasil lokal ditinjau dan biaya disetujui

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
- kunci tidak diset;
- snapshot lebih tua dari 7 hari;
- estimasi melebihi `cloud_guard.max_estimated_cost_usd` (`config/pipeline.json`, default 1 USD).

Provider OpenRouter tidak dikunci; provider per panggilan dicatat (`provider`).

## 4. Yang dikirim untuk analisis

- Semua berkas `logs/*.log` dari tahap yang dijalankan - mencatat perintah persis, waktu, dan ringkasan tiap tahap.
- `results/01_audit/audit_summary.md` - audit data & GT (termasuk kelompok berkas isi-identik yang dipakai perbaikan V2 #1).
- `results/unit_task/12_eval/eval_report.md`, `metrics_long.csv`, dan `runs_wide.csv` - hasil evaluasi LLM
  (M0-M8, retrieval P/R/F1, BLEU/ROUGE bila `reference_valid`). **Kirim `metrics_long.csv`/`runs_wide.csv`
  sepenuhnya**, bukan hanya `eval_report.md`, agar kolom BLEU/ROUGE per run bisa diperiksa satu per satu.
- `results/unit_task/12_eval/failures.csv` - daftar run yang gagal/tidak lengkap (kosong = tidak ada kegagalan).
- `results/legacy_check.json` - **HANYA bila berkas ini memang ada di disk Anda** (dihasilkan oleh
  `tools/check_legacy.py`, langkah verifikasi opsional di Bagian 1, bukan bagian wajib alur pipeline). Pada run
  Anda sebelumnya berkas ini **tidak ada** - jangan menganggapnya ada hanya karena pernah disebut di dokumen ini;
  cukup jalankan `python3 tools/check_legacy.py` dulu bila Anda memang ingin mengirimkannya.
- Bila diminta: berkas JSON laporan tahap terkait, mis. `results/04_validate/validation_scenarioN.json`,
  `results/05_sparql/scenarioN/sparql_report.json`, `results/06_retrieval/retrieval_scenarioN.json`,
  `results/07_correlation/scenarioN/correlation_report.json`, atau
  `results/unit_task/09_prompts/scenarioN/<unit>/prompts_report.json` (berguna khusus untuk memeriksa perbaikan
  V2 #1: bandingkan `scope_files_nominal` vs `correlation_block.scope_files_effective`).

## Lokasi hasil

| Tahap | Folder |
|---|---|
| 00–07 | `results/00_env` … `results/07_correlation` |
| 08–12 | `results/unit_task/` (utama) atau `results/unit_scenario/` |
| 10 | `results/10_models/` |

Dataset di `data/` tidak pernah ditulis oleh pipeline.

## Verifikasi khusus perbaikan V2 #1 (unit 4616)

```bash
python3 src/09_prompts.py --scenario 3 --unit task
diff results/unit_task/09_prompts/scenario3/4616-with-regex/P2.txt \
     results/unit_task/09_prompts/scenario3/4616-without-regex/P2.txt     # harus KOSONG (identik) setelah V2
grep "4616" logs/<waktu>_stage09_*.log   # baris "prompt identik ...: [['4616-with-regex', '4616-without-regex']]"
python3 -m unittest tests.test_v1.TestDuplicateContentGroups -v           # 6 uji khusus perbaikan ini
```

## Item dari permintaan V2/V3 yang BELUM dikerjakan

Disebut secara jujur, bukan disembunyikan.

1. **Tampilan progres real-time Stage 11** - ✅ selesai di V3 (`[i/N] RUNNING/[WAITING]/[SKIP]/status` per job,
   lihat Bagian 2 di atas dan `docs/CHANGELOG_V3.md`). Dicoret dari daftar ini karena sudah dikerjakan.
2. **Flag `--unit-id`/`--strategy` untuk memilih satu kombinasi persis** - `--unit-id` sudah ada untuk Stage 08, 11, dan 12 (bersama `--variant`, lihat `docs/CHANGELOG_R1FIX.md`). `--strategy` belum ada.
3. **Verifikasi BLEU/ROUGE dengan keluaran S1 nyata** - ✅ selesai pada 84 run S1; satu koreksi deduplikasi referensi
   diterapkan. Untuk mengevaluasi ulang tanpa memanggil LLM:
   `python3 run.py --stage 12 --scenario all`.

Beri tahu saya bila item-item ini ingin dikerjakan di iterasi selanjutnya.

## Catatan tambahan (2026-11-04)

- **Gunakan `.venv`.** Stage 12 membaca `nltk` dan `rouge_score` bila terpasang. Dengan `python3` sistem yang tidak memilikinya, kolom `lib_*` pada `runs_wide.csv` kosong. `run.py` memakai `sys.executable`, jadi aktifkan venv sebelum menjalankan.
- **Menjalankan ulang sebagian ke folder varian.** `--variant NAMA` (Stage 08, 09, 11, 12) menulis ke `results/unit_task__NAMA` tanpa menyentuh baseline; `--unit-id ID` (Stage 08, 11, 12) membatasi ke satu unit dan wajib disertai `--variant`. Contoh dan prosedur ada di `docs/FINAL_REFACTOR_AND_FIX_REPORT.md` dan `docs/CHANGELOG_R1FIX.md`.
- **Agregat Stage 12 tidak dapat digabung dari hasil satu unit.** `summary_overall.csv`, `summary_by_scenario.csv`, dan `eval_report.md` harus dihitung ulang dari seluruh laporan. Cara yang dipakai saat promosi `r1fix` dijelaskan di `docs/CHANGELOG_R1FIX.md`.
