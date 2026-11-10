"""Retrieval over the lender's loan agreement (the "R" in RAG): Okapi BM25, written out in full.

Small, dependency-free and explainable: the agreement has a dozen sections, so a keyword
ranking with the English text plus a Hinglish summary per section is enough, fast, and easy
to test. Answers cite the section id so a borrower (or a reviewer) can check them.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import yaml

_STOP = {"the", "a", "an", "of", "to", "is", "and", "or", "in", "on", "for", "by", "be", "as",
         "at", "it", "my", "me", "i", "if", "what", "how", "will", "do", "does", "can", "ka",
         "ki", "ke", "ko", "hai", "hain", "kya", "se", "mein", "par", "aur", "toh", "this",
         "that", "your", "you", "our", "we", "now", "here", "there", "with", "about", "any",
         "abhi", "yeh", "woh", "main", "mera", "meri", "aap", "aapka"}
_SYNONYMS = {"penalty": "late", "jurmana": "late", "fine": "late", "fee": "charge",
             "charges": "charge", "cibil": "credit", "score": "credit", "shikayat": "complaint",
             "complain": "complaint", "foreclose": "foreclosure", "prepay": "prepayment",
             "kisht": "emi", "tareekh": "date", "naukri": "job", "bimari": "medical",
             "half": "part", "partial": "part", "thoda": "part", "aadha": "part",
             "recording": "recorded", "record": "recorded"}


def tokens(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+|[ऀ-ॿ]+", text.lower())
    return [_SYNONYMS.get(w, w) for w in words if w not in _STOP]


@dataclass(frozen=True)
class Section:
    id: str
    title: str
    text: str
    hi: str


class Agreement:
    def __init__(self, document: str, sections: list[Section], k1: float = 1.5, b: float = 0.75):
        self.document = document
        self.sections = sections
        self.k1, self.b = k1, b
        self.docs = [tokens(f"{s.title} {s.title} {s.text} {s.hi}") for s in sections]
        self.avg_len = sum(map(len, self.docs)) / len(self.docs)
        df = Counter(t for d in self.docs for t in set(d))
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}
        self.tf = [Counter(d) for d in self.docs]

    @classmethod
    def load(cls, path: str | Path) -> Agreement:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return cls(data["document"], [Section(str(s["id"]), s["title"], s["text"], s["hi"])
                                      for s in data["sections"]])

    def score(self, query: str) -> list[tuple[float, Section]]:
        q = tokens(query)
        out = []
        for i, sec in enumerate(self.sections):
            tf, length, s = self.tf[i], len(self.docs[i]), 0.0
            for t in q:
                if t in tf:
                    s += self.idf[t] * tf[t] * (self.k1 + 1) / (
                        tf[t] + self.k1 * (1 - self.b + self.b * length / self.avg_len))
            out.append((s, sec))
        return sorted(out, key=lambda x: -x[0])

    def search(self, query: str, k: int = 2) -> list[Section]:
        return [sec for s, sec in self.score(query)[:k] if s > 0]
