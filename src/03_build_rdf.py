"""STAGE 03 - Bangun RDF (kode lama 03_build_rdf.py; logika tidak diubah, hanya lokasi masukan/keluaran).
Keluaran: results/03_rdf/scenarioN.nt, sample_scenarioN.ttl, ord2i_impl_schema.nt, build_report_scenarioN.json

PHASE 3B - Representasi RDF berbasis konsep ORD2I (namespace IMPLEMENTASI, bukan ontologi baru).

Input : data/scenarioN/processed/official_events_classified.csv + reports/phase2_1/preprocess_events_report_scenarioN.json
Output: rdf/scenarioN.nt (satu graf per skenario, tidak pernah digabung), rdf/sample_scenarioN.ttl, rdf/ord2i_impl_schema.nt,
        reports/phase3/build_report_scenarioN.json
Aturan: tidak ada triple dari nilai kosong; tidak ada dedup (satu baris = satu Event); Subject hanya bila data menyatakan akun.

    python3 src/03_build_rdf.py --scenario all
"""
import argparse, csv, hashlib, json, os, re, sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config
import search_engines
from rdf_nt import (BASE, ORD2I, OWL, RDF_TYPE, RDFS, XSD_DATETIME, XSD_INTEGER, iri, lit, nt_line, norm_path, sha1_16, slug, to_turtle)

O = lambda name: ORD2I + name
UNCLASSIFIED = "Unclassified"
SID_RE = re.compile(r"^S-1-\d+(?:-\d+)*$")
EVTX_ID = re.compile(r"^\[(\d+) /")
EVTX_SRC = re.compile(r"Source Name: (.*?) (?:Strings:|Computer Name:)")
EVTX_COMP = re.compile(r"Computer Name: (\S+)")
BAM_SID = re.compile(r"\[(S-1-[0-9-]+)\]\s*$")
NOT_AN_APP = ("UEME_",)                      # penghitung internal UserAssist, bukan nama aplikasi (terbukti di data S3)
SEC = "Microsoft-Windows-Security-Auditing"
SUBJECT_LAYOUT = {"4647": (0, 1, 2), "4624": (4, 5, 6), "4625": (4, 5, 6)}   # indeks Strings: (SID, nama, domain)
_CLOSE = re.compile(r"'(?=  '|  None|$)")

# ---------------------------------------------------------------- skema implementasi (dibangkitkan kode)
LAYERS = {"CKL": "Common Knowledge Layer", "SKL": "Specialised Knowledge Layer", "TKL": "Traceability Knowledge Layer"}
CLASSES = [("Event", "CKL", None), ("EventLogEntry", "CKL", "Event"), ("Account", "SKL", None), ("WinUserAccount", "SKL", "Account"),
           ("File", "SKL", None), ("ExeFile", "SKL", "File"), ("RegistryKey", "SKL", None), ("Webpage", "SKL", None),
           ("WebResource", "SKL", None), ("Cookie", "SKL", None), ("InvestigativeOperation", "TKL", None)]
PROPS = {"hasTimestamp": "xsd:dateTime; hanya bila timestamp_status = valid", "hasTimestampRaw": "string datetime asli (tidak diubah)",
         "hasTimestampStatus": "valid|zero_date|filetime_zero|not_a_time|out_of_range|unparseable", "hasTimestampDescription": "timestamp_desc Plaso",
         "hasEventType": "label classifier (event_rules_v2.csv)", "hasRuleId": "rule yang aktif; kosong untuk Unclassified (tidak ditulis)",
         "hasParser": "parser Plaso", "hasSource": "source Plaso", "hasMessage": "message Plaso apa adanya", "hasDisplayName": "display_name Plaso",
         "hasSourceFile": "nama file events asal", "hasRowInFile": "nomor baris data (1-based) dalam file asal", "hasRowHash": "SHA-1 8 kolom mentah; untuk pengelompokan duplikat, bukan penghapusan",
         "hasObject": "event -> entitas SKL", "hasSubject": "event -> akun; hanya bila data menyatakan akun", "partOfOperation": "event -> InvestigativeOperation",
         "hasEventID": "Event ID EVTX", "hasProvider": "Source Name EVTX", "hasComputerName": "Computer Name EVTX", "hasLogonType": "LogonType (4624, Strings ke-8)",
         "hasFilePath": "path file apa adanya (kemunculan pertama)", "hasFileName": "nama berkas/aplikasi", "hasRegistryKey": "kunci registry", "hasURL": "URL",
         "hasHost": "host dari URL", "hasTitle": "judul halaman", "hasSearchQuery": "nilai parameter kueri pencarian", "hasDomain": "host cookie / domain akun",
         "hasSID": "SID akun", "hasAccountName": "nama akun", "hasTool": "alat ekstraksi", "hasDatasetDOI": "DOI dataset", "hasInputSHA256": "'<sha256>  <nama file>' per file events",
         "hasRuleTableSHA256": "SHA-256 tabel rule yang dipakai"}
SCHEMA_NOTE = ("Namespace implementasi tesis; konsep berasal dari ORD2I (Chabot et al., 2015). Bukan IRI resmi ORD2I dan bukan klaim ontologi baru. "
               "Lapisan: CKL = Common Knowledge Layer, SKL = Specialised Knowledge Layer, TKL = Traceability Knowledge Layer.")


def schema_triples(event_types) -> list:
    T = []
    ont = ORD2I.rstrip("#")
    T += [(ont, RDF_TYPE, iri(OWL + "Ontology")), (ont, RDFS + "comment", lit(SCHEMA_NOTE))]
    for name, layer, parent in CLASSES:
        T += [(O(name), RDF_TYPE, iri(OWL + "Class")), (O(name), RDFS + "label", lit(name)), (O(name), O("knowledgeLayer"), lit(layer)),
              (O(name), RDFS + "comment", lit(f"{LAYERS[layer]} (implementasi konsep ORD2I)"))]
        if parent: T.append((O(name), RDFS + "subClassOf", iri(O(parent))))
    for et in sorted(set(event_types) - {UNCLASSIFIED}):
        T += [(O(et), RDF_TYPE, iri(OWL + "Class")), (O(et), RDFS + "label", lit(et)), (O(et), O("knowledgeLayer"), lit("CKL")),
              (O(et), RDFS + "subClassOf", iri(O("Event")))]
    for name, comment in PROPS.items():
        T += [(O(name), RDF_TYPE, iri("http://www.w3.org/1999/02/22-rdf-syntax-ns#Property")), (O(name), RDFS + "label", lit(name)), (O(name), RDFS + "comment", lit(comment))]
    return T


# ---------------------------------------------------------------- EVTX
def parse_strings(message: str):
    """'Strings: [...]' -> list[str|None] atau None bila tidak terparse. Elemen dipisah dua spasi; 'None' tanpa kutip."""
    i = message.find(" Strings: [")
    j = message.rfind("] Computer Name:")
    if i < 0 or j < 0 or j < i: return None
    inner, pos, out = message[i + 11:j], 0, []
    while pos < len(inner):
        if inner.startswith("None", pos) and (pos + 4 == len(inner) or inner.startswith("  ", pos + 4)):
            out.append(None); pos += 4
        elif inner[pos] == "'":
            m = _CLOSE.search(inner, pos + 1)
            if not m: return None
            out.append(inner[pos + 1:m.start()]); pos = m.end()
        else:
            return None
        if pos < len(inner):
            if not inner.startswith("  ", pos): return None
            pos += 2
    return out


def evtx_info(row: dict):
    msg = row["message"]
    mi = EVTX_ID.match(msg)
    ms = EVTX_SRC.search(msg)
    mc = EVTX_COMP.search(msg)
    return {"id": mi.group(1) if mi else None, "provider": ms.group(1) if ms else None, "computer": mc.group(1) if mc else None,
            "strings": parse_strings(msg) if mi else None}


def subject_of(row: dict, info):
    """-> (subject|None, anomali:list[str]). Subject hanya dari EVTX 4624/4625/4647 (Security-Auditing) dan BAM."""
    if row["parser"] == "winreg/bam":
        m = BAM_SID.search(row["message"])
        return ({"sid": m.group(1), "name": "", "domain": "", "source": "bam", "logon_type": None}, []) if m else (None, ["bam:sid_tidak_ditemukan"])
    if info and info["provider"] == SEC and info["id"] in SUBJECT_LAYOUT:
        tag, st = f"evtx{info['id']}", info["strings"]
        if st is None: return None, [f"{tag}:strings_tidak_terparse"]
        isid, iname, idom = SUBJECT_LAYOUT[info["id"]]
        if len(st) <= idom: return None, [f"{tag}:strings_terlalu_pendek({len(st)})"]
        sid, name, dom = (st[isid] or ""), (st[iname] or ""), (st[idom] or "")
        an = []
        if sid and not SID_RE.match(sid): an.append(f"{tag}:sid_bukan_pola({sid[:20]})"); sid = ""
        if not sid and not name: return None, an + [f"{tag}:tanpa_sid_dan_nama"]
        lt = st[8] if info["id"] == "4624" and len(st) > 8 else None
        return {"sid": sid, "name": name, "domain": dom, "source": tag, "logon_type": lt}, an
    return None, []


def account_key(s: dict) -> str:
    """SID bila ada & bukan SID nol -> identitas = SID; selain itu domain\\nama. (Deviasi tercatat dari spesifikasi sha1(sid|domain\\nama):
    agar BAM (hanya SID) dan EVTX (SID+nama) untuk akun yang sama menjadi SATU individu, penting bagi 'common subjects'.)"""
    if s["sid"] and s["sid"] != "S-1-0-0": return "sid:" + s["sid"].lower()
    return "name:" + f"{s['domain']}\\{s['name']}".lower()


# ---------------------------------------------------------------- objek SKL
def search_query(url: str) -> str:
    return search_engines.search_query(url)       # Phase 2.2: parameter per mesin (src/search_engines.py)


def skl_objects(row: dict) -> list:
    """-> [(kelas, kunci_ternormalisasi, [(properti, nilai)], )] ; hanya dari kolom Phase 2 yang tidak kosong."""
    et, url, host, title = row["event_type"], row["url"], row["host"], row["page_title"]
    out, used_exe = [], False
    app, fpath = row["app_name"], row["file_path"]
    if et in ("AppExecution", "AppPresence") and app and not app.startswith(NOT_AN_APP):
        pathlike = "\\" in app or "/" in app
        path = fpath or (app if pathlike else "")
        name = re.split(r"[\\/]", app)[-1] if pathlike else app
        props = [("hasFileName", name)] + ([("hasFilePath", path)] if path else [])
        out.append(("ExeFile", "path:" + norm_path(path) if path else "name:" + name.lower(), props)); used_exe = True
    if fpath and not used_exe:
        out.append(("File", norm_path(fpath), [("hasFilePath", fpath)]))
    if row["registry_key"]:
        out.append(("RegistryKey", norm_path(row["registry_key"]), [("hasRegistryKey", row["registry_key"])]))
    if url:
        if et == "WebpageVisit":
            out.append(("Webpage", url, [("hasURL", url)] + ([("hasHost", host)] if host else []) + ([("hasTitle", title)] if title else [])))
        elif et in ("WebSearch", "WebCacheEntry", "FileDownload"):
            q = search_query(url) if et == "WebSearch" else ""
            out.append(("WebResource", url, [("hasURL", url)] + ([("hasHost", host)] if host else []) + ([("hasSearchQuery", q)] if q else [])))
    if et == "CookieAccess" and host:
        out.append(("Cookie", host.lower(), [("hasDomain", host)]))
    return out


# ---------------------------------------------------------------- pembangun
def read_rows(csv_path: Path):
    csv.field_size_limit(1 << 30)
    with open(csv_path, newline="", encoding="utf-8") as f:
        yield from csv.DictReader(f)


def to_xsd_datetime(clean: str) -> str:
    if clean.endswith("+00:00"): return clean[:-6] + "Z"
    if clean.endswith("Z"): return clean
    raise ValueError(f"timestamp_clean bukan UTC: {clean!r}")


def event_iri(sn: str, row: dict) -> str:
    return f"{BASE}{sn}/event/{slug(row['source_file'][:-4] if row['source_file'].endswith('.csv') else row['source_file'])}/{int(row['row_in_file']):05d}"


def build_triples(sn: str, scen: str, rows, op: dict, accounts: dict, stats: dict):
    """Generator (idx, s, p, o); idx = indeks event (0-based) atau -1 untuk operasi TKL."""
    opi = f"{BASE}{sn}/operation/plaso-events"
    yield -1, opi, RDF_TYPE, iri(O("InvestigativeOperation"))
    yield -1, opi, O("hasTool"), lit("log2timeline/Plaso")
    yield -1, opi, O("hasDatasetDOI"), lit("10.5281/zenodo.15493424")
    for fi in op["files"]: yield -1, opi, O("hasInputSHA256"), lit(f"{fi['sha256']}  {fi['file']}")
    yield -1, opi, O("hasRuleTableSHA256"), lit(op["rules_sha256"])
    seen = set(); seen_events = set()
    for idx, row in enumerate(rows):
        ev = event_iri(sn, row)
        if ev in seen_events: raise ValueError(f"IRI event bertabrakan: {ev}")
        seen_events.add(ev)
        et, parser, status = row["event_type"], row["parser"], row["timestamp_status"]
        P = lambda p, o: (idx, ev, O(p), o)
        yield idx, ev, RDF_TYPE, iri(O("Event"))
        if et != UNCLASSIFIED:
            if not re.fullmatch(r"[A-Za-z][A-Za-z0-9]*", et): raise ValueError(f"event_type tidak valid sebagai nama kelas: {et!r}")
            yield idx, ev, RDF_TYPE, iri(O(et))
        info = evtx_info(row) if parser == "winevtx" else None
        if parser == "winevtx": yield idx, ev, RDF_TYPE, iri(O("EventLogEntry"))
        if status == "valid": yield P("hasTimestamp", lit(to_xsd_datetime(row["timestamp_clean"]), XSD_DATETIME))
        for pred, col in (("hasTimestampRaw", "datetime_raw"), ("hasTimestampStatus", "timestamp_status"), ("hasTimestampDescription", "timestamp_desc"),
                          ("hasEventType", "event_type"), ("hasRuleId", "rule_id"), ("hasParser", "parser"), ("hasSource", "source"),
                          ("hasMessage", "message"), ("hasDisplayName", "display_name"), ("hasSourceFile", "source_file")):
            if row[col] != "": yield P(pred, lit(row[col]))
        yield P("hasRowInFile", lit(str(int(row["row_in_file"])), XSD_INTEGER))
        if row["row_hash"]: yield P("hasRowHash", lit(row["row_hash"]))
        if info:
            if info["id"]: yield P("hasEventID", lit(info["id"], XSD_INTEGER))
            if info["provider"]: yield P("hasProvider", lit(info["provider"]))
            if info["computer"]: yield P("hasComputerName", lit(info["computer"]))
        subj, anomalies = subject_of(row, info)
        for a in anomalies: stats["subject_anomalies"][a] += 1
        if info and info["id"] == "4624" and subj and subj["logon_type"] is not None:
            lt = subj["logon_type"]; yield P("hasLogonType", lit(lt, XSD_INTEGER) if lt.isdigit() else lit(lt))
        links = Counter()
        for cls, key, props in skl_objects(row):
            ent = f"{BASE}{sn}/{cls.lower()}/{sha1_16(key)}"
            if ent not in seen:
                seen.add(ent); stats["entities"][cls] += 1
                yield idx, ent, RDF_TYPE, iri(O(cls))
                for p, v in props: yield idx, ent, O(p), lit(v)
            yield P("hasObject", iri(ent)); links[cls] += 1
        if row["app_name"].startswith(NOT_AN_APP) and et in ("AppExecution", "AppPresence"): stats["skipped_not_an_app"][row["app_name"][:30]] += 1
        if subj:
            key = account_key(subj); ent = f"{BASE}{sn}/account/{sha1_16(key)}"
            if ent not in seen:
                seen.add(ent); stats["entities"]["WinUserAccount"] += 1
                a = accounts[key]
                yield idx, ent, RDF_TYPE, iri(O("WinUserAccount"))
                for p, vals in (("hasSID", a["sid"]), ("hasAccountName", a["name"]), ("hasDomain", a["domain"])):
                    for v in vals: yield idx, ent, O(p), lit(v)
            yield P("hasSubject", iri(ent)); links["WinUserAccount"] += 1
            stats["subject_events"][subj["source"]] += 1
        yield P("partOfOperation", iri(opi))
        cv = stats["coverage"][parser]; cv["rows"] += 1
        if links: cv["with_object_or_subject"] += 1
        for c in links: cv[c] += 1
        if row["url"] and not links: stats["url_without_object"][et] += 1                 # punya URL tetapi tidak menghasilkan objek apa pun
        stats["events"] += 1
        stats["status"][status] += 1
        if status != "valid": stats["events_without_timestamp"][status] += 1


def prepass_accounts(rows) -> dict:
    acc = defaultdict(lambda: {"sid": [], "name": [], "domain": []})
    for row in rows:
        info = evtx_info(row) if row["parser"] == "winevtx" else None
        s, _ = subject_of(row, info)
        if not s: continue
        a = acc[account_key(s)]
        for k, v in (("sid", s["sid"] if s["sid"] != "S-1-0-0" else ""), ("name", s["name"]), ("domain", s["domain"])):
            if v and v not in a[k]: a[k].append(v)
    return acc


def build_scenario(scenario: str, root=None, schema_event_types=None) -> dict:
    paths, rp = config.scenario_paths(scenario, root), config.rdf_paths(scenario, root)
    csv_path = paths["processed_dir"] / config.OFFICIAL_PROCESSED
    rep_path = config.preprocess_report_path(scenario, root)
    if not csv_path.exists() or not rep_path.exists():
        return {"scenario": scenario, "status": "INPUT_NOT_FOUND", "expected_path": str(csv_path)}
    r2 = json.loads(rep_path.read_text(encoding="utf-8"))
    csv_sha = hashlib.sha256(csv_path.read_bytes()).hexdigest()
    if csv_sha != r2["output_sha256"]: raise ValueError(f"{csv_path.name} tidak cocok dengan laporan Phase 2.1 (output basi?)")
    sn = "s" + scenario.replace("scenario", "")
    op = {"files": r2["per_file"], "rules_sha256": r2["rules_sha256"]}
    accounts = prepass_accounts(read_rows(csv_path))
    stats = {"events": 0, "entities": Counter(), "coverage": defaultdict(Counter), "subject_events": Counter(), "subject_anomalies": Counter(),
             "skipped_not_an_app": Counter(), "url_without_object": Counter(), "status": Counter(), "events_without_timestamp": Counter()}
    rp["nt"].parent.mkdir(parents=True, exist_ok=True); rp["report_dir"].mkdir(parents=True, exist_ok=True)
    tmp = rp["nt"].with_name(rp["nt"].name + ".tmp"); n = 0; pred = Counter(); sample = []; LIMIT = 50
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            for idx, s, p, o in build_triples(sn, scenario, read_rows(csv_path), op, accounts, stats):
                f.write(nt_line(s, p, o)); n += 1; pred[p.replace(ORD2I, "ord2i:")] += 1
                if idx < LIMIT: sample.append((s, p, o))
        os.replace(tmp, rp["nt"])
    finally:
        if tmp.exists(): tmp.unlink()
    rp["sample_ttl"].write_text(to_turtle(sample), encoding="utf-8")
    sch = schema_triples(schema_event_types or [])
    rep = {"scenario": scenario, "status": "OK", "input_csv": str(csv_path), "input_csv_sha256": csv_sha, "nt_path": str(rp["nt"]),
           "events": stats["events"], "triples": n, "triples_per_event": round(n / max(stats["events"], 1), 2), "nt_bytes": rp["nt"].stat().st_size,
           "nt_sha256": hashlib.sha256(rp["nt"].read_bytes()).hexdigest(), "entities": dict(stats["entities"]),
           "subject_events_by_source": dict(stats["subject_events"]), "subject_anomalies": dict(stats["subject_anomalies"]),
           "skipped_app_name_not_an_app": dict(stats["skipped_not_an_app"]), "url_rows_without_skl_object_by_event_type": dict(stats["url_without_object"]),
           "timestamp_status": dict(stats["status"]), "events_without_timestamp": dict(stats["events_without_timestamp"]),
           "coverage_by_parser": {k: dict(v) for k, v in sorted(stats["coverage"].items(), key=lambda kv: -kv[1]["rows"])},
           "triples_by_predicate": dict(pred.most_common()), "rule_table_sha256": op["rules_sha256"]}
    (rp["report_dir"] / f"build_report_{scenario}.json").write_text(json.dumps(rep, indent=2, ensure_ascii=False), encoding="utf-8")
    return rep


def write_schema(event_types, root=None) -> Path:
    p = config.rdf_paths("scenario1", root)["schema"]; p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text("".join(nt_line(s, pr, o) for s, pr, o in schema_triples(event_types)), encoding="utf-8"); os.replace(tmp, p); return p


def rule_event_types(rules_path) -> list:
    with open(rules_path, newline="", encoding="utf-8") as f: return sorted({r["event_type"] for r in csv.DictReader(f)})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", required=True, choices=["1", "2", "3", "all"])
    ap.add_argument("--rules", default=str(config.RULES_V2))
    a = ap.parse_args()
    types = rule_event_types(a.rules)
    print("schema ->", write_schema(types))
    for s in (config.SCENARIOS if a.scenario == "all" else [f"scenario{a.scenario}"]):
        r = build_scenario(s, schema_event_types=types)
        if r["status"] != "OK": print(f"[{s}] {r['status']}: {r['expected_path']}"); continue
        print(f"[{s}] events={r['events']} triples={r['triples']} ({r['triples_per_event']}/event) entities={r['entities']} subjects={r['subject_events_by_source']} nt_sha256={r['nt_sha256'][:16]}")


if __name__ == "__main__":
    main()
