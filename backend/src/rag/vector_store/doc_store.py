from __future__ import annotations

import json
import pickle
import re
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from rank_bm25 import BM25Okapi


@dataclass
class StoredDoc:
    pk: str
    text: str
    meta: Dict[str, Any]


def _sha1(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


def bm25_tokens(text: str) -> List[str]:
    """Tokenize for BM25.

    - English words/number/underscore
    - CJK continuous sequences (better for Chinese)
    """
    return re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]+", (text or "").lower())


class LocalDocStore:
    """Local persistent store for text + metadata, plus a BM25 index.

    Why local?
    - We keep Milvus schema minimal (pk + vectors), and store rich metadata locally.
    - This also enables neighbor-chunk expansion and evidence rendering pointers without DB joins.

    Files:
      - docs.jsonl
      - bm25.pkl
    """

    def __init__(self, index_dir: str):
        self.index_dir = Path(index_dir)
        self.index_dir.mkdir(parents=True, exist_ok=True)

        self.docs_path = self.index_dir / "docs.jsonl"
        self.bm25_path = self.index_dir / "bm25.pkl"

        self._docs: Dict[str, StoredDoc] = {}
        self._bm25: Optional[BM25Okapi] = None
        self._bm25_ids: List[str] = []
        self._bm25_tokens: List[List[str]] = []

    # -------------------- persistence --------------------
    def add_many(self, docs: List[StoredDoc]) -> None:
        if not docs:
            return
        with self.docs_path.open("a", encoding="utf-8") as f:
            for d in docs:
                self._docs[d.pk] = d
                f.write(json.dumps({"pk": d.pk, "text": d.text, "meta": d.meta}, ensure_ascii=False) + "\n")

    def load_all(self) -> Dict[str, StoredDoc]:
        if self._docs:
            return self._docs
        if not self.docs_path.exists():
            return {}
        with self.docs_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    pk = str(obj.get("pk"))
                    text = str(obj.get("text", ""))
                    meta = obj.get("meta", {}) or {}
                    self._docs[pk] = StoredDoc(pk=pk, text=text, meta=meta)
                except Exception:
                    continue
        return self._docs

    def get(self, pk: str) -> Optional[StoredDoc]:
        self.load_all()
        return self._docs.get(pk)

    def get_many(self, pks: List[str]) -> List[StoredDoc]:
        self.load_all()
        out: List[StoredDoc] = []
        for pk in pks:
            d = self._docs.get(pk)
            if d is not None:
                out.append(d)
        return out

    # -------------------- neighbor expansion helpers --------------------
    @staticmethod
    def pk_from_doc_chunk(doc_id: str, chunk_index: int) -> str:
        """Recompute pk used during ingest."""
        return _sha1(f"{doc_id}:{int(chunk_index)}")

    def get_by_doc_chunk(self, doc_id: str, chunk_index: int) -> Optional[StoredDoc]:
        pk = self.pk_from_doc_chunk(doc_id, chunk_index)
        return self.get(pk)

    def get_neighbors(self, doc_id: str, chunk_index: int, window: int = 1) -> List[StoredDoc]:
        """Return neighbor chunks around (doc_id, chunk_index).

        Note: This is best-effort. Missing chunks are ignored.
        """
        window = int(window)
        if window <= 0:
            d = self.get_by_doc_chunk(doc_id, chunk_index)
            return [d] if d else []
        out: List[StoredDoc] = []
        for i in range(int(chunk_index) - window, int(chunk_index) + window + 1):
            d = self.get_by_doc_chunk(doc_id, i)
            if d:
                out.append(d)
        return out

    # -------------------- BM25 --------------------
    def rebuild_bm25(self) -> None:
        docs = list(self.load_all().values())
        ids = [d.pk for d in docs]
        corpus_tokens = [bm25_tokens(d.text) for d in docs]
        bm25 = BM25Okapi(corpus_tokens) if corpus_tokens else None

        self._bm25 = bm25
        self._bm25_ids = ids
        self._bm25_tokens = corpus_tokens

        with self.bm25_path.open("wb") as f:
            pickle.dump({"ids": ids, "tokens": corpus_tokens}, f)

    def load_bm25(self) -> None:
        if self._bm25 is not None:
            return
        if not self.bm25_path.exists():
            self.rebuild_bm25()
            return
        try:
            obj = pickle.loads(self.bm25_path.read_bytes())
            ids = list(obj.get("ids", []))
            tokens = list(obj.get("tokens", []))
            self._bm25_ids = ids
            self._bm25_tokens = tokens
            self._bm25 = BM25Okapi(tokens) if tokens else None
        except Exception:
            self.rebuild_bm25()

    def bm25_search(self, query: str, top_k: int = 20) -> List[Tuple[str, float]]:
        self.load_bm25()
        if self._bm25 is None:
            return []
        q_tokens = bm25_tokens(query)
        scores = self._bm25.get_scores(q_tokens)

        ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)[: int(top_k)]
        out: List[Tuple[str, float]] = []
        for idx, sc in ranked:
            if idx < len(self._bm25_ids):
                out.append((self._bm25_ids[idx], float(sc)))
        return out
