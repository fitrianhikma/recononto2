"""Metrik TAMBAHAN V1 (kolom baru; M0-M8 di report_metrics.py tidak tersentuh). Rincian dan alasan: docs/REFERENCE.md (bagian 1).

1. Metrik tugas berbasis ground truth (semua skenario), dibangun di atas pemetaan lama GT -> rowHash (D24) dan sitasi [Exx]:
   t_precision, t_recall, t_f1, t_recall_weighted, t_recall_conditional, t_recall_mention, jumlah butir mentah/unik.
   Semantik HIMPUNAN atas identitas butir (tasks.identity). Precision S1 = BATAS BAWAH (GT hanya 8 jenis event terdefinisi).
2. BLEU dan ROUGE-1/2/L untuk S1 saja, bila referensi valid. Implementasi sendiri (rumus eksplisit) + pembanding pustaka bila terpasang.
"""
import math, re
from collections import Counter

import report_metrics as rm

# ---------------------------------------------------------------- tokenisasi (BLEU/ROUGE)
_TOK = re.compile(r"\d{1,2}:\d{2}:\d{2}|[a-z0-9]+(?:[._\-][a-z0-9]+)*")


def strip_report(text: str) -> str:
    """Membuang penanda sitasi [Exx] dan label judul bagian (struktur laporan, bukan isi) sebelum BLEU/ROUGE."""
    return rm.HEAD_RE.sub(" ", rm.CITE_GROUP.sub(" ", text or ""))       # judul dikenali dengan aturan M0 yang sama


def tokens(text: str) -> list:
    """Huruf kecil; token = waktu HH:MM:SS utuh atau deret alfanumerik yang boleh disambung . _ - (mis. firefox.exe, w3schools.com)."""
    return _TOK.findall((text or "").lower())


def _ngrams(t, n): return Counter(tuple(t[i:i + n]) for i in range(len(t) - n + 1))


def bleu(hyp: list, ref: list, max_n: int = 4, smooth: bool = False):
    """BLEU kalimat (Papineni et al., 2002): presisi n-gram terpotong 1..max_n berbobot sama, rata-rata geometrik, brevity penalty.
    smooth=False: bila salah satu presisi n-gram = 0 maka BLEU = 0 (perilaku asli; konsisten dengan nilai 0,0000 di Tabel 4 SIET).
    smooth=True : Chen & Cherry (2014) method1 (pembilang 0 diganti epsilon 0,1), sama dengan nltk SmoothingFunction().method1."""
    if not hyp or not ref: return 0.0
    logs = []
    for n in range(1, max_n + 1):
        h, r = _ngrams(hyp, n), _ngrams(ref, n); den = sum(h.values())
        if den == 0: return 0.0
        num = sum((h & r).values())
        if num == 0:
            if not smooth: return 0.0
            num = 0.1
        logs.append(math.log(num / den))
    c, rl = len(hyp), len(ref); bp = 1.0 if c > rl else math.exp(1 - rl / c)
    return bp * math.exp(sum(logs) / max_n)


def _prf(overlap, hl, rl):
    p = overlap / hl if hl else 0.0; r = overlap / rl if rl else 0.0
    return (2 * p * r / (p + r)) if p + r > 0 else 0.0


def rouge_n(hyp: list, ref: list, n: int) -> float:
    """ROUGE-N F1 (Lin, 2004): tumpang-tindih n-gram terpotong; F1 = rata-rata harmonik presisi dan recall (beta = 1)."""
    h, r = _ngrams(hyp, n), _ngrams(ref, n); return _prf(sum((h & r).values()), sum(h.values()), sum(r.values()))


def lcs_len(a: list, b: list) -> int:
    if len(a) < len(b): a, b = b, a
    prev = [0] * (len(b) + 1)
    for x in a:
        cur = [0]
        for j, y in enumerate(b, 1): cur.append(prev[j - 1] + 1 if x == y else max(prev[j], cur[j - 1]))
        prev = cur
    return prev[-1]


def rouge_l(hyp: list, ref: list) -> float:
    """ROUGE-L F1: LCS atas seluruh teks (satu 'kalimat'), sama dengan rougeL pustaka rouge-score (bukan rougeLsum)."""
    return _prf(lcs_len(hyp, ref), len(hyp), len(ref))


def lexical_scores(hyp_text: str, ref_lines: list, max_n: int = 4, min_ref_tokens: int = 5, prefix: str = "") -> dict:
    """-> kolom BLEU/ROUGE; None + alasan bila referensi tidak valid. Mean = (BLEU + ROUGE-1 + ROUGE-2 + ROUGE-L) / 4 seperti Tabel 4 SIET."""
    ref_text = "\n".join(ref_lines); ref = tokens(ref_text); hyp = tokens(strip_report(hyp_text))
    keys = ["bleu", "bleu_smooth1", "rouge1_f", "rouge2_f", "rougeL_f", "mean_bleu_rouge"]
    out = {f"{prefix}{k}": None for k in keys}
    out[f"{prefix}ref_tokens"], out[f"{prefix}hyp_tokens"] = float(len(ref)), float(len(hyp))
    if not ref_lines or len(ref) < min_ref_tokens:
        out[f"{prefix}reference_valid"] = 0.0; return out
    out[f"{prefix}reference_valid"] = 1.0
    b, b1 = bleu(hyp, ref, max_n), bleu(hyp, ref, max_n, smooth=True)
    r1, r2, rl = rouge_n(hyp, ref, 1), rouge_n(hyp, ref, 2), rouge_l(hyp, ref)
    out.update({f"{prefix}bleu": b, f"{prefix}bleu_smooth1": b1, f"{prefix}rouge1_f": r1, f"{prefix}rouge2_f": r2, f"{prefix}rougeL_f": rl,
                f"{prefix}mean_bleu_rouge": (b + r1 + r2 + rl) / 4})
    return out


def library_scores(hyp_text: str, ref_lines: list) -> dict:
    """Pembanding pustaka (opsional): nltk sentence_bleu (tanpa smoothing dan method1) dengan token yang sama; rouge-score dengan
    tokenizer bawaannya (use_stemmer=False). None bila pustaka tidak terpasang. Selisih kecil wajar karena tokenisasi rouge-score berbeda."""
    out = {"lib_bleu_nltk": None, "lib_bleu_nltk_smooth1": None, "lib_rouge1_f": None, "lib_rouge2_f": None, "lib_rougeL_f": None}
    hyp_s, ref_s = strip_report(hyp_text), "\n".join(ref_lines)
    try:
        import warnings
        from nltk.translate.bleu_score import SmoothingFunction, sentence_bleu
        h, r = tokens(hyp_s), tokens(ref_s)
        if h and r:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                out["lib_bleu_nltk"] = sentence_bleu([r], h)
                out["lib_bleu_nltk_smooth1"] = sentence_bleu([r], h, smoothing_function=SmoothingFunction().method1)
    except ImportError: pass
    try:
        from rouge_score import rouge_scorer
        sc = rouge_scorer.RougeScorer(["rouge1", "rouge2", "rougeL"], use_stemmer=False).score(ref_s, hyp_s)
        out.update({"lib_rouge1_f": sc["rouge1"].fmeasure, "lib_rouge2_f": sc["rouge2"].fmeasure, "lib_rougeL_f": sc["rougeL"].fmeasure})
    except ImportError: pass
    return out


# ---------------------------------------------------------------- metrik tugas (P/R/F1)
def task_metrics(groups: list, evidence: list, cited_ids: set, mentioned_ids: set, precision_hashes: set, prefix: str = "t_") -> dict:
    """groups      : [{identity, mult, hashes}] butir GT unik (tasks.group_items + pemetaan lama -> rowHash)
    evidence       : bukti digest [{id, row_hash, ...}]
    cited_ids      : ID [Exx] SAH yang dikutip laporan (cara hitung sama dengan M1/M5)
    mentioned_ids  : ID yang dikutip ATAU waktunya disebut (cara hitung sama dengan M3b/M5b)
    precision_hashes: rowHash yang dianggap relevan untuk presisi (S1: GT multiple; S2/S3: GT tugas itu)."""
    byid = {e["id"]: e["row_hash"] for e in evidence}
    ch = {byid[i] for i in cited_ids if i in byid}; mh = {byid[i] for i in mentioned_ids if i in byid}; dh = set(byid.values())
    n_u = len(groups); n_raw = sum(g["mult"] for g in groups)
    hit = [bool(g["hashes"] & ch) for g in groups]; hit_m = [bool(g["hashes"] & mh) for g in groups]; ind = [bool(g["hashes"] & dh) for g in groups]
    rec = sum(hit) / n_u if n_u else None
    cited_valid = [i for i in cited_ids if i in byid]
    prec = (sum(1 for i in cited_valid if byid[i] in precision_hashes) / len(cited_valid)) if cited_valid else None
    f1 = (2 * prec * rec / (prec + rec) if (prec is not None and rec is not None and prec + rec > 0) else (0.0 if prec is not None and rec is not None else None))
    return {f"{prefix}gt_items_raw": float(n_raw), f"{prefix}gt_items_unique": float(n_u), f"{prefix}gt_unique_in_digest": float(sum(ind)),
            f"{prefix}gt_unique_unmapped": float(sum(1 for g in groups if not g["hashes"])),
            f"{prefix}precision": prec, f"{prefix}recall": rec, f"{prefix}f1": f1,
            f"{prefix}recall_weighted": (sum(g["mult"] for g, h in zip(groups, hit) if h) / n_raw) if n_raw else None,
            f"{prefix}recall_conditional": (sum(hit) / sum(ind)) if sum(ind) else None,
            f"{prefix}recall_mention": (sum(hit_m) / n_u) if n_u else None}


def cited_and_mentioned(text: str, evidence: list) -> tuple:
    """Persis cara report_metrics.evaluate_run menghitung ID sah yang dikutip dan yang 'disebut' (dikutip atau waktu HH:MM:SS bukti muncul)."""
    ids = {e["id"] for e in evidence}; cited = {c for c in rm.cited_ids(text) if c in ids}
    rtimes = set(rm.TIME_RE.findall(text)); mentioned = cited | {e["id"] for e in evidence if e["timestamp"][11:19] in rtimes}
    return cited, mentioned
