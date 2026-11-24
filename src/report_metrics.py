"""Metrik laporan M0-M8 (kode lama eval/08_evaluate_reports.py, fungsi evaluate_run dan seluruh pembantunya TIDAK diubah:
rumus, normalisasi, aturan pembacaan laporan, dan pemetaan ground truth -> rowHash tetap). Driver lama (collect_runs, aggregate,
run_all, report_md, main) dipindah ke 12_evaluate.py karena struktur folder hasil berubah. Metrik tambahan V1: extra_metrics.py.

PHASE 8B (+ patch v2: M6, M2n, M3b/M5b) - Evaluator laporan LLM. TERPISAH dari pipeline utama: hanya MEMBACA digest, evidence, ground truth resmi, dan laporan.

    python3 eval/08_evaluate_reports.py --results results/llm [--digest-dir results/digest] [--tasks data/tasks] [--out results/eval]
Metrik (docs/PHASE6A_DESIGN.md §5 + docs/DECISIONS.md D25-D29): M0 struktur; M1 sitasi; M2/M2n entitas dan angka tak berdukung; M3/M3b cakupan evidence (sitasi / penyebutan); M4 konsistensi sitasi; M5/M5b cakupan ground truth; M6a terpotong; M6b salin prompt.
Hanya run berstatus OK yang dievaluasi (GAGAL_* bukan hasil). Satu run deterministik per kondisi: tidak ada uji signifikansi; ringkasan bersifat deskriptif.
Tidak menghitung BLEU/ROUGE/SBERT.
"""
import csv, glob, json, os, re, sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import events_reader as er

SECTIONS = ("SUMMARY", "TIMELINE", "FINDINGS", "LIMITATIONS")
CITE_GROUP = re.compile(r"\[\s*(E\d+(?:\s*[,;&]\s*E\d+)*)\s*\]", re.I)
TIME_RE = re.compile(r"(?<![\d:])(\d{2}:\d{2}:\d{2})(?![\d:])")
URL_RE = re.compile(r"https?://[^\s\]\)\"'<>]+", re.I)
HOST_TLDS = ("com", "org", "net", "edu", "gov", "io", "co", "cc", "info", "biz", "us", "uk", "de", "ru", "cn", "jp", "fr", "ms")   # operasionalisasi: nama tuan rumah tanpa skema
HOST_RE = re.compile(r"(?<![\w.@/-])((?:[a-z0-9-]+\.)+(?:" + "|".join(HOST_TLDS) + r"))(?![\w-])", re.I)
EXE_RE = re.compile(r"(?<![\w.-])([\w.-]+\.exe)(?![\w-])", re.I)
EVID_RE = re.compile(r"(?:event\s*id|eventid|\bid)\s*[=:]?\s*(\d{3,5})\b", re.I)
NUM_RE = re.compile(r"\d{1,3}(?:,\d{3})+|\d{3,}")
ECHO_THRESHOLD = 0.70                     # M6b: degenerate_echo bila bagian trigram yang ada di prompt >= 0,70 (atau memuat frasa instruksi prompt)
STRUCT = ["m0_structure", "m0_format_exact", "m0_order_unique", "m8_timeline_within_limit", "m8_findings_within_limit", "m8_limitations_within_limit", "m8_summary_within_limit",
          "m8_timeline_lines_start_with_id", "m8_words_within_limit", "m8_plain_text", "m8_compliance_share"]
CONTENT = ["m1_citations_total", "m1_citation_valid_ratio", "m1_timeline_uncited_ratio", "m2_unsupported_rate_all", "m2_unsupported_rate_time", "m2_unsupported_rate_url", "m2_unsupported_rate_host",
           "m2_unsupported_rate_exe", "m2_unsupported_rate_eventid", "m2n_unsupported_number_rate", "m3_evidence_coverage", "m3b_evidence_mention_coverage", "m3_r1_coverage",
           "m4_citation_time_consistency", "m4b_id_label_mismatch_rate", "m5_recall_digest", "m5_recall_report", "m5_recall_conditional", "m5b_recall_report", "m5b_recall_conditional", "m7_key_event_conclusion_recall"]
QUALITY = ["m6a_truncated", "m6b_copy_ratio", "m6b_degenerate_echo", "m6c_template_leak", "m6d_timeline_verbatim_ratio", "pure"]
WANT = STRUCT + CONTENT + QUALITY


# ---------------------------------------------------------------- parsing laporan
def cited_ids(text: str) -> list:
    """Semua ID [Exx] yang disitir (dengan pengulangan), mendukung [E01], [E01, E02]."""
    out = []
    for m in CITE_GROUP.finditer(text): out += [x.upper() for x in re.findall(r"E\d+", m.group(1), re.I)]
    return out


HEAD_RE = re.compile(r"(?im)^(?:[#>*_\-\[(]|\d+[.)]|[ \t])*(" + "|".join(SECTIONS) + r")\b[ \t\]\)*_]*(?::[ \t]*(?:\*\*|__)?|$)")


def heading_sequence(text: str) -> list:
    """Semua judul bagian menurut urutan kemunculan (termasuk duplikat). Bentuk judul: hiasan opsional (#, **, [, nomor) + NAMA + (titik dua | akhir baris); kalimat yang kebetulan diawali kata itu bukan judul."""
    return [m.group(1).upper() for m in HEAD_RE.finditer(text)]


def split_sections(text: str) -> dict:
    """-> {NAMA: isi} untuk kemunculan PERTAMA tiap judul (hiasan markdown/kurung/nomor diterima)."""
    marks = [(m.group(1).upper(), m.start(), m.end()) for m in HEAD_RE.finditer(text)]; out = {}
    for i, (name, s_, e) in enumerate(marks):
        end = marks[i + 1][1] if i + 1 < len(marks) else len(text); out.setdefault(name, text[e:end])
    return out


def format_exact(text: str) -> bool:
    """Format persis dari prompt: tiap judul `NAMA:` huruf besar di awal baris, tanpa hiasan."""
    return set(re.findall(r"(?m)^(" + "|".join(SECTIONS) + r"):", text)) == set(SECTIONS)


def entities(text: str) -> dict:
    """Entitas yang dapat diperiksa terhadap digest: waktu HH:MM:SS, URL, host (tanpa skema), nama .exe, Event ID."""
    urls = [u.rstrip(".,;:") for u in URL_RE.findall(text)]; rest = URL_RE.sub(" ", text)
    return {"time": TIME_RE.findall(text), "url": urls, "host": [h.lower() for h in HOST_RE.findall(rest)], "exe": [x.lower() for x in EXE_RE.findall(text)], "eventid": EVID_RE.findall(text)}


def supported(kind: str, value: str, digest_lc: str, digest_times: set) -> bool:
    if kind == "time": return value in digest_times
    if kind == "eventid": return re.search(r"(?<!\d)" + re.escape(value) + r"(?!\d)", digest_lc) is not None
    return value.lower() in digest_lc


def units(text: str) -> list:
    out = []
    for line in text.splitlines():
        for s in re.split(r"(?<=[.!?])\s+(?=[A-Z\[\-*])", line):
            if s.strip(): out.append(s.strip())
    return out


def ratio(n, d): return (n / d) if d else None


# ---------------------------------------------------------------- M5: ground truth -> himpunan rowHash (identitas baris sepenuh yang tersedia)
def dtk(s):
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})(\.\d+)?", s or "")
    return None if not m else f"{m.group(1)}-{m.group(2)}-{m.group(3)}T{m.group(4)}:{m.group(5)}:{m.group(6)}." + (m.group(7) or ".0")[1:].ljust(6, "0")[:6]


def norm_bs(s: str) -> str: return re.sub(r"\\+", r"\\", s).rstrip("] \n")        # GT S2 memadatkan escape backslash ganda


def index_rows(rows):
    idx = defaultdict(list)
    for r in rows: idx[(r["source_file"], dtk(r["datetime_raw"]))].append(r)
    return idx


def gt_s1(items, sf, idx):
    """Butir GT S1 hanya memuat waktu, plugin dan evidence_source: kunci = berkas + waktu + parser (sufiks plugin) + evidence_source sebagai awalan pesan (penuh, bukan 120 karakter).
    Hasil HIMPUNAN rowHash: baris yang hanya beda timestamp_desc tidak terbedakan oleh GT."""
    out = []
    for g in items:
        ev, plug = g.get("evidence_source", ""), g.get("plugin", "").split("-")[-1]
        c = [r for r in idx.get((sf, dtk(g["date_time_min"])), []) if (r["message"].startswith(ev) or ev.startswith(r["message"])) and (not plug or r["parser"] == plug)]
        out.append({"hashes": {r["row_hash"] for r in c}, "rows": len(c)})
    return out


def gt_s2(items, sf, idx, byfile):
    out = []
    for g in items:
        cands = idx.get((sf, dtk(g["datetime"])), []); gm = norm_bs(g["message"])
        c = [r for r in cands if norm_bs(r["message"]) == gm]                                     # identitas penuh: waktu + pesan penuh
        if not c:
            gs = set(re.findall(r"\{[0-9A-Fa-f-]{36}\}", g["message"])); c = [r for r in cands if gs and gs & set(re.findall(r"\{[0-9A-Fa-f-]{36}\}", r["message"]))]
        if not c:                                                                                  # isi identik dan unik dalam berkas walau waktu GT berbeda (inkonsistensi data resmi)
            same = [r for r in byfile.get(sf, []) if norm_bs(r["message"]) == gm]; c = same if len({r["row_hash"] for r in same}) == 1 else []
        out.append({"hashes": {r["row_hash"] for r in c}, "rows": len(c)})
    return out


def gt_s3(lines):
    out = []
    for l in lines:
        if not l.strip(): continue
        try: f = next(csv.reader([l]))
        except Exception: continue
        if len(f) == 8: out.append({"hashes": {er.row_hash(f)}, "rows": 1})                      # baris CSV lengkap -> hash baris persis
    return out


def load_gt_tasks(scenario, tasks_dir: Path, rows) -> dict:
    """-> {nama_tugas: [ {hashes:set, rows:int} per baris GT ]} (S1 14 langkah; S2 7 tugas; S3 5 tugas)."""
    tasks = {}
    if scenario == "scenario1":
        idx = index_rows(rows)
        for fp in sorted(glob.glob(str(tasks_dir / "event-summarization" / "ground-truth-single" / "*.json"))):
            tasks[Path(fp).stem] = gt_s1(list(json.load(open(fp, encoding="utf-8")).values()), Path(fp).stem + ".csv", idx)
    elif scenario == "scenario2":
        idx = index_rows(rows); byfile = defaultdict(list)
        for r in rows: byfile[r["source_file"]].append(r)
        for fp in sorted(glob.glob(str(tasks_dir / "keyword-analysis" / "ground-truth" / "*.json"))):
            tasks[Path(fp).stem] = gt_s2(json.load(open(fp, encoding="utf-8")), Path(fp).stem + ".csv", idx, byfile)
    elif scenario == "scenario3":
        for fp in sorted(glob.glob(str(tasks_dir / "grep" / "ground-truth" / "*.txt"))):
            tasks[Path(fp).stem] = gt_s3(open(fp, encoding="utf-8", errors="replace").read().splitlines())
    return tasks


def task_coverage(tasks: dict, evidence_hashes: set) -> dict:
    """Tugas tercakup bila >= 1 baris GT-nya (himpunan rowHash-nya) beririsan dengan evidence_hashes."""
    return {t: any(g["hashes"] & evidence_hashes for g in gts) for t, gts in tasks.items()}


# ---------------------------------------------------------------- M6 (terpotong, salin) dan M2n (angka)
def word_trigrams(text: str) -> set:
    w = re.findall(r"[a-z0-9]+", text.lower()); return {tuple(w[i:i + 3]) for i in range(len(w) - 2)}


def copy_ratio(report: str, prompt: str):
    """Bagian trigram kata (huruf kecil) laporan yang juga ada di prompt; None bila laporan < 3 kata."""
    r = word_trigrams(report)
    return None if not r else len(r & word_trigrams(prompt)) / len(r)


def echoes_instructions(report: str) -> bool:
    return "RULES" in report or re.search(r"evidence below", report, re.I) is not None


def numbers_in(text: str) -> list:
    """Bilangan bulat >= 3 digit di luar waktu HH:MM:SS, URL, sitasi [Exx], dan Event ID (yang diperiksa terpisah); pemisah ribuan koma dibuang."""
    t = URL_RE.sub(" ", text); t = TIME_RE.sub(" ", t); t = CITE_GROUP.sub(" ", t); t = EVID_RE.sub(" ", t)
    return [m.replace(",", "") for m in NUM_RE.findall(t)]


# ---------------------------------------------------------------- patch v3: kepatuhan aturan, salinan baris, konsistensi ID-label, peristiwa kunci
MAX_ITEMS = {"TIMELINE": 10, "FINDINGS": 3, "LIMITATIONS": 2}; MAX_SUMMARY_SENTENCES = 2; MAX_WORDS = 220; MAX_DF = 3
_BULLET = re.compile(r"^\s*(?:[-*\u2022]|\d+[.)]|\[E\d+\])")


def compact(s: str) -> str: return re.sub(r"[^a-z0-9]", "", s.lower())


def sentences(text: str) -> list: return [x for x in re.split(r"(?<=[.!?])\s+", " ".join(text.split())) if x.strip()]


def count_items(body: str) -> int:
    """Butir = baris berbutir/bernomor/diawali [Exx] bila ada; selain itu jumlah kalimat paragraf."""
    lines = [l for l in body.splitlines() if l.strip()]; bl = [l for l in lines if _BULLET.match(l)]
    return len(bl) if bl else len(sentences(" ".join(lines)))


def norm_line(l: str) -> str: return " ".join(re.sub(r"^[\s\-*\u2022]+", "", l).lower().split())


# Token terlalu umum / format digest: dibuang dari pencocokan label (kosakata Inggris umum + penanda format digest; BUKAN istilah skenario)
STOP = set("""about above after also among and are because been before being between both but can could did does done each either else ever every few for from had has have her here him his how into its itself just
may might more most much must not now off once only other our out over own same shall she should some such than that the their them then there these they this those through too under until upon very was were what when where
which while who whom why will with within without would your""".split()) | {"acct", "type", "count", "auditing", "security", "windows", "system", "provider", "service", "services", "events", "event", "user", "users", "file", "files", "path", "https", "http", "null"}


def evidence_tokens(evidence: list, max_df: int = MAX_DF) -> dict:
    """{id: token} dari LABEL bukti (>= 4 karakter alfanumerik, bukan angka murni, bukan STOP) yang muncul di <= max_df butir bukti (token terlalu umum dibuang)."""
    raw = {e["id"]: {t for t in re.findall(r"[a-z0-9]{4,}", e["label"].lower()) if not t.isdigit() and t not in STOP} for e in evidence}; df = collections_counter(t for v in raw.values() for t in v)
    return {i: {t for t in v if df[t] <= max_df} for i, v in raw.items()}


GENERIC_TYPE_WORDS = {"app", "web", "page"}      # kata tipe terlalu umum untuk menjadi syarat kecocokan (kata lain dari STOP, mis. user/file/system/event, juga dibuang)


def type_stems(event_type: str) -> set:
    """Kata dari nama tipe event (CamelCase) -> awalan 5 huruf. Kata umum (STOP/GENERIC_TYPE_WORDS) dibuang bila MASIH tersisa >= 2 kata khas
    (UserLogonFailed -> {logon, faile}; LogCleared -> {log, clear}); bila kurang, semua kata dipakai (AppExecution -> {app, execu}; UserLogon -> {user, logon}) agar satu kata umum tidak cukup."""
    words = [w.lower() for w in re.findall(r"[A-Z][a-z]+|[a-z]+", event_type or "") if len(w) >= 3]
    core = {w[:5] for w in words if w not in STOP and w not in GENERIC_TYPE_WORDS}
    return core if len(core) >= 2 else {w[:5] for w in words}


def type_mentioned(text: str, event_type: str) -> bool:
    """Semua kata tipe event (awalan 5 huruf) muncul dalam SATU kalimat teks - parafrasa seperti 'failed ... logon' untuk UserLogonFailed."""
    ts = type_stems(event_type)
    if not ts: return False
    for u in sentences(text):
        words = re.findall(r"[a-z]+", u.lower())
        if all(any(w.startswith(st) for w in words) for st in ts): return True
    return False


def collections_counter(it):
    c = defaultdict(int)
    for x in it: c[x] += 1
    return c


def matches(tokens: set, text_compact: str) -> bool: return any(t in text_compact for t in tokens)


def id_label_consistency(text: str, evidence: list) -> dict:
    """Untuk tiap (kalimat/baris, ID valid yang disitir): konsisten bila token berciri butir itu muncul; BEDA bila tidak, padahal token berciri butir LAIN yang tidak disitir di kalimat itu muncul
    (kalimat jelas menggambarkan butir lain). Selain itu tak tertentukan dan tidak dihitung. Tidak memakai kosakata tipe event."""
    tok = evidence_tokens(evidence); ids = set(tok); ok = bad = 0; examples = []
    for u in units(text):
        cs = [c for c in cited_ids(u) if c in ids]
        if not cs: continue
        uc = compact(CITE_GROUP.sub(" ", u)); cited = set(cs)
        for x in cited:
            if matches(tok[x], uc): ok += 1
            elif any(matches(tok[y], uc) for y in ids - cited): bad += 1; examples.append((x, u[:90]))
    return {"consistent": ok, "mismatch": bad, "rate": ratio(bad, ok + bad), "examples": examples[:5]}


def task_evidence(tasks: dict, evidence: list) -> dict:
    """{tugas: [id bukti]} - bukti digest yang rowHash-nya ada di himpunan rowHash ground truth tugas itu (hanya tugas tercakup digest)."""
    out = {}
    for t, gts in tasks.items():
        hs = set().union(*[g["hashes"] for g in gts]) if gts else set(); ids = [e["id"] for e in evidence if e["row_hash"] in hs]
        if ids: out[t] = ids
    return out


def key_event_conclusion(text: str, evidence: list, tasks: dict):
    """Peristiwa kunci (turunan ground truth): tugas tercakup digest yang buktinya DISEBUT di SUMMARY+FINDINGS (ID dikutip atau token berciri butir itu muncul). -> (rasio, rincian)."""
    te = task_evidence(tasks, evidence)
    if not te: return None, {"tasks_digest": [], "tasks_conclusion": []}
    secs = split_sections(text); concl = (secs.get("SUMMARY", "") + "\n" + secs.get("FINDINGS", "")); cc = compact(CITE_GROUP.sub(" ", concl)); cited = set(cited_ids(concl)); tok = evidence_tokens(evidence)
    bytype = {e["id"]: e.get("event_type", "") for e in evidence}
    hit = [t for t, ids in te.items() if any(i in cited or matches(tok[i], cc) or type_mentioned(CITE_GROUP.sub(" ", concl), bytype[i]) for i in ids)]
    return ratio(len(hit), len(te)), {"tasks_digest": sorted(te), "tasks_conclusion": sorted(hit)}


def rule_compliance(text: str) -> dict:
    """Kepatuhan terhadap aturan prompt; None = bagian tidak ada (tak terdefinisi)."""
    secs = split_sections(text); M = {}
    for name, key in (("TIMELINE", "m8_timeline_within_limit"), ("FINDINGS", "m8_findings_within_limit"), ("LIMITATIONS", "m8_limitations_within_limit")):
        M[key] = None if name not in secs else (1.0 if count_items(secs[name]) <= MAX_ITEMS[name] else 0.0)
    M["m8_summary_within_limit"] = None if "SUMMARY" not in secs else (1.0 if len(sentences(secs["SUMMARY"])) <= MAX_SUMMARY_SENTENCES else 0.0)
    tl = [l for l in secs.get("TIMELINE", "").splitlines() if l.strip()]
    M["m8_timeline_lines_start_with_id"] = None if not tl else (1.0 if all(re.match(r"^[\s\-*\u2022\d.)]*\[?E\d+\]", l, re.I) for l in tl) else 0.0)
    M["m8_words_within_limit"] = 1.0 if len(text.split()) <= MAX_WORDS else 0.0
    M["m8_plain_text"] = 0.0 if re.search(r"\*\*|__|^\s*#{1,6}\s|^\s*\|.*\|\s*$", text, re.M) else 1.0
    vals = [v for k, v in M.items() if v is not None]; M["m8_compliance_share"] = sum(vals) / len(vals) if vals else None
    return M


def load_template_terms(tdir) -> dict:
    """Istilah khas templat prompt: waktu HH:MM:SS di semua templat + nama bertanda kutip pada contoh format (nama rekaan). Dibaca dari berkas templat, bukan ditulis di kode."""
    tdir = Path(tdir); times, names = set(), set()
    for f in sorted(tdir.glob("*.txt")):
        t = f.read_text(encoding="utf-8"); times |= set(TIME_RE.findall(t))
        if f.name == "format_example.txt": names |= {w.lower() for w in re.findall(r'"([A-Za-z][A-Za-z-]{3,})"', t)}
    return {"times": sorted(times), "names": sorted(names)}


def template_leak(text: str, digest_text: str, terms: dict) -> dict:
    """Waktu/nama khas templat yang muncul di laporan padahal TIDAK ada di digest (jadi berasal dari contoh/aturan, bukan dari bukti)."""
    rt = set(TIME_RE.findall(text)); times = [t for t in terms["times"] if t in rt and t not in digest_text]; tl = text.lower(); dl = digest_text.lower()
    names = [n for n in terms["names"] if re.search(r"(?<![a-z])" + re.escape(n) + r"(?![a-z])", tl) and n not in dl]
    return {"count": len(times) + len(names), "times": times, "names": names}


def timeline_verbatim_ratio(text: str, digest_text: str):
    """Bagian baris TIMELINE yang identik (setelah membuang penanda butir, spasi, huruf besar-kecil) dengan baris digest. Menangkap salinan parsial yang lolos ambang trigram."""
    tl = [norm_line(l) for l in split_sections(text).get("TIMELINE", "").splitlines() if l.strip()]; dl = {norm_line(l) for l in digest_text.splitlines() if l.strip()}
    return ratio(sum(1 for l in tl if l in dl), len(tl))


# ---------------------------------------------------------------- evaluasi satu laporan
def evaluate_run(text: str, digest_text: str, evidence: list, tasks: dict = None, prompt_text: str = None, finish_reason: str = None, template_terms: dict = None) -> dict:
    ids = {e["id"] for e in evidence}; byid = {e["id"]: e for e in evidence}; M = {}; detail = {}
    secs = split_sections(text); M["m0_structure"] = 1.0 if all(s in secs for s in SECTIONS) else 0.0; detail["sections_found"] = [s for s in SECTIONS if s in secs]
    seq = heading_sequence(text); M["m0_order_unique"] = 1.0 if seq == list(SECTIONS) else 0.0; M["m0_format_exact"] = 1.0 if format_exact(text) else 0.0; detail["heading_sequence"] = seq
    M.update(rule_compliance(text)); M["m6d_timeline_verbatim_ratio"] = timeline_verbatim_ratio(text, digest_text); M["m7_key_event_conclusion_recall"] = None
    tl_ = template_leak(text, digest_text, template_terms) if template_terms is not None else None; M["m6c_template_leak"] = None if tl_ is None else float(tl_["count"]); detail["template_leak"] = tl_
    cites = cited_ids(text); valid = [c for c in cites if c in ids]
    M["m1_citation_valid_ratio"] = ratio(len(valid), len(cites)); M["m1_citations_total"] = float(len(cites)); detail["citations_total"] = len(cites); detail["citations_invalid"] = sorted({c for c in cites if c not in ids})
    tl = [l for l in secs.get("TIMELINE", "").splitlines() if l.strip()]; M["m1_timeline_uncited_ratio"] = ratio(sum(1 for l in tl if not CITE_GROUP.search(l)), len(tl)); detail["timeline_lines"] = len(tl)
    dl = digest_text.lower(); dtimes = set(TIME_RE.findall(digest_text)); ent = entities(text); tot = bad = 0
    for kind in ("time", "url", "host", "exe", "eventid"):
        vals = ent[kind]; b = sum(1 for v in vals if not supported(kind, v, dl, dtimes)); M[f"m2_unsupported_rate_{kind}"] = ratio(b, len(vals)); tot += len(vals); bad += b
        detail[f"m2_{kind}"] = {"total": len(vals), "unsupported": b, "unsupported_values": sorted({v for v in vals if not supported(kind, v, dl, dtimes)})[:10]}
    M["m2_unsupported_rate_all"] = ratio(bad, tot); detail["m2_total"] = tot; detail["m2_unsupported"] = bad
    dnums = set(re.findall(r"\d+", digest_text)); nums = numbers_in(text); nb = [n for n in nums if n not in dnums]
    M["m2n_unsupported_number_rate"] = ratio(len(nb), len(nums)); detail["m2n"] = {"total": len(nums), "unsupported": len(nb), "unsupported_values": sorted(set(nb))[:10]}
    cited = set(valid); M["m3_evidence_coverage"] = ratio(len(cited), len(ids)); r1 = {e["id"] for e in evidence if e.get("r1")}; M["m3_r1_coverage"] = ratio(len(cited & r1), len(r1))
    rtimes = set(TIME_RE.findall(text)); mentioned = cited | {e["id"] for e in evidence if e["timestamp"][11:19] in rtimes}     # disebut = ID dikutip ATAU waktu HH:MM:SS bukti muncul persis
    M["m3b_evidence_mention_coverage"] = ratio(len(mentioned), len(ids)); detail["mentioned_ids"] = sorted(mentioned)
    chk = ok = 0
    for u in units(text):
        us = TIME_RE.findall(u); cs = [c for c in cited_ids(u) if c in byid]
        if us and cs:
            chk += 1; times = {byid[c]["timestamp"][11:19] for c in cs}; ok += all(t in times for t in us)
    M["m4_citation_time_consistency"] = ratio(ok, chk); detail["m4_units_checked"] = chk
    idl = id_label_consistency(text, evidence); M["m4b_id_label_mismatch_rate"] = idl["rate"]; detail["m4b"] = idl
    trunc = None if finish_reason is None else (1.0 if finish_reason == "length" else 0.0); M["m6a_truncated"] = trunc
    cr = copy_ratio(text, prompt_text) if prompt_text else None; M["m6b_copy_ratio"] = cr
    echo = 1.0 if ((cr is not None and cr >= ECHO_THRESHOLD) or echoes_instructions(text)) else 0.0; M["m6b_degenerate_echo"] = echo
    M["pure"] = 1.0 if (trunc != 1.0 and echo == 0.0) else 0.0                    # subset "murni": tidak terpotong dan bukan degenerate_echo
    if tasks:
        dig = {e["row_hash"] for e in evidence}; cit = {byid[c]["row_hash"] for c in cited}; men = {byid[c]["row_hash"] for c in mentioned}
        d, r, rb = task_coverage(tasks, dig), task_coverage(tasks, cit), task_coverage(tasks, men); n = len(tasks); nd, nr, nrb = sum(d.values()), sum(r.values()), sum(rb.values())
        M["m5_recall_digest"] = ratio(nd, n); M["m5_recall_report"] = ratio(nr, n); M["m5_recall_conditional"] = ratio(nr, nd); M["m5b_recall_report"] = ratio(nrb, n); M["m5b_recall_conditional"] = ratio(nrb, nd)
        M["m7_key_event_conclusion_recall"], detail["m7"] = key_event_conclusion(text, evidence, tasks)
        detail["m5"] = {"tasks": n, "digest_covered": nd, "report_covered": nr, "report_covered_by_mention": nrb, "tasks_digest": d, "tasks_report": r, "tasks_report_mention": rb}
    return {"metrics": M, "detail": detail}


# ---------------------------------------------------------------- penyatuan dan keluaran
def fmt(v): return "" if v is None else f"{v:.4f}"


def write_csv(path: Path, header, rows):
    path.parent.mkdir(parents=True, exist_ok=True); tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n"); w.writerow(header); w.writerows(rows)
    os.replace(tmp, path)


def mean(xs):
    xs = [x for x in xs if x is not None]; return sum(xs) / len(xs) if xs else None
