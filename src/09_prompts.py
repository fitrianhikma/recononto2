"""STAGE 09 - Prompt P1/P2/P3 per unit (templat: prompts/templates/; arsip lama: prompts/archive_v0/).

    python3 src/09_prompts.py --scenario {1,2,3,all} [--unit task|scenario] [--variant NAMA]
P1 = aturan + EVIDENCE (digest)                                   [SIET S1 baseline]
P2 = P1 + blok CORRELATIONS: top-5 pasangan dari pairs.csv          [SIET S2 ORD2I-augmented]
P3 = P1 + satu laporan contoh lengkap sintetis (format_example.txt) [SIET S3 few-shot]
Ketiganya memakai digest, aturan, dan skema keluaran yang SAMA; hanya satu blok yang berbeda.
Pemeriksaan kebocoran contoh P3 (gagal = berhenti): nama rekaan / ID contoh muncul di digest unit. Waktu contoh yang kebetulan ada di digest = PERINGATAN.
Keluaran: results/unit_<unit>/09_prompts/scenarioN/<unit_id>/{P1,P2,P3}.txt + prompts_report.json; prompts_index.json per skenario.
Skor korelasi bukan probabilitas dan bukan bukti kausal.
"""
import argparse, csv, hashlib, json, re, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config, correlation as cc, digest as digestmod

STRATEGIES = ("P1", "P2", "P3")
SCORE_ONE = 1.0 - 1e-9
_SLOT = re.compile(r"\{(RULES|DIGEST|CORRELATIONS|EXAMPLE)\}")
TIME_RE = re.compile(r"(?<![\d:])(\d{2}:\d{2}:\d{2})(?![\d:])")


def sha(s: str) -> str: return hashlib.sha256(s.encode("utf-8")).hexdigest()
def tpl(name: str, tdir=None) -> str: return (Path(tdir or config.PROMPTS_DIR) / name).read_text(encoding="utf-8").rstrip("\n")
def fill(template: str, values: dict) -> str: return _SLOT.sub(lambda m: values[m.group(1)], template)      # satu lintasan (sama dengan kode lama)


def load_pairs(path) -> list:
    with open(path, newline="", encoding="utf-8") as f:
        return [dict(r, delta_t_s=float(r["delta_t_s"]), corr_t=float(r["corr_t"]), corr_s=float(r["corr_s"]), corr_o=float(r["corr_o"]), score=float(r["score"])) for r in csv.DictReader(f)]


def correlation_block(pairs: list, evidence: list, top_n: int, source_files=None, tdir=None) -> dict:
    """Top-N pasangan di antara bukti digest, urutan (skor turun, dt naik, IRI) - kunci urut sama dengan kode lama.
    Baris: ID, label sumber (parser) tiap event, skor dan komponennya, aturan pakar, selisih waktu (format baris lama + label sumber).
    Kalimat ringkasan (jumlah pasti) dihitung atas pasangan yang kedua event-nya berada pada SALAH SATU berkas di `source_files`
    (unit=scenario: source_files=None -> semua pasangan, seperti lama). `source_files` di sini adalah himpunan EFEKTIF yang
    sudah diperluas oleh run_scenario() lewat expand_with_duplicate_groups() - lihat catatan di sana (PERBAIKAN V2, lihat
    docs/CHANGELOG_V2.md #1)."""
    idof = {e["event_iri"]: e["id"] for e in evidence}; parser = {e["event_iri"]: e["parser"] for e in evidence}
    among = [p for p in pairs if p["event_a"] in idof and p["event_b"] in idof]
    key = lambda p: (-p["score"], p["delta_t_s"], p["event_a"], p["event_b"])
    top = sorted(among, key=key)[:top_n]

    def line(p):
        (ia, a), (ib, b) = sorted(((idof[p["event_a"]], p["event_a"]), (idof[p["event_b"]], p["event_b"])))
        rule = ", expert rule R1" if p["ek"] == "1" else ""
        return (f"[{ia}] ({parser[a]}) and [{ib}] ({parser[b]}): score {p['score']:.2f} (time {p['corr_t']:.2f}, subject {p['corr_s']:.2f}, "
                f"object {p['corr_o']:.2f}{rule}); {p['delta_t_s']:.1f} s apart")
    scope = pairs if source_files is None else [p for p in pairs if _file_of(p["event_a"]) in source_files and _file_of(p["event_b"]) in source_files]
    n_ge = len(scope); same_obj = sum(1 for p in scope if p["corr_o"] >= 1.0 and p["delta_t_s"] <= cc.T_CANDIDATE_MAX_S); by_rule = sum(1 for p in scope if p["ek"] == "1")
    summary = f"{same_obj} of {n_ge} pairs scored >= {cc.TAU} are the same object within {cc.T_CANDIDATE_MAX_S:g} s; {by_rule} by expert rule."
    lines = [line(p) for p in top] or ["(no correlated pair among the EVIDENCE items)"]
    return {"text": "\n".join(lines + [summary, tpl("correlation_scale.txt", tdir)]), "pairs_shown": len(top), "pairs_among_evidence": len(among),
            "pairs_ge_tau_in_scope": n_ge, "same_object_within_window": same_obj, "pairs_by_expert_rule": by_rule,
            "scope_files_effective": sorted(source_files) if source_files else None,
            "ids_in_block": sorted({idof[p[k]] for p in top for k in ("event_a", "event_b")})}


def _file_of(event_iri: str) -> str:
    """IRI event lama: .../<sN>/event/<slug berkas>/<baris>. Dikembalikan slug + '.csv' untuk dibandingkan dengan slug berkas unit."""
    return event_iri.rsplit("/", 2)[-2] + ".csv"


def load_duplicate_groups(scenario: str, root=None) -> dict:
    """PERBAIKAN V2 (docs/CHANGELOG_V2.md #1): baca results/01_audit/audit_{scenario}.json (keluaran stage 01, hanya dibaca,
    TIDAK dihitung ulang di sini) dan kembalikan {"groups": [set(slug.csv), ...], "source": "audit_json"|"MISSING"}.
    Alasan: correlation.load_events() mengkanonikalisasi event dengan hasRowHash sama (baris identik persis, lintas berkas)
    menjadi SATU event yang dipertahankan dalam graf korelasi; event dari berkas 'saudara' yang isinya identik TIDAK muncul
    sama sekali di pairs.csv (bukan dipindah IRI-nya, tapi disingkirkan sebelum pembentukan pasangan - lihat correlation.py
    baris load_events(), `by_hash.setdefault`). Akibatnya unit yang nama berkas nominalnya adalah berkas 'saudara yang
    disingkirkan' (mis. scenario3 4616-without-regex, saudara dari 4616-with-regex yang dipertahankan) tidak pernah cocok
    saat correlation_block() memfilter pairs.csv berdasarkan nama berkas nominalnya sendiri -> ringkasan P2 keliru '0 of 0'
    padahal bukti (digest) unit itu identik dengan saudaranya yang py punya 384 pasangan. Stage 01 SUDAH mendeteksi
    kelompok-berkas-isi-identik ini (audit_summary.md bagian 'kelompok isi identik'); fungsi ini hanya membaca ulang deteksi
    itu (TIDAK menghitung ulang dengan metode independen) dan menyediakannya untuk expand_with_duplicate_groups().
    Jika berkas audit stage 01 belum ada/tidak terbaca: kembalikan source="MISSING" dan groups=[] - TIDAK dianggap berarti
    tidak ada duplikat (sesuai larangan mengasumsikan berkas tidak ada = data kosong); run_scenario mencatat ini sebagai
    PERINGATAN di prompts_index.json, bukan diam-diam."""
    p = config._root(root) / "results" / "01_audit" / f"audit_{scenario}.json"
    if not p.exists(): return {"groups": [], "source": "MISSING", "path": str(p)}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        groups = [{_slug_csv(x) for x in g} for g in d.get("identical_content_groups", [])]
        return {"groups": groups, "source": "audit_json", "path": str(p)}
    except Exception as e:
        return {"groups": [], "source": f"READ_ERROR: {e}", "path": str(p)}


def expand_with_duplicate_groups(source_files, dup_groups: list):
    """PERBAIKAN V2: perluas `source_files` (nama berkas nominal unit, sudah di-slug) dengan anggota kelompok
    isi-identik (dup_groups, dari load_duplicate_groups()) yang beranggotakan salah satu berkas di source_files.
    source_files=None (unit=scenario) dikembalikan apa adanya (tidak terpengaruh). Jika tidak ada kelompok yang
    relevan, hasilnya identik dengan source_files (tidak ada perubahan untuk unit yang bukan bagian duplikat isi)."""
    if source_files is None: return None
    out = set(source_files)
    for g in dup_groups:
        if g & out: out |= g
    return out


def example_leak_check(example: str, digest_text: str, evidence: list, id_floor: int) -> dict:
    """Kebocoran contoh P3 terhadap digest unit. FAIL: nama rekaan bertanda kutip muncul di digest, atau ID contoh ada di digest.
    WARN: waktu HH:MM:SS contoh kebetulan ada di digest (M6c tetap tidak menghitungnya sebagai kebocoran templat)."""
    names = {w.lower() for w in re.findall(r'"([A-Za-z][A-Za-z-]{3,})"', example)}; dl = digest_text.lower()
    ex_ids = set(re.findall(r"\[(E\d+)\]", example)); dig_ids = {e["id"] for e in evidence}
    bad_names = sorted(n for n in names if re.search(r"(?<![a-z])" + re.escape(n) + r"(?![a-z])", dl))
    low_ids = sorted(i for i in ex_ids if int(i[1:]) < id_floor)
    times = sorted(t for t in set(TIME_RE.findall(example)) if t in set(TIME_RE.findall(digest_text)))
    return {"ok": not bad_names and not (ex_ids & dig_ids) and not low_ids, "names_in_digest": bad_names, "ids_in_digest": sorted(ex_ids & dig_ids),
            "example_ids_below_floor": low_ids, "WARN_times_in_digest": times}


def build_prompts(digest_text: str, evidence: list, pairs: list, top_n: int, source_files=None, tdir=None) -> dict:
    d = digest_text.rstrip("\n"); cb = correlation_block(pairs, evidence, top_n, source_files, tdir)
    vals = {"RULES": tpl("rules.txt", tdir), "DIGEST": d, "CORRELATIONS": cb["text"], "EXAMPLE": tpl(config.load_settings()["prompt"]["p3_example_file"], tdir)}
    return {"prompts": {s: fill(tpl(f"{s}.txt", tdir), vals) + "\n" for s in STRATEGIES}, "correlation": cb, "example": vals["EXAMPLE"]}


def run_scenario(scenario: str, unit: str, root=None) -> dict:
    st = config.load_settings()["prompt"]; dbase = config.unit_dir(unit, root) / "08_digest" / scenario; obase = config.unit_dir(unit, root) / "09_prompts" / scenario
    idx_p = dbase / "digest_index.json"; pairs_p = config.correlation_dir(scenario, root) / "pairs.csv"
    for p in (idx_p, pairs_p):
        if not p.exists(): return {"scenario": scenario, "status": "INPUT_NOT_FOUND", "expected_path": str(p)}
    didx = json.loads(idx_p.read_text(encoding="utf-8"))
    if didx["pairs_csv_sha256"] != hashlib.sha256(pairs_p.read_bytes()).hexdigest(): raise ValueError(f"digest {scenario} dibangun dari pairs.csv yang berbeda (jalankan ulang stage 08)")
    pairs = load_pairs(pairs_p); tdir = config.PROMPTS_DIR
    templates = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(tdir.glob("*.txt"))}
    dupe = load_duplicate_groups(scenario, root)      # PERBAIKAN V2 #1 - lihat load_duplicate_groups()/expand_with_duplicate_groups()
    index = {"scenario": scenario, "unit": unit, "templates_sha256": templates, "units": {}, "status": "OK",
             "duplicate_content_groups_source": dupe["source"], "duplicate_content_groups": [sorted(g) for g in dupe["groups"]]}
    for uid, v in didx["units"].items():
        if v.get("status") != "OK": continue
        dd = dbase / uid; digest = (dd / "digest.txt").read_text(encoding="utf-8"); evidence = json.loads((dd / "digest_evidence.json").read_text(encoding="utf-8"))["evidence"]
        drep = json.loads((dd / "digest_report.json").read_text(encoding="utf-8"))
        sf_nominal = None if drep["source_files"] == "ALL" else {_slug_csv(x) for x in drep["source_files"]}
        sf_effective = expand_with_duplicate_groups(sf_nominal, dupe["groups"])      # PERBAIKAN V2 #1
        res = build_prompts(digest, evidence, pairs, st["p2_top_pairs"], sf_effective, tdir)
        leak = example_leak_check(res["example"], digest, evidence, st["example_id_floor"])
        out = obase / uid
        rep = {"scenario": scenario, "unit": unit, "unit_id": uid, "status": "OK" if leak["ok"] else "LEAK_FAIL", "digest_sha256": drep["digest_sha256"],
               "pairs_csv_sha256": didx["pairs_csv_sha256"], "templates_sha256": templates, "p3_example_leak_check": leak,
               "scope_files_nominal": sorted(sf_nominal) if sf_nominal else None,
               "correlation_block": {k: x for k, x in res["correlation"].items() if k != "text"}, "prompts": {}}
        for s, t in res["prompts"].items():
            digestmod.write_atomic(out / f"{s}.txt", t)
            rep["prompts"][s] = {"chars": len(t), "approx_tokens_chars_div4": len(t) // 4, "sha256": sha(t)}
        digestmod.write_atomic(out / "prompts_report.json", json.dumps(rep, indent=1, ensure_ascii=False) + "\n")
        index["units"][uid] = {"status": rep["status"], **{s: rep["prompts"][s]["sha256"] for s in STRATEGIES}, "chars": {s: rep["prompts"][s]["chars"] for s in STRATEGIES},
                               "warn_example_times_in_digest": leak["WARN_times_in_digest"]}
        if not leak["ok"]: index["status"] = "LEAK_FAIL"
    groups = {}
    for uid, v in index["units"].items(): groups.setdefault(tuple(v[s] for s in STRATEGIES), []).append(uid)
    index["identical_prompt_groups"] = [g for g in groups.values() if len(g) > 1]
    index["distinct_prompt_sets"] = len(groups)
    digestmod.write_atomic(obase / "prompts_index.json", json.dumps(index, indent=1, ensure_ascii=False) + "\n")
    return index


def _slug_csv(name: str) -> str:
    """Slug berkas persis seperti IRI event lama (rdf_nt.slug pada nama tanpa .csv) + '.csv'."""
    from rdf_nt import slug
    return slug(name[:-4] if name.endswith(".csv") else name) + ".csv"


def main():
    st = config.load_settings()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scenario", required=True, choices=["1", "2", "3", "all"]); ap.add_argument("--unit", choices=["task", "scenario"], default=st["unit_default"])
    ap.add_argument("--variant", help="baca digest dan tulis prompt di results/unit_<unit>__<variant> (baseline tidak tersentuh)")
    a = ap.parse_args(); config.set_variant(a.variant); bad = False; total_units = total_sets = 0
    for s in config.scenario_list(a.scenario):
        r = run_scenario(s, a.unit)
        if r["status"] == "INPUT_NOT_FOUND": print(f"[{s}] {r['status']}: {r['expected_path']}"); bad = True; continue
        for uid, v in r["units"].items():
            print(f"[{s}] {uid}: {v['status']} chars P1/P2/P3={v['chars']['P1']}/{v['chars']['P2']}/{v['chars']['P3']}" + (f" PERINGATAN waktu contoh ada di digest: {v['warn_example_times_in_digest']}" if v["warn_example_times_in_digest"] else ""))
        if r["identical_prompt_groups"]: print(f"[{s}] prompt identik (satu panggilan LLM, dievaluasi per tugas): {r['identical_prompt_groups']}")
        total_units += len(r["units"]); total_sets += r["distinct_prompt_sets"]; bad |= r["status"] != "OK"
    n_models = len(st["models"])
    print(f"RINGKASAN: unit={total_units}, set prompt berbeda={total_sets}; panggilan LLM per model = {total_sets} x 3 = {total_sets * 3}; "
          f"untuk {n_models} model = {total_sets * 3 * n_models} (laporan yang dievaluasi = {total_units} x 3 x {n_models} = {total_units * 3 * n_models})")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
