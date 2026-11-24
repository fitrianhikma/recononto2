"""Helper RDF tanpa dependency: istilah, escaping N-Triples, penulis N-Triples/Turtle, IRI deterministik."""
import hashlib, re

ORD2I = "https://example.org/thesis-ord2i#"        # namespace IMPLEMENTASI (bukan IRI resmi ORD2I)
BASE = "https://example.org/thesis/"
XSD = "http://www.w3.org/2001/XMLSchema#"
RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
RDFS = "http://www.w3.org/2000/01/rdf-schema#"
OWL = "http://www.w3.org/2002/07/owl#"
RDF_TYPE = RDF + "type"
XSD_DATETIME, XSD_INTEGER = XSD + "dateTime", XSD + "integer"

_IRI_BAD = re.compile(r'[\x00-\x20<>"{}|^`\\]')
_LIT_ESC = re.compile(r'[\\"\n\r\t\x00-\x1f\x7f]')
_MAP = {"\\": "\\\\", '"': '\\"', "\n": "\\n", "\r": "\\r", "\t": "\\t"}


def iri(v: str) -> tuple:
    if _IRI_BAD.search(v): raise ValueError(f"IRI tidak valid: {v!r}")
    return ("iri", v)


def lit(v: str, dt=None) -> tuple:
    return ("lit", v, dt)


def escape_literal(v: str) -> str:
    return _LIT_ESC.sub(lambda m: _MAP.get(m.group(0)) or "\\u%04X" % ord(m.group(0)), v)


def nt_term(t: tuple) -> str:
    if t[0] == "iri": return f"<{t[1]}>"
    return f'"{escape_literal(t[1])}"' + (f"^^<{t[2]}>" if t[2] else "")


def nt_line(s: str, p: str, o: tuple) -> str:
    return f"<{s}> <{p}> {nt_term(o)} .\n"


def slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)


def sha1_16(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:16]


def norm_path(v: str) -> str:
    return v.lower().replace("/", "\\")


def to_turtle(triples: list) -> str:
    """Turtle sederhana untuk sampel yang dibaca manusia (urutan subjek = kemunculan pertama)."""
    pre = [("ord2i", ORD2I), ("xsd", XSD), ("rdf", RDF), ("rdfs", RDFS), ("owl", OWL)]
    def short(u):
        if u == RDF_TYPE: return "a"
        for k, ns in pre:
            if u.startswith(ns) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", u[len(ns):] or "x"): return f"{k}:{u[len(ns):]}"
        return f"<{u}>"
    def term(t):
        if t[0] == "iri": return short(t[1])
        return f'"{escape_literal(t[1])}"' + (f"^^{short(t[2])}" if t[2] else "")
    by = {}
    for s, p, o in triples: by.setdefault(s, []).append((p, o))
    out = [f"@prefix {k}: <{ns}> ." for k, ns in pre] + [""]
    for s, po in by.items():
        out.append(f"<{s}>")
        out += [f"    {short(p)} {term(o)}" + (" ;" if i < len(po) - 1 else " .") for i, (p, o) in enumerate(po)]
        out.append("")
    return "\n".join(out) + "\n"


_NT_RE = re.compile(r'^<([^<>"\s]*)> <([^<>"\s]*)> (<[^<>"\s]*>|"(?:[^"\\\n\r]|\\["\\nrtbf]|\\u[0-9A-Fa-f]{4}|\\U[0-9A-Fa-f]{8})*"(?:\^\^<[^<>"\s]*>)?) \.$')
_LIT_RE = re.compile(r'^"((?:[^"\\]|\\.)*)"(?:\^\^<([^>]*)>)?$', re.S)
_UNESC = re.compile(r'\\(["\\nrtbf]|u[0-9A-Fa-f]{4}|U[0-9A-Fa-f]{8})')


def unescape_literal(v: str) -> str:
    def f(m):
        g = m.group(1)
        return {"n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f", '"': '"', "\\": "\\"}.get(g) or chr(int(g[1:], 16))
    return _UNESC.sub(f, v)


def parse_nt_line(line: str):
    """-> (s, p, o) dengan o = ('iri', v) | ('lit', v, dt); ValueError bila sintaks salah."""
    m = _NT_RE.match(line.rstrip("\n"))
    if not m: raise ValueError(f"baris N-Triples tidak valid: {line[:120]!r}")
    s, p, o = m.groups()
    if o.startswith("<"): return s, p, ("iri", o[1:-1])
    lm = _LIT_RE.match(o)
    return s, p, ("lit", unescape_literal(lm.group(1)), lm.group(2))
