"""pgvector (PostgreSQL) implementation of :class:`VectorDBBackend`.

This wraps ``psycopg2`` and the ``pgvector`` extension behind the abstract
backend interface so the benchmark pipeline is completely database-agnostic.

Requirements::

    pip install psycopg2-binary pgvector

The target PostgreSQL server must have the ``vector`` extension installed::

    CREATE EXTENSION IF NOT EXISTS vector;
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import numpy as np

from ..base import CollectionInfo, IndexProgress, VectorDBBackend

logger = logging.getLogger(__name__)

# Mapping from the generic metric names used by the benchmark framework
# to the pgvector operator classes required by each index type.
_METRIC_TO_HNSW_OPS: Dict[str, str] = {
    "L2": "vector_l2_ops",
    "COSINE": "vector_cosine_ops",
    "IP": "vector_ip_ops",
}

_METRIC_TO_IVFFLAT_OPS: Dict[str, str] = {
    "L2": "vector_l2_ops",
    "COSINE": "vector_cosine_ops",
    "IP": "vector_ip_ops",
}

# The SQL distance operator used at query time for each metric.
_METRIC_TO_OPERATOR: Dict[str, str] = {
    "L2": "<->",
    "COSINE": "<=>",
    "IP": "<#>",
}


class PGVectorBackend(VectorDBBackend):
    """Concrete backend for PostgreSQL + pgvector."""

    def __init__(self) -> None:
        self._conn = None  # type: Any   # psycopg2 connection

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def connect(
        self,
        host: str = "127.0.0.1",
        port: str = "5432",
        dbname: str = "postgres",
        user: str = "postgres",
        password: str = "",
        **kwargs,
    ) -> None:
        import psycopg2
        from pgvector.psycopg2 import register_vector

        self._conn = psycopg2.connect(
            host=host,
            port=port,
            dbname=dbname,
            user=user,
            password=password,
        )
        self._conn.autocommit = True
        register_vector(self._conn)

        # Ensure the vector extension exists.
        with self._conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
        logger.info("Connected to PostgreSQL at %s:%s (db=%s)", host, port, dbname)

    def disconnect(self) -> None:
        if self._conn and not self._conn.closed:
            self._conn.close()
        self._conn = None
        logger.info("Disconnected from PostgreSQL")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _cur(self):
        """Return a new cursor, raising if not connected."""
        if self._conn is None or self._conn.closed:
            raise RuntimeError("Not connected to PostgreSQL")
        return self._conn.cursor()

    @staticmethod
    def _table(name: str) -> str:
        """Sanitize a collection name for use as a SQL identifier."""
        import psycopg2.extensions
        return psycopg2.extensions.quote_ident(name) if hasattr(
            psycopg2.extensions, "quote_ident"
        ) else f'"{name}"'

    @staticmethod
    def _index_name(table: str, suffix: str = "vec_idx") -> str:
        return f"{table}_{suffix}"

    # ------------------------------------------------------------------
    # Collection management
    # ------------------------------------------------------------------
    def create_collection(
        self,
        name: str,
        dimension: int,
        metric_type: str = "COSINE",
        index_type: str = "HNSW",
        index_params: Optional[Dict[str, Any]] = None,
        num_shards: int = 1,
        force: bool = False,
    ) -> CollectionInfo:
        table = self._table(name)
        idx_name = self._index_name(name)

        if self.collection_exists(name):
            if force:
                self.drop_collection(name)
            else:
                raise ValueError(
                    f"Table '{name}' already exists. Use force=True to drop it."
                )

        with self._cur() as cur:
            cur.execute(
                f"CREATE TABLE {table} ("
                f"  id BIGINT PRIMARY KEY,"
                f"  vector vector({dimension})"
                f")"
            )
            logger.info("Created table '%s' (%s-d)", name, f"{dimension:,}")

        # Build the index (unless FLAT / no index requested).
        index_params = index_params or {}
        if index_type.upper() not in ("FLAT", "NONE"):
            self._create_index(
                name, dimension, metric_type, index_type, index_params
            )

        return CollectionInfo(
            name=name,
            dimension=dimension,
            metric_type=metric_type,
            index_type=index_type,
            row_count=0,
            extra={"index_params": index_params},
        )

    def _create_index(
        self,
        name: str,
        dimension: int,
        metric_type: str,
        index_type: str,
        index_params: Dict[str, Any],
    ) -> None:
        table = self._table(name)
        idx_name = self._index_name(name)
        upper = index_type.upper()

        if upper == "HNSW":
            ops = _METRIC_TO_HNSW_OPS.get(metric_type.upper(), "vector_cosine_ops")
            m = index_params.get("M", index_params.get("m", 16))
            ef_construction = index_params.get(
                "efConstruction",
                index_params.get("ef_construction", 200),
            )
            with_clause = f"(m = {m}, ef_construction = {ef_construction})"
            sql = (
                f"CREATE INDEX {idx_name} ON {table} "
                f"USING hnsw (vector {ops}) WITH {with_clause}"
            )
        elif upper == "IVFFLAT":
            ops = _METRIC_TO_IVFFLAT_OPS.get(metric_type.upper(), "vector_cosine_ops")
            nlist = index_params.get("nlist", index_params.get("lists", 100))
            with_clause = f"(lists = {nlist})"
            sql = (
                f"CREATE INDEX {idx_name} ON {table} "
                f"USING ivfflat (vector {ops}) WITH {with_clause}"
            )
        else:
            logger.warning(
                "Unknown index type '%s' for pgvector; skipping index creation.",
                index_type,
            )
            return

        logger.info("Creating index: %s", sql)
        with self._cur() as cur:
            cur.execute(sql)
        logger.info("Index '%s' created (%s / %s)", idx_name, index_type, metric_type)

    def collection_exists(self, name: str) -> bool:
        with self._cur() as cur:
            cur.execute(
                "SELECT EXISTS ("
                "  SELECT 1 FROM information_schema.tables"
                "  WHERE table_name = %s"
                ")",
                (name,),
            )
            return cur.fetchone()[0]

    def drop_collection(self, name: str) -> None:
        table = self._table(name)
        with self._cur() as cur:
            cur.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
        logger.info("Dropped table: %s", name)

    # ------------------------------------------------------------------
    # Data ingestion
    # ------------------------------------------------------------------
    def insert_batch(
        self,
        name: str,
        ids: np.ndarray,
        vectors: np.ndarray,
    ) -> int:
        import psycopg2.extras

        table = self._table(name)
        n = len(ids)
        # Build a list of tuples for execute_values.
        rows = [(int(ids[i]), vectors[i].tolist()) for i in range(n)]
        with self._cur() as cur:
            psycopg2.extras.execute_values(
                cur,
                f"INSERT INTO {table} (id, vector) VALUES %s "
                f"ON CONFLICT (id) DO NOTHING",
                rows,
                template="(%s, %s::vector)",
                page_size=1000,
            )
        return n

    def flush(self, name: str) -> None:
        # With autocommit = True every statement is already committed.
        logger.info("Flush (no-op with autocommit) for table '%s'", name)

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------
    def search(
        self,
        name: str,
        query_vectors: np.ndarray,
        top_k: int,
        search_params: Optional[Dict[str, Any]] = None,
    ) -> List[List[int]]:
        table = self._table(name)
        search_params = search_params or {}

        # Determine distance operator from metric_type in search_params.
        metric = search_params.get("metric_type", "COSINE").upper()
        op = _METRIC_TO_OPERATOR.get(metric, "<=>")

        # Apply runtime search params (e.g. ef_search for HNSW, probes for IVFFlat).
        ef_search = search_params.get("ef_search", search_params.get("ef"))
        probes = search_params.get("probes")

        results: List[List[int]] = []

        # SET LOCAL requires a transaction block, so temporarily leave
        # autocommit mode when we need to apply search-time GUCs.
        need_txn = ef_search is not None or probes is not None
        if need_txn:
            self._conn.autocommit = False

        try:
            with self._cur() as cur:
                if ef_search is not None:
                    cur.execute(
                        f"SET LOCAL hnsw.ef_search = {int(ef_search)}"
                    )
                if probes is not None:
                    cur.execute(
                        f"SET LOCAL ivfflat.probes = {int(probes)}"
                    )

                for qvec in query_vectors:
                    vec_literal = "[" + ",".join(str(float(v)) for v in qvec) + "]"
                    cur.execute(
                        f"SELECT id FROM {table} "
                        f"ORDER BY vector {op} %s::vector "
                        f"LIMIT %s",
                        (vec_literal, top_k),
                    )
                    results.append([row[0] for row in cur.fetchall()])

            if need_txn:
                self._conn.commit()
        except Exception:
            if need_txn:
                self._conn.rollback()
            raise
        finally:
            if need_txn:
                self._conn.autocommit = True

        return results

    # ------------------------------------------------------------------
    # Status / info
    # ------------------------------------------------------------------
    def row_count(self, name: str) -> int:
        table = self._table(name)
        with self._cur() as cur:
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            return cur.fetchone()[0]

    def get_index_progress(self, name: str) -> IndexProgress:
        """In PostgreSQL ``CREATE INDEX`` is synchronous, so by the time
        control returns the index is already built.  This simply checks
        whether any index exists on the table.
        """
        with self._cur() as cur:
            cur.execute(
                "SELECT indexname FROM pg_indexes WHERE tablename = %s",
                (name,),
            )
            indexes = [row[0] for row in cur.fetchall()]
        if indexes:
            return IndexProgress(
                is_ready=True,
                status=", ".join(indexes),
            )
        return IndexProgress(is_ready=False, status="waiting")

    # ------------------------------------------------------------------
    # Administration / introspection
    # ------------------------------------------------------------------
    def list_collections(self) -> List[str]:
        with self._cur() as cur:
            cur.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' "
                "AND table_type = 'BASE TABLE' "
                "ORDER BY table_name"
            )
            return [row[0] for row in cur.fetchall()]

    def get_collection_info(self, name: str) -> Dict[str, Any]:
        table = self._table(name)

        # Columns
        schema: List[Dict[str, Any]] = []
        dimension = None
        with self._cur() as cur:
            cur.execute(
                "SELECT column_name, data_type, udt_name "
                "FROM information_schema.columns "
                "WHERE table_name = %s ORDER BY ordinal_position",
                (name,),
            )
            for col_name, data_type, udt_name in cur.fetchall():
                entry: Dict[str, Any] = {
                    "name": col_name,
                    "dtype": udt_name if udt_name != data_type else data_type,
                }
                if udt_name == "vector":
                    # Retrieve dimension from atttypmod
                    cur.execute(
                        "SELECT atttypmod FROM pg_attribute "
                        "WHERE attrelid = %s::regclass AND attname = %s",
                        (name, col_name),
                    )
                    row = cur.fetchone()
                    if row and row[0] > 0:
                        dimension = row[0]
                        entry["dim"] = dimension
                schema.append(entry)

        # Index info
        indexes = self.list_indexes(name)
        index_type = indexes[0]["index_type"] if indexes else None

        # Metric type from operator class
        metric_type = None
        if indexes:
            ops = indexes[0].get("params", {}).get("opclass", "")
            for metric, op_cls in _METRIC_TO_HNSW_OPS.items():
                if op_cls == ops:
                    metric_type = metric
                    break

        row_count = self.row_count(name)

        return {
            "name": name,
            "row_count": row_count,
            "dimension": dimension,
            "metric_type": metric_type,
            "index_type": index_type,
            "schema": schema,
        }

    def list_indexes(self, name: str) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        with self._cur() as cur:
            cur.execute(
                "SELECT indexname, indexdef FROM pg_indexes "
                "WHERE tablename = %s",
                (name,),
            )
            for idx_name, idx_def in cur.fetchall():
                # Skip primary-key indexes
                if "_pkey" in idx_name:
                    continue
                idx_type = "UNKNOWN"
                idx_def_upper = idx_def.upper()
                if "USING HNSW" in idx_def_upper:
                    idx_type = "HNSW"
                elif "USING IVFFLAT" in idx_def_upper:
                    idx_type = "IVFFLAT"
                results.append({
                    "index_name": idx_name,
                    "index_type": idx_type,
                    "definition": idx_def,
                    "params": {},
                })
        return results

    def drop_index(self, name: str, index_name: Optional[str] = None) -> None:
        if index_name is None:
            index_name = self._index_name(name)
        with self._cur() as cur:
            cur.execute(f"DROP INDEX IF EXISTS {index_name}")
        logger.info("Dropped index '%s' from table '%s'", index_name, name)
