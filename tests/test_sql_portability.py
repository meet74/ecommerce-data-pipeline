"""Cheap guard for the Postgres claim: compile the models and make sure sqlglot can parse them as Postgres."""
from pathlib import Path

import sqlglot

from pipeline import transform
from pipeline.config import ROOT, Settings


def test_compiled_models_parse_as_postgres(tmp_path):
    res = transform.run_dbt(Settings(duckdb_path=str(tmp_path / "x.duckdb")), "duckdb", "compile")
    assert res["returncode"] == 0, res["stdout_tail"]
    files = list(Path(ROOT / "dbt_project" / "target" / "compiled" / "ecommerce").rglob("*.sql"))
    assert len(files) >= 25
    for f in files:
        sqlglot.parse_one(f.read_text(), read="postgres")
