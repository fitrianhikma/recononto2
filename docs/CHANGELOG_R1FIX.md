# Changelog R1FIX (2026-11-04)

Perubahan terbatas pada hasil unit `reg-launch-user-assist` (skenario 2). Tidak ada perubahan algoritma evaluasi, prompt, atau konfigurasi eksperimen yang dilakukan pada langkah promosi ini.

## Ringkasan
- **Perbaikan R1:** digest unit ini kini memuat `r1_items = 2` (sebelumnya 0); evidence 9 butir (sebelumnya 8). Digest 23 unit lain tidak berubah: 72 dari 72 berkas di `results/unit_task__r1fix_all/08_digest/` identik dengan baseline.
- **Kode:** opsi `--variant NAMA` (Stage 08, 09, 11, 12) dan `--unit-id ID` (Stage 08, 11, 12), serta `src/report_validation.py` (`report_validity.csv`, versi `validation_v2`). Rincian: `docs/FINAL_REFACTOR_AND_FIX_REPORT.md`.
- **Hasil dijalankan ulang untuk unit ini:** 12 laporan (4 model × 3 strategi) ke `results/unit_task__r1fix/` (cloud: 6 panggilan, perkiraan batas atas US$0,0013).
- **Promosi ke baseline:** 31 file unit, indeks 08 dan 09, `run_log.jsonl` (12 baris unit diganti), dan agregat Stage 12. Laporan lengkap ada di arsip hasil yang dirilis terpisah.
- **Agregat Stage 12:** dihitung ulang dengan `src/12_evaluate.py --variant promo_tmp` pada staging gabungan (offline, tanpa LLM, dengan `.venv`), karena agregat satu unit tidak dapat digabung ke baseline. Baris unit lain identik dengan baseline asli.
- **Dua laporan INVALID untuk unit ini dipertahankan apa adanya:** `qwen2.5-0.5b` P2 (`INCOMPLETE_STRUCTURE`) dan P3 (`INVALID_EVIDENCE_ID`).
- **Efek pada ringkasan global:** setelah promosi, 288 laporan = 211 VALID dan 77 INVALID.

## Arsip
`results/unit_task__r1fix/`, `results/unit_task__r1fix_all/`, `results/unit_task__promo_tmp/`, dan backup `~/ord2_backups/pre_promosi_r1fix_20261104T085810/` dipertahankan.

## Dokumentasi yang diperbarui bersama changelog ini
`README.md`, `docs/RUN_GUIDE.md`, `results/README.md`.
