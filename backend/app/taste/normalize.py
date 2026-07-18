import re
import unicodedata

_FEAT_PAREN = re.compile(r"[\(\[][^)\]]*\bfeat\.?[^)\]]*[\)\]]", re.IGNORECASE)
_FEAT_TAIL = re.compile(r"\s+-?\s*feat\.?\s+.*$", re.IGNORECASE)
_PUNCT = re.compile(r"[^\w\s]")
_WS = re.compile(r"\s+")


def norm_name(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = _FEAT_PAREN.sub("", s)
    s = _FEAT_TAIL.sub("", s)
    s = _PUNCT.sub("", s.lower())
    return _WS.sub(" ", s).strip()


def norm_key(artist: str, title: str = "") -> str:
    if title:
        return f"{norm_name(artist)}|{norm_name(title)}"
    return norm_name(artist)
