"""Pembacaan kata kunci tugas (S2, S3) - tambahan V1, dipakai stage 01 (audit) dan stage 06 (validitas pengambilan).

S2 additional-keywords.json (data resmi, TIDAK diubah) memuat kurung siku tanpa escape, mis. "[104 / 0x0068] Provider ...".
Dalam regex, "[104 / 0x0068]" adalah character class (cocok satu karakter), sehingga pola as-is tidak pernah cocok dengan pesan Plaso
"[104 / 0x0068] Provider identifier: ...". Ini akar masalah recall 0 untuk regex/literal pada delete-logs di audit lama.

`literal_brackets` = OPERASIONALISASI PENELITIAN (bukan definisi dataset): kelompok [...] TANPA rentang karakter (x-y) dibaca sebagai teks
literal Plaso; kelompok dengan rentang (mis. [a-f0-9\\-]) tetap character class. Metode lama (as-is) tetap dijalankan dan dilaporkan berdampingan.
"""
import re

_BRACKET = re.compile(r"(?<!\\)\[((?:\\.|[^\]\\])*)(?<!\\)\]")
_RANGE = re.compile(r"\w-\w")


def literal_brackets(pattern: str) -> str:
    def fix(m):
        body = m.group(1)
        if _RANGE.search(body): return m.group(0)                      # rentang karakter -> character class asli
        return re.escape("[") + re.escape(body.replace("\\", "")) + re.escape("]") if "\\" not in body else re.escape("[") + body + re.escape("]")
    return _BRACKET.sub(fix, pattern)


def compiles(pattern: str) -> bool:
    try: re.compile(pattern); return True
    except re.error: return False
