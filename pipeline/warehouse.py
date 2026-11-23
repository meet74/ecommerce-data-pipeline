"""Warehouse access for DuckDB (default) and Postgres (SQLAlchemy URL).

Both backends take the same SQL: ON CONFLICT upserts, IS DISTINCT FROM and the
common type names. Only connection handling and bulk insert differ.
"""
from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Iterable, Sequence

import pandas as pd

from .config import Settings
from .schema import META_COLS, TABLES, ddl


def _py(v):
    if v is None or v is pd.NA or v is pd.NaT:
        return None
    return v.item() if hasattr(v, "item") else v


class Warehouse:
    dialect = "base"

    def execute(self, sql: str, params: Sequence | None = None) -> None: ...
    def query(self, sql: str, params: Sequence | None = None) -> list[tuple]: ...
    def insert_frame(self, table: str, df: pd.DataFrame) -> None: ...
    def begin(self) -> None: ...
    def commit(self) -> None: ...
    def rollback(self) -> None: ...
    def close(self) -> None: ...

    @contextlib.contextmanager
    def transaction(self):
        self.begin()
        try:
            yield
        except BaseException:
            self.rollback()
            raise
        else:
            self.commit()

    def query_df(self, sql: str, params: Sequence | None = None) -> pd.DataFrame:
        raise NotImplementedError

    def scalar(self, sql: str, params: Sequence | None = None):
        rows = self.query(sql, params)
        return rows[0][0] if rows else None

    def init_schema(self) -> None:
        for stmt in ddl():
            self.execute(stmt)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class DuckDBWarehouse(Warehouse):
    dialect = "duckdb"

    def __init__(self, path: str | Path, read_only: bool = False):
        import duckdb
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.con = duckdb.connect(str(path), read_only=read_only)

    def execute(self, sql, params=None):
        self.con.execute(sql, list(params) if params else None)

    def query(self, sql, params=None):
        return self.con.execute(sql, list(params) if params else None).fetchall()

    def query_df(self, sql, params=None):
        return self.con.execute(sql, list(params) if params else None).df()

    def insert_frame(self, table, df):
        self.con.register("_frame", df)
        try:
            self.con.execute(f"INSERT INTO {table} SELECT * FROM _frame")
        finally:
            self.con.unregister("_frame")

    def begin(self):
        self.con.execute("BEGIN TRANSACTION")

    def commit(self):
        self.con.execute("COMMIT")

    def rollback(self):
        self.con.execute("ROLLBACK")

    def close(self):
        self.con.close()


class PostgresWarehouse(Warehouse):
    dialect = "postgres"

    def __init__(self, url: str):
        from sqlalchemy import create_engine
        self.engine = create_engine(url)
        self.conn = self.engine.raw_connection()   # DBAPI connection; transactions are explicit
        self.in_tx = False

    @staticmethod
    def _sql(sql: str) -> str:
        return sql.replace("?", "%s")

    def execute(self, sql, params=None):
        with self.conn.cursor() as cur:
            cur.execute(self._sql(sql), list(params) if params else None)
        if not self.in_tx:
            self.conn.commit()

    def query(self, sql, params=None):
        with self.conn.cursor() as cur:
            cur.execute(self._sql(sql), list(params) if params else None)
            rows = cur.fetchall() if cur.description else []
        if not self.in_tx:
            self.conn.commit()
        return rows

    def query_df(self, sql, params=None):
        with self.conn.cursor() as cur:
            cur.execute(self._sql(sql), list(params) if params else None)
            cols = [d[0] for d in cur.description]
            rows = cur.fetchall()
        if not self.in_tx:
            self.conn.commit()
        return pd.DataFrame(rows, columns=cols)

    def insert_frame(self, table, df):
        from psycopg2.extras import execute_values
        cols = ", ".join(df.columns)
        records = [tuple(_py(v) for v in row) for row in df.itertuples(index=False, name=None)]
        with self.conn.cursor() as cur:
            execute_values(cur, f"INSERT INTO {table} ({cols}) VALUES %s", records, page_size=5000)
        if not self.in_tx:
            self.conn.commit()

    def begin(self):
        self.in_tx = True

    def commit(self):
        self.conn.commit()
        self.in_tx = False

    def rollback(self):
        self.conn.rollback()
        self.in_tx = False

    def close(self):
        self.conn.close()
        self.engine.dispose()


def connect(settings: Settings, target: str | None = None, read_only: bool = False) -> Warehouse:
    target = target or settings.target
    if target == "duckdb":
        return DuckDBWarehouse(settings.path(settings.duckdb_path), read_only=read_only)
    if target == "postgres":
        if not settings.database_url:
            raise SystemExit("DATABASE_URL is required for --target postgres")
        return PostgresWarehouse(settings.database_url)
    raise SystemExit(f"unknown target {target!r}")


def frame_for(table: str, rows: list[dict], run_id: str, loaded_at) -> pd.DataFrame:
    """Build a DataFrame with explicit nullable dtypes so ints and bools survive missing values."""
    cols = TABLES[table] + META_COLS
    data = {}
    for name, typ in cols:
        if name == "_run_id":
            values = [run_id] * len(rows)
        elif name == "_loaded_at":
            values = [loaded_at] * len(rows)
        else:
            values = [r.get(name) for r in rows]
        if typ in ("BIGINT", "INTEGER"):
            data[name] = pd.array(values, dtype="Int64")
        elif typ == "BOOLEAN":
            data[name] = pd.array(values, dtype="boolean")
        else:
            data[name] = pd.Series(values, dtype="object")
    return pd.DataFrame(data)
