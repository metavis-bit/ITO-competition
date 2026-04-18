from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from ..utils.text import sanitize_collection_name


@dataclass
class MilvusConfig:
    """Milvus connection & index configuration."""

    uri: str
    metric_type: str = "COSINE"  # COSINE | IP | L2
    index_type: str = "HNSW"  # HNSW | IVF_FLAT | AUTOINDEX etc.
    index_params: Dict[str, Any] | None = None
    search_params: Dict[str, Any] | None = None

    # ---- hybrid / sparse ----
    enable_sparse: bool = False
    sparse_field: str = "sparse_vector"
    sparse_index_params: Dict[str, Any] | None = None
    sparse_metric_type: str = "IP"  # for sparse vectors, Milvus supports IP/BM25

    # ---- field names ----
    pk_field: str = "pk"
    dense_field: str = "vector"


class MilvusVectorStore:
    """Milvus-backed vector store.

    Supports both:
      - Milvus server (uri like "127.0.0.1:19530" or http(s) endpoint)
      - Milvus Lite (uri as local file path, e.g. "./rag_store/milvus.db").

    We intentionally store only (pk, vectors...) in Milvus, and keep text/metadata in LocalDocStore.

    Dense-only mode:
      pk + dense_vector

    Hybrid mode (BGE-M3 dense + sparse):
      pk + dense_vector + sparse_vector (DataType.SPARSE_FLOAT_VECTOR)
    """

    def __init__(self, cfg: MilvusConfig):
        self.cfg = cfg
        self._connected = False
        self._collections: Dict[str, Any] = {}
        self._connect()

    # ---------------------------- connection ----------------------------
    def _connect(self) -> None:
        if self._connected:
            return
        try:
            from pymilvus import connections
        except Exception as e:
            raise RuntimeError(
                "pymilvus is required. Please install pymilvus (and optionally milvus-lite).\n"
                "  pip install pymilvus milvus-lite"
            ) from e

        uri = str(self.cfg.uri)
        uri = os.getenv("MILVUS_URI", uri)

        kwargs: Dict[str, Any] = {}
        if uri.startswith("http://") or uri.startswith("https://"):
            kwargs["uri"] = uri
        elif uri.endswith(".db") or uri.endswith(".sqlite") or os.path.sep in uri:
            # Milvus Lite typically uses a local file path
            kwargs["uri"] = uri
        else:
            # host:port
            if ":" in uri:
                host, port = uri.split(":", 1)
                kwargs["host"] = host
                kwargs["port"] = int(port)
            else:
                kwargs["host"] = uri
                kwargs["port"] = 19530

        connections.connect(alias="default", **kwargs)
        self._connected = True

    # ---------------------------- schema & collection ----------------------------
    def _collection(self, raw_name: str, dim: int):
        from pymilvus import Collection, FieldSchema, CollectionSchema, DataType, utility

        name = sanitize_collection_name(raw_name)
        if name in self._collections:
            return self._collections[name]

        if utility.has_collection(name):
            coll = Collection(name)
        else:
            fields: List[FieldSchema] = [
                FieldSchema(
                    name=self.cfg.pk_field,
                    dtype=DataType.VARCHAR,
                    is_primary=True,
                    auto_id=False,
                    max_length=64,
                ),
                FieldSchema(
                    name=self.cfg.dense_field,
                    dtype=DataType.FLOAT_VECTOR,
                    dim=int(dim),
                ),
            ]

            if self.cfg.enable_sparse:
                # Milvus supports sparse vector input as dict: {dim_index: weight, ...}
                fields.append(
                    FieldSchema(
                        name=self.cfg.sparse_field,
                        dtype=DataType.SPARSE_FLOAT_VECTOR,
                    )
                )

            schema = CollectionSchema(fields, description="edu_rag vectors")
            coll = Collection(name, schema)

            # ---- dense index ----
            index_params = self.cfg.index_params or {}
            metric = (self.cfg.metric_type or "COSINE").upper()
            itype = (self.cfg.index_type or "AUTOINDEX").upper()

            if itype == "HNSW":
                # ✅ FIX: correct index_type should be HNSW (not IVF_FLAT)
                params = {
                    "index_type": "HNSW",
                    "metric_type": metric,
                    "params": {
                        "M": int(index_params.get("M", 16)),
                        "efConstruction": int(index_params.get("efConstruction", 200)),
                    },
                }
            elif itype == "IVF_FLAT":
                params = {
                    "index_type": "IVF_FLAT",
                    "metric_type": metric,
                    "params": {"nlist": int(index_params.get("nlist", 1024))},
                }
            else:
                # AUTOINDEX or others
                params = {"index_type": self.cfg.index_type, "metric_type": metric, "params": index_params}

            coll.create_index(field_name=self.cfg.dense_field, index_params=params)

            # ---- sparse index ----
            if self.cfg.enable_sparse:
                sp_params = self.cfg.sparse_index_params or {}
                # Recommended defaults from Milvus docs: SPARSE_INVERTED_INDEX + IP metric
                sp_index = {
                    "index_type": sp_params.get("index_type", "SPARSE_INVERTED_INDEX"),
                    "metric_type": (self.cfg.sparse_metric_type or "IP").upper(),
                    "params": sp_params.get("params", {"inverted_index_algo": "DAAT_MAXSCORE"}),
                }
                try:
                    coll.create_index(field_name=self.cfg.sparse_field, index_params=sp_index)
                except Exception:
                    # Older Milvus or pymilvus may not support sparse index creation; ignore and fallback to FLAT.
                    pass

        # load collection to memory for search
        try:
            coll.load()
        except Exception:
            pass

        self._collections[name] = coll
        return coll

    # ---------------------------- CRUD ----------------------------
    def upsert(
        self,
        collection: str,
        pks: List[str],
        dense_vectors: List[List[float]],
        dim: int,
        sparse_vectors: Optional[List[Dict[int, float]]] = None,
    ) -> None:
        """Insert vectors.

        NOTE: Milvus insert doesn't replace existing by default.
        For deterministic pipelines we usually reset store dir; duplicates are acceptable for demo.
        """
        if not pks:
            return
        coll = self._collection(collection, dim)

        if self.cfg.enable_sparse:
            if sparse_vectors is None:
                # allow inserting empty sparse (all-zero) vectors
                sparse_vectors = [{} for _ in pks]
            if len(sparse_vectors) != len(pks):
                raise ValueError("sparse_vectors length must match pks")
            coll.insert([pks, dense_vectors, sparse_vectors])
        else:
            coll.insert([pks, dense_vectors])

        try:
            coll.flush()
        except Exception:
            pass

    # ---------------------------- search APIs ----------------------------
    def search_dense(
        self,
        collection: str,
        query_vectors: List[List[float]],
        dim: int,
        top_k: int,
    ) -> List[List[Tuple[str, float]]]:
        coll = self._collection(collection, dim)

        metric = (self.cfg.metric_type or "COSINE").upper()
        search_params = self.cfg.search_params or {}
        itype = (self.cfg.index_type or "AUTOINDEX").upper()

        if itype == "HNSW":
            params = {"metric_type": metric, "params": {"ef": int(search_params.get("ef", 64))}}
        elif itype.startswith("IVF"):
            params = {"metric_type": metric, "params": {"nprobe": int(search_params.get("nprobe", 16))}}
        else:
            params = {"metric_type": metric, "params": search_params}

        res = coll.search(
            data=query_vectors,
            anns_field=self.cfg.dense_field,
            param=params,
            limit=int(top_k),
            output_fields=[self.cfg.pk_field],
        )

        out: List[List[Tuple[str, float]]] = []
        for hits in res:
            row: List[Tuple[str, float]] = []
            for h in hits:
                pk = str(h.id)
                dist = float(getattr(h, "distance", 0.0))
                score = -dist if metric == "L2" else dist
                row.append((pk, score))
            out.append(row)
        return out

    def search_sparse(
        self,
        collection: str,
        query_sparse_vectors: List[Dict[int, float]],
        dim: int,
        top_k: int,
    ) -> List[List[Tuple[str, float]]]:
        """Search the sparse vector field (if enabled)."""
        if not self.cfg.enable_sparse:
            return [[] for _ in query_sparse_vectors]

        coll = self._collection(collection, dim)
        metric = (self.cfg.sparse_metric_type or "IP").upper()

        # Sparse search params: drop_ratio_search etc (optional)
        search_params = (self.cfg.sparse_index_params or {}).get("search_params", {}) if isinstance(self.cfg.sparse_index_params, dict) else {}
        params = {"metric_type": metric, "params": search_params or {}}

        res = coll.search(
            data=query_sparse_vectors,
            anns_field=self.cfg.sparse_field,
            param=params,
            limit=int(top_k),
            output_fields=[self.cfg.pk_field],
        )

        out: List[List[Tuple[str, float]]] = []
        for hits in res:
            row: List[Tuple[str, float]] = []
            for h in hits:
                pk = str(h.id)
                dist = float(getattr(h, "distance", 0.0))
                score = dist  # IP: higher is better
                row.append((pk, score))
            out.append(row)
        return out

    def hybrid_search(
        self,
        collection: str,
        query_dense: List[List[float]],
        query_sparse: List[Dict[int, float]],
        dim: int,
        top_k: int,
        ranker: str = "rrf",
        rrf_k: int = 60,
        weights: Optional[List[float]] = None,
        dense_k: Optional[int] = None,
        sparse_k: Optional[int] = None,
    ) -> List[List[Tuple[str, float]]]:
        """Milvus native hybrid_search() if available.

        Falls back to two separate searches if hybrid_search API is not available.

        ranker:
          - "rrf" (RRFRanker)
          - "weighted" (WeightedRanker)
        """
        if not self.cfg.enable_sparse:
            # fallback to dense only
            return self.search_dense(collection, query_dense, dim=dim, top_k=top_k)

        coll = self._collection(collection, dim)

        dense_k = int(dense_k or top_k)
        sparse_k = int(sparse_k or top_k)

        # Build AnnSearchRequest list
        try:
            from pymilvus import AnnSearchRequest, RRFRanker, WeightedRanker
        except Exception:
            AnnSearchRequest = None  # type: ignore

        if AnnSearchRequest is None or not hasattr(coll, "hybrid_search"):
            # Fallback: do separate searches and fuse externally (scores are not comparable)
            dense_res = self.search_dense(collection, query_dense, dim=dim, top_k=dense_k)
            sparse_res = self.search_sparse(collection, query_sparse, dim=dim, top_k=sparse_k)
            # Return concatenated lists for external fusion usage
            out: List[List[Tuple[str, float]]] = []
            for d, s in zip(dense_res, sparse_res):
                out.append(d + s)
            return out

        metric_dense = (self.cfg.metric_type or "COSINE").upper()
        itype = (self.cfg.index_type or "AUTOINDEX").upper()
        dense_search_params = self.cfg.search_params or {}
        if itype == "HNSW":
            dense_param = {"metric_type": metric_dense, "params": {"ef": int(dense_search_params.get("ef", 64))}}
        elif itype.startswith("IVF"):
            dense_param = {"metric_type": metric_dense, "params": {"nprobe": int(dense_search_params.get("nprobe", 16))}}
        else:
            dense_param = {"metric_type": metric_dense, "params": dense_search_params}

        metric_sparse = (self.cfg.sparse_metric_type or "IP").upper()
        sparse_search_params = (self.cfg.sparse_index_params or {}).get("search_params", {}) if isinstance(self.cfg.sparse_index_params, dict) else {}
        sparse_param = {"metric_type": metric_sparse, "params": sparse_search_params or {}}

        results: List[List[Tuple[str, float]]] = []
        for dv, sv in zip(query_dense, query_sparse):
            reqs = [
                AnnSearchRequest(data=[dv], anns_field=self.cfg.dense_field, param=dense_param, limit=dense_k),
                AnnSearchRequest(data=[sv], anns_field=self.cfg.sparse_field, param=sparse_param, limit=sparse_k),
            ]
            if ranker.lower() == "weighted":
                # weights length must equal number of reqs
                w = weights or [0.5, 0.5]
                rerank = WeightedRanker(*[float(x) for x in w])
            else:
                rerank = RRFRanker(int(rrf_k))

            res = coll.hybrid_search(reqs=reqs, rerank=rerank, limit=int(top_k), output_fields=[self.cfg.pk_field])
            # res is a list with one element (hits) because we queried one vector
            hits = res[0] if res else []
            row: List[Tuple[str, float]] = []
            for h in hits:
                pk = str(h.id)
                dist = float(getattr(h, "distance", 0.0))
                # For hybrid search, distance is already a reranked score; treat higher as better.
                row.append((pk, dist))
            results.append(row)
        return results

    # ---------------------------- admin ----------------------------
    def drop_collection(self, raw_name: str) -> None:
        from pymilvus import utility

        name = sanitize_collection_name(raw_name)
        if utility.has_collection(name):
            utility.drop_collection(name)
        self._collections.pop(name, None)
