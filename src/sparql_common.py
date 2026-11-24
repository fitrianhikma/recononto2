"""Utilitas SPARQL bersama (Phase 4B). rdflib diimpor malas: logika non-SPARQL dapat diuji tanpa rdflib.

Template (Q12-Q14, Q17) menerima parameter lewat initBindings. TERKUNCI pada data nyata: Event ID harus xsd:integer;
binding bertipe string mengembalikan 0 baris (tidak error)."""
import csv, hashlib, os, re
from pathlib import Path

import config

TEMPLATES = ("Q12_by_provider_eventid", "Q13_message_regex", "Q14_message_literal", "Q17_grep_regex")      # Q17 ditambahkan V1
INT_PARAMS = ("eid",)                                   # parameter template yang harus xsd:integer
_VAR = re.compile(r"[?$](\w+)")


def catalog_queries(qdir=None) -> list:
    """Berkas .rq katalog (bukan template), urut nama. Kosong -> FileNotFoundError (tidak ada fallback)."""
    qdir = Path(qdir) if qdir else config.QUERIES_DIR
    names = sorted(p.stem for p in qdir.glob("*.rq") if p.stem not in TEMPLATES) if qdir.exists() else []
    if not names: raise FileNotFoundError(f"tidak ada query katalog di {qdir}")
    return names


def query_text(name, qdir=None) -> str:
    return (Path(qdir) if qdir else config.QUERIES_DIR).joinpath(f"{name}.rq").read_text(encoding="utf-8")


def load_graph(nt_path):
    import rdflib
    g = rdflib.Graph(); g.parse(str(nt_path), format="nt"); return g


def _rdflib_bindings(b: dict) -> dict:
    from rdflib import Literal, Variable
    return {Variable(k): Literal(v) for k, v in b.items()}          # int -> xsd:integer, str -> xsd:string


def run_select(graph, text, bindings=None, convert=None) -> tuple:
    """-> (kolom:list[str], baris:list[list[str]]); nilai tak terikat -> ''. Urutan baris = urutan hasil query (ORDER BY)."""
    kw = {"initBindings": (convert or _rdflib_bindings)(bindings)} if bindings else {}
    res = graph.query(text, **kw)
    return [str(v) for v in res.vars], [["" if v is None else str(v) for v in row] for row in res]


def run_template(graph, name, queries_dir=None, convert=None, **params) -> list:
    """Jalankan template Q12-Q14. -> list[dict kolom->str]. Template/parameter tak dikenal -> ValueError."""
    if name not in TEMPLATES: raise ValueError(f"bukan template: {name!r}")
    text = query_text(name, queries_dir); declared = set(_VAR.findall(text))
    unknown = sorted(set(params) - declared)
    if unknown: raise ValueError(f"{name}: parameter tidak ada pada query: {unknown}")
    b = {k: (int(v) if k in INT_PARAMS else str(v)) for k, v in params.items()}
    cols, rows = run_select(graph, text, b, convert)
    return [dict(zip(cols, r)) for r in rows]


def write_csv_atomic(path, cols, rows) -> str:
    """UTF-8, '\\n', urutan baris persis; tulis .tmp lalu rename. -> SHA-256 file."""
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True); tmp = path.with_name(path.name + ".tmp")
    try:
        with open(tmp, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f, lineterminator="\n"); w.writerow(cols); w.writerows(rows)
        os.replace(tmp, path)
    finally:
        if tmp.exists(): tmp.unlink()
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prf(retrieved, gt) -> dict:
    """Precision/recall multiset (duplikat dihitung)."""
    from collections import Counter
    R, G = Counter(retrieved), Counter(gt); tp = sum((R & G).values()); r, g = sum(R.values()), sum(G.values())
    p_, r_ = (tp / r if r else None), (tp / g if g else None)
    f1 = (2 * p_ * r_ / (p_ + r_) if (p_ is not None and r_ is not None and p_ + r_ > 0) else (0.0 if (p_ == 0 or r_ == 0) and p_ is not None and r_ is not None else None))
    return {"retrieved": r, "gt": g, "tp": tp, "precision": round(p_, 4) if p_ is not None else None, "recall": round(r_, 4) if r_ is not None else None,
            "f1": round(f1, 4) if f1 is not None else None}                       # f1: tambahan V1 (precision/recall lama tidak berubah)


_EVTX_PAIR = re.compile(r"^\[(\d+) / 0x[0-9a-fA-F]+\].*?Source Name: (.*?)(?: Strings:| Computer Name:|$)")


def evtx_pair(text: str):
    """'[ID / 0x..] Provider identifier: .. Source Name: X ...' -> (X, ID) atau None. Dipakai untuk kunci tugas DAN baris GT."""
    m = _EVTX_PAIR.match(text or "")
    return (m.group(2).strip(), m.group(1)) if m and m.group(2).strip() else None
