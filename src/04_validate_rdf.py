"""STAGE 04 - Validasi RDF (kode lama 03_validate_rdf.py; pemeriksaan tidak diubah, hanya lokasi keluaran: results/04_validate/).

PHASE 3B - Validasi RDF (GERBANG B). Validator ditulis INDEPENDEN dari pembangun: tidak memakai ulang skl_objects/subject_of.

    python3 src/03_validate_rdf.py --scenario all [--tasks data/tasks]
Exit code != 0 bila ada pemeriksaan gagal.
"""
import argparse, csv, glob, hashlib, importlib.util, json, os, random, re, shutil, sys, tempfile
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config
from rdf_nt import ORD2I, RDF_TYPE, XSD_DATETIME, parse_nt_line, norm_path

O = lambda n: ORD2I + n
SEED = 20240601
SAMPLE_N = 20


def load_builder():
    """Muat 03_build_rdf.py sebagai modul lewat importlib (nama berkas berawalan angka, tidak bisa 'import' biasa)."""
    path = Path(__file__).resolve().parent / "03_build_rdf.py"
    spec = importlib.util.spec_from_file_location("build_rdf_03", path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def dt_key(s):
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})(\.\d+)?", s or "")
    if not m: return None
    frac = (m.group(7) or ".0")[1:].ljust(6, "0")[:6]
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}T{m.group(4)}:{m.group(5)}:{m.group(6)}.{frac}"


def load_nt(path: Path):
    """-> (props: {subject: {predicate: [objek,...]}}, n_triples). Sintaks salah -> ValueError."""
    props = defaultdict(lambda: defaultdict(list)); n = 0
    with open(path, encoding="utf-8", newline="") as f:
        for line in f:
            s, p, o = parse_nt_line(line); props[s][p].append(o); n += 1
    return props, n


def rows_of(csv_path: Path) -> dict:
    csv.field_size_limit(1 << 30); out = {}
    with open(csv_path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f): out[(r["source_file"], int(r["row_in_file"]))] = r
    return out


def val(props, s, p):
    return [o[1] for o in props[s].get(p, [])]


class Check:
    def __init__(self): self.items = {}
    def add(self, name, ok, detail=None): self.items[name] = {"ok": bool(ok), "detail": detail}
    @property
    def all_ok(self): return all(v["ok"] for v in self.items.values())


def validate_scenario(scenario, tasks_dir=None, root=None) -> dict:
    b = load_builder(); paths = config.scenario_paths(scenario, root); rp = config.rdf_paths(scenario, root)
    root_ = Path(root) if root else config.ROOT; sn = "s" + scenario[-1]
    csv_path = paths["processed_dir"] / config.OFFICIAL_PROCESSED
    if not rp["nt"].exists(): return {"scenario": scenario, "status": "NT_NOT_FOUND", "expected_path": str(rp["nt"])}
    r2 = json.loads(config.preprocess_report_path(scenario, root).read_text(encoding="utf-8"))
    br = json.loads((rp["report_dir"] / f"build_report_{scenario}.json").read_text(encoding="utf-8"))
    C = Check(); res = {"scenario": scenario, "status": "OK"}
    props, ntrip = load_nt(rp["nt"])                                                         # V0: sintaks (ValueError bila salah)
    C.add("V0 sintaks N-Triples valid & jumlah triple == laporan pembangun", ntrip == br["triples"], {"triples": ntrip})
    rdflib_note = "rdflib tidak terpasang; pemeriksa sintaks sendiri dipakai"
    try:
        import rdflib
        g = rdflib.Graph(); g.parse(str(rp["nt"]), format="nt"); C.add("V0b rdflib: jumlah triple sama", len(g) == ntrip, {"rdflib": len(g)}); rdflib_note = "rdflib " + rdflib.__version__
    except ImportError: pass
    res["syntax_checker"] = rdflib_note
    ev = {s: p for s, p in props.items() if any(o[1] == O("Event") for o in p.get(RDF_TYPE, []))}
    rows = rows_of(csv_path)
    # V1
    hashes = {v for p in ev.values() for v in [o[1] for o in p.get(O("hasRowHash"), [])]}
    C.add("V1 jumlah Event == baris input == laporan Phase 2.1", len(ev) == len(rows) == r2["rows_in"], {"events": len(ev), "csv_rows": len(rows), "report_rows_in": r2["rows_in"]})
    C.add("V1b hasRowHash unik == laporan Phase 2.1", len(hashes) == r2["row_hash_unique"], {"unik": len(hashes), "laporan": r2["row_hash_unique"]})
    # V2
    bad2 = [s for s, p in ev.items() if any(len(p.get(O(k), [])) != 1 for k in ("hasEventType", "hasTimestampStatus", "hasSourceFile", "hasRowInFile"))]
    C.add("V2 tiap Event tepat satu hasEventType/hasTimestampStatus/hasSourceFile/hasRowInFile", not bad2, {"pelanggar": len(bad2), "contoh": bad2[:3]})
    # V3
    st = Counter(); bad3 = []
    for s, p in ev.items():
        status = p[O("hasTimestampStatus")][0][1]; st[status] += 1; has = O("hasTimestamp") in p
        if has != (status == "valid"): bad3.append(s)
        if has and p[O("hasTimestamp")][0][2] != XSD_DATETIME: bad3.append(s)
    C.add("V3 hasTimestamp ada iff status valid (bertipe xsd:dateTime)", not bad3, {"pelanggar": len(bad3)})
    C.add("V3b hitungan per status == laporan Phase 2.1", dict(st) == {k: v for k, v in r2["timestamp_status"].items() if v}, {"rdf": dict(st), "laporan": {k: v for k, v in r2["timestamp_status"].items() if v}})
    # V4 literal kosong, entitas dirujuk, objek terdefinisi
    empty = sum(1 for p in props.values() for objs in p.values() for o in objs if o[0] == "lit" and o[1] == "")
    refd = Counter(o[1] for p in ev.values() for k in ("hasObject", "hasSubject") for o in p.get(O(k), []))
    skl_types = {O(c) for c in ("File", "ExeFile", "RegistryKey", "Webpage", "WebResource", "Cookie", "WinUserAccount")}
    entities = {s for s, p in props.items() if any(o[1] in skl_types for o in p.get(RDF_TYPE, []))}
    orphan = [e for e in entities if refd[e] == 0]; dangling = [o for o in refd if o not in props]
    C.add("V4 tidak ada literal kosong", empty == 0, {"jumlah": empty})
    C.add("V4b tiap entitas SKL/akun dirujuk >= 1 Event", not orphan, {"yatim": len(orphan), "contoh": orphan[:3]})
    C.add("V4c tiap objek hasObject/hasSubject terdefinisi", not dangling, {"menggantung": len(dangling)})
    # V4d: entitas sesuai isi kolom CSV (independen) + kelengkapan
    viol, miss = Counter(), Counter(); ex = defaultdict(list)
    def bad(kind, s, why):
        viol[kind] += 1
        if len(ex[kind]) < 3: ex[kind].append((s.rsplit("/", 2)[-2] + "/" + s.rsplit("/", 1)[-1], why))
    for s, p in ev.items():
        row = rows[(p[O("hasSourceFile")][0][1], int(p[O("hasRowInFile")][0][1]))]
        linked = defaultdict(list)
        for o in p.get(O("hasObject"), []):
            t = {x[1] for x in props[o[1]][RDF_TYPE]} & skl_types
            for tt in t: linked[tt.replace(ORD2I, "")].append(o[1])
        for ent in linked.get("File", []):
            if norm_path(val(props, ent, O("hasFilePath"))[0]) != norm_path(row["file_path"]): bad("File", s, "path")
        for ent in linked.get("RegistryKey", []):
            if norm_path(val(props, ent, O("hasRegistryKey"))[0]) != norm_path(row["registry_key"]): bad("RegistryKey", s, "key")
        for cls in ("Webpage", "WebResource"):
            for ent in linked.get(cls, []):
                if val(props, ent, O("hasURL"))[0] != row["url"]: bad(cls, s, "url")
                h = val(props, ent, O("hasHost"));  t = val(props, ent, O("hasTitle"))
                if (h and h[0] != row["host"]) or (t and t[0] != row["page_title"]) or (not h and row["host"]): bad(cls, s, "host/title")
        for ent in linked.get("Cookie", []):
            if val(props, ent, O("hasDomain"))[0].lower() != row["host"].lower(): bad("Cookie", s, "domain")
        for ent in linked.get("ExeFile", []):
            nm, pt = val(props, ent, O("hasFileName"))[0], val(props, ent, O("hasFilePath"))
            if not (nm == row["app_name"] or nm == re.split(r"[\\/]", row["app_name"])[-1]): bad("ExeFile", s, "nama")
            if pt and norm_path(pt[0]) not in (norm_path(row["file_path"]), norm_path(row["app_name"])): bad("ExeFile", s, "path")
        et, app = row["event_type"], row["app_name"]
        exe_expected = et in ("AppExecution", "AppPresence") and app and not app.startswith("UEME_")
        if row["file_path"] and not exe_expected and not linked.get("File"): miss["File"] += 1
        if row["registry_key"] and not linked.get("RegistryKey"): miss["RegistryKey"] += 1
        if row["url"] and et == "WebpageVisit" and not linked.get("Webpage"): miss["Webpage"] += 1
        if row["url"] and et in ("WebSearch", "WebCacheEntry", "FileDownload") and not linked.get("WebResource"): miss["WebResource"] += 1
        if et == "CookieAccess" and row["host"] and not linked.get("Cookie"): miss["Cookie"] += 1
        if exe_expected and not linked.get("ExeFile"): miss["ExeFile"] += 1
        if not row["file_path"] and not row["registry_key"] and not row["url"] and not (exe_expected) and linked and not p.get(O("hasSubject")): bad("tanpa-kolom", s, "objek tanpa kolom sumber")
    C.add("V4d setiap entitas SKL sesuai isi kolom CSV asalnya (semua event)", not viol, {"pelanggaran": dict(viol), "contoh": {k: v for k, v in ex.items()}})
    C.add("V4e setiap kolom turunan non-kosong yang berlaku menghasilkan entitas (kelengkapan)", not miss, {"hilang": dict(miss)})
    # V4f Subject: verifikasi indeks pada SEMUA event 4624/4625/4647 + BAM, dengan parser kutip independen
    sub_exp, sub_got, sub_bad, sub_skip = Counter(), Counter(), [], Counter()
    for s, p in ev.items():
        row = rows[(p[O("hasSourceFile")][0][1], int(p[O("hasRowInFile")][0][1]))]; msg = row["message"]
        mi = re.match(r"^\[(\d+) /", msg) if row["parser"] == "winevtx" else None
        key = None
        if mi and "Source Name: Microsoft-Windows-Security-Auditing " in msg and mi.group(1) in ("4624", "4625", "4647"): key = "evtx" + mi.group(1)
        elif row["parser"] == "winreg/bam" and re.search(r"\[S-1-[0-9-]+\]\s*$", msg): key = "bam"
        subj = p.get(O("hasSubject"), [])
        if key: sub_exp[key] += 1
        if not key and subj: sub_bad.append(("subject tanpa sumber", s)); continue
        if not key: continue
        if not subj: sub_skip[key] += 1; continue
        sub_got[key] += 1; acc = subj[0][1]
        if key == "bam":
            if val(props, acc, O("hasSID")) != [re.search(r"\[(S-1-[0-9-]+)\]\s*$", msg).group(1)]: sub_bad.append(("bam sid", s))
            continue
        inner = msg[msg.find("Strings: [") + 10: msg.rfind("] Computer Name:")]; tok = re.findall(r"'([^']*)'", inner)
        i = {"evtx4647": (0, 1, 2)}.get(key, (4, 5, 6))
        if tok[i[1]] not in val(props, acc, O("hasAccountName")) or tok[i[2]] not in val(props, acc, O("hasDomain")): sub_bad.append((key + " nama/domain", s))
        if tok[i[0]] != "S-1-0-0" and tok[i[0]] not in val(props, acc, O("hasSID")): sub_bad.append((key + " sid", s))
        if key == "evtx4624" and val(props, s, O("hasLogonType")) != [tok[8]]: sub_bad.append(("logontype", s))
    reported = Counter()                                      # anomali yang DICATAT pembangun (event dalam cakupan tanpa Subject harus tercatat, bukan hilang senyap)
    for k, v in br.get("subject_anomalies", {}).items(): reported[k.split(":")[0]] += v
    C.add("V4f Subject: indeks Strings & BAM sesuai pada SEMUA event 4624/4625/4647/BAM; tanpa pelepasan senyap", not sub_bad and dict(sub_skip) == dict(reported),
          {"diharapkan": dict(sub_exp), "dibuat": dict(sub_got), "tanpa_subject": dict(sub_skip), "anomali_tercatat": dict(reported), "salah": sub_bad[:5]})
    # V6 determinisme: bangun ulang di direktori sementara -> SHA-256 sama
    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        for rel in ((paths["processed_dir"] / config.OFFICIAL_PROCESSED).relative_to(root_), config.preprocess_report_path(scenario, root).relative_to(root_)):
            (t / rel).parent.mkdir(parents=True, exist_ok=True); shutil.copy(root_ / rel, t / rel)
        again = b.build_scenario(scenario, root=t, schema_event_types=[])
    C.add("V6 determinisme: SHA-256 .nt identik pada build ulang", again["nt_sha256"] == br["nt_sha256"] == hashlib.sha256(rp["nt"].read_bytes()).hexdigest(), {"sha256": br["nt_sha256"][:16]})
    # GT
    rp["validate_dir"].mkdir(parents=True, exist_ok=True)
    if tasks_dir and Path(tasks_dir).exists():
        res["ground_truth"] = gt_coverage(scenario, ev, props, Path(tasks_dir), rp["validate_dir"], C)
    else:
        res["ground_truth"] = {"status": "TASKS_NOT_PROVIDED"}; C.add("V5 cakupan ground truth resmi", False, "tasks tidak tersedia (--tasks)")
    res["checks"] = C.items; res["all_ok"] = C.all_ok
    res["event_iris"] = None
    rp["validate_dir"].mkdir(parents=True, exist_ok=True)
    sample_review(scenario, ev, props, rows, rp["validate_dir"])
    (rp["validate_dir"] / f"validation_{scenario}.json").write_text(json.dumps({k: v for k, v in res.items() if k != "event_iris"}, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    res["_event_iris"] = set(ev); res["_nt_sha256"] = br["nt_sha256"]
    return res


def sample_review(scenario, ev, props, rows, out_dir):
    rnd = random.Random(SEED); picks = rnd.sample(sorted(ev), min(SAMPLE_N, len(ev))); L = [f"# Sampel review manusia — {scenario} (seed {SEED}, {len(picks)} event)\n"]
    for s in picks:
        p = ev[s]; row = rows[(p[O("hasSourceFile")][0][1], int(p[O("hasRowInFile")][0][1]))]
        L += [f"## {s.split('/event/')[1]}", "", "**Baris CSV (kolom kunci):**", "```",
              *(f"{k}: {row[k][:200]}" for k in ("datetime_raw", "timestamp_status", "timestamp_desc", "event_type", "rule_id", "parser", "url", "host", "page_title", "app_name", "registry_key", "file_path", "message") if row[k] != ""), "```", "**Triple Event:**", "```"]
        for pr, objs in p.items():
            for o in objs: L.append(f"{pr.replace(ORD2I, 'ord2i:').replace(RDF_TYPE, 'a')} {('<' + o[1] + '>') if o[0] == 'iri' else repr(o[1][:120])}" + (f"^^{o[2].split('#')[-1]}" if o[0] == 'lit' and o[2] else ""))
        for k in ("hasObject", "hasSubject"):
            for o in p.get(O(k), []):
                L.append(f"  -> {o[1].split('/', 4)[-1]}: " + "; ".join(f"{q.replace(ORD2I, '')}={[x[1][:80] for x in v]}" for q, v in props[o[1]].items() if q != RDF_TYPE))
        L += ["```", ""]
    (out_dir / f"sample_review_{scenario}.md").write_text("\n".join(L), encoding="utf-8")


def gt_coverage(scenario, ev, props, tasks, out_dir, C) -> dict:
    idx = defaultdict(list); idx3 = defaultdict(list); byfile = defaultdict(list)
    for s, p in ev.items():
        sf, rin = p[O("hasSourceFile")][0][1], int(p[O("hasRowInFile")][0][1])
        raw = val(props, s, O("hasTimestampRaw")); msg = (val(props, s, O("hasMessage")) or [""])[0]
        if raw:
            idx[(sf, dt_key(raw[0]))].append((rin, msg)); idx3[(sf, raw[0], msg[:100])].append(rin); byfile[sf].append((rin, msg, raw[0]))
    out, loc = {}, []
    if scenario == "scenario1":
        for kind in ("single", "multiple"):
            tot = strict = dtonly = 0; miss = []
            for fp in sorted(glob.glob(str(tasks / "event-summarization" / f"ground-truth-{kind}" / "*.json"))):
                sf = os.path.basename(fp).replace(".json", ".csv")
                for k, g in json.load(open(fp, encoding="utf-8")).items():
                    tot += 1; cands = idx.get((sf, dt_key(g["date_time_min"])), []); evd = g.get("evidence_source", "")
                    m = [c for c in cands if c[1].startswith(evd[:120]) or evd.startswith(c[1][:120])]
                    if m: strict += 1; loc.append((f"s1-{kind}", f"{sf}:{k}", sf, m[0][0], "strict"))
                    elif cands: dtonly += 1; loc.append((f"s1-{kind}", f"{sf}:{k}", sf, cands[0][0], "datetime_only"))
                    else: miss.append(f"{sf}:{k}")
            out[kind] = {"items": tot, "matched_strict": strict, "matched_datetime_only": dtonly, "unmatched": len(miss), "unmatched_examples": miss[:5]}
    elif scenario == "scenario2":
        tot = strict = guid = content = 0; miss = []; deltas = []
        for fp in sorted(glob.glob(str(tasks / "keyword-analysis" / "ground-truth" / "*.json"))):
            sf = os.path.basename(fp).replace(".json", ".csv")
            for i, g in enumerate(json.load(open(fp, encoding="utf-8"))):
                tot += 1; cands = idx.get((sf, dt_key(g["datetime"])), []); gid = f"{sf}:{i}"
                m = [c for c in cands if c[1].startswith(g["message"][:120])]
                if m: strict += 1; loc.append(("s2-keyword", gid, sf, m[0][0], "strict")); continue
                gs = set(re.findall(r"\{[0-9A-Fa-f-]{36}\}", g["message"])); m = [c for c in cands if gs and gs & set(re.findall(r"\{[0-9A-Fa-f-]{36}\}", c[1]))]
                if m: guid += 1; loc.append(("s2-keyword", gid, sf, m[0][0], "datetime+guid")); continue
                # tingkat terpisah & berlabel: isi IDENTIK dan UNIK dalam file, tetapi datetime GT berbeda dari file events (inkonsistensi data resmi)
                norm = g["message"].rstrip("] \n"); same = [c for c in byfile.get(sf, []) if c[1].rstrip("] \n") == norm]
                if len(same) == 1:
                    from datetime import datetime
                    d = abs((datetime.fromisoformat(dt_key(same[0][2])) - datetime.fromisoformat(dt_key(g["datetime"]))).total_seconds())
                    content += 1; deltas.append({"gt": gid, "row_in_file": same[0][0], "gt_datetime": g["datetime"], "events_datetime": same[0][2], "delta_seconds": round(d, 3)})
                    loc.append(("s2-keyword", gid, sf, same[0][0], "content_unique_datetime_differs"))
                else: miss.append(gid)
        out["keyword"] = {"items": tot, "matched_strict": strict, "matched_datetime_guid": guid, "matched_content_unique_datetime_differs": content,
                          "datetime_discrepancies": deltas, "unmatched": len(miss), "unmatched_examples": miss[:5]}
    elif scenario == "scenario3":
        tot = found = 0; miss = []
        for fp in sorted(glob.glob(str(tasks / "grep" / "ground-truth" / "*.txt"))):
            sf = os.path.basename(fp).replace(".txt", ".csv")
            for l in open(fp, encoding="utf-8", errors="replace").read().splitlines():
                if not l.strip(): continue
                try: f = next(csv.reader([l]))
                except Exception: continue
                if len(f) < 5: continue
                tot += 1; c = idx3.get((sf, f[0], f[4][:100]))
                if c: found += 1; loc.append(("s3-grep", f"{sf}:{tot}", sf, c[0], "strict"))
                else: miss.append(f"{sf}:{tot}")
        out["grep"] = {"items": tot, "matched_strict": found, "unmatched": len(miss), "unmatched_examples": miss[:5]}
    with open(out_dir / f"gt_localization_{scenario}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["gt_set", "gt_id", "source_file", "row_in_file", "match_level"]); w.writerows(loc)
    ok = all(v["unmatched"] == 0 for v in out.values()) and bool(out)
    C.add("V5 semua event ground truth resmi dapat dilokalisasi di RDF (source_file,row_in_file)", ok, out)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", required=True, choices=["1", "2", "3", "all"])
    ap.add_argument("--tasks", default=str(config.TASKS_DIR))
    a = ap.parse_args(); allres = {}; fail = False
    for s in (config.SCENARIOS if a.scenario == "all" else [f"scenario{a.scenario}"]):
        r = validate_scenario(s, a.tasks if Path(a.tasks).exists() else None)
        if r["status"] != "OK": print(f"[{s}] {r['status']}"); fail = True; continue
        allres[s] = r; fail |= not r["all_ok"]
        print(f"\n[{s}] {'LULUS' if r['all_ok'] else 'GAGAL'} ({r['syntax_checker']})")
        for k, v in r["checks"].items(): print(f"   {'OK  ' if v['ok'] else 'GAGAL'} {k}" + ("" if v["ok"] else f"  -> {json.dumps(v['detail'], default=str)[:400]}"))
    if len(allres) > 1:                                   # V7 pemisahan skenario
        sets = {s: r["_event_iris"] for s, r in allres.items()}; hs = {s: r["_nt_sha256"] for s, r in allres.items()}
        inter = [(x, y, len(sets[x] & sets[y])) for x in sets for y in sets if x < y]
        ok = all(n == 0 for *_, n in inter) and len(set(hs.values())) == len(hs)
        print(f"\nV7 pemisahan skenario: IRI event beririsan={inter}, hash .nt berbeda={len(set(hs.values())) == len(hs)} -> {'OK' if ok else 'GAGAL'}"); fail |= not ok
        (config.rdf_paths("scenario1")["validate_dir"] / "validation_separation.json").write_text(json.dumps({"event_iri_intersections": inter, "nt_sha256": hs, "ok": ok}, indent=2), encoding="utf-8")
    sys.exit(1 if fail else 0)


if __name__ == "__main__":
    main()
