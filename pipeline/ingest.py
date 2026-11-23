"""Extract to the landing zone, then merge into typed raw tables.

Per entity: read the watermark, page through the API, write every page as JSONL under
data/landing/, then in ONE transaction upsert the rows and advance the watermark.
If anything fails before that commit the watermark does not move, so the next run
re-reads the same window.
"""
from __future__ import annotations

import json
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from .client import ApiClient
from .config import Settings
from .entities import ENTITIES, Entity, row_hash
from .schema import META_COLS, TABLES
from .warehouse import Warehouse, frame_for


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


def new_run_id() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y%m%dT%H%M%S") + f"{now.microsecond // 1000:03d}"


def get_watermark(wh: Warehouse, source: str, entity: str) -> datetime | None:
    return wh.scalar("SELECT high_watermark FROM meta.watermarks WHERE source = ? AND entity = ?", [source, entity])


def set_watermark(wh: Warehouse, source: str, entity: str, value: datetime, run_id: str) -> None:
    wh.execute(
        "INSERT INTO meta.watermarks (source, entity, high_watermark, last_run_id, updated_at) VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT (source, entity) DO UPDATE SET high_watermark = EXCLUDED.high_watermark, "
        "last_run_id = EXCLUDED.last_run_id, updated_at = EXCLUDED.updated_at",
        [source, entity, value, run_id, utcnow()])


def log_run(wh: Warehouse, run_id: str, source: str, entity: str, **f) -> None:
    cols = ["run_id", "source", "entity"] + list(f)
    wh.execute(f"INSERT INTO meta.run_log ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
               [run_id, source, entity] + list(f.values()))


def land_pages(settings: Settings, ent: Entity, run_id: str, pages) -> tuple[list[dict], int]:
    folder = settings.path(settings.landing_dir) / ent.source / ent.name / run_id
    folder.mkdir(parents=True, exist_ok=True)
    records, n_pages = [], 0
    for n_pages, page in enumerate(pages, start=1):
        with open(folder / f"page-{n_pages:05d}.jsonl", "w") as fh:
            for rec in page:
                fh.write(json.dumps(rec, separators=(",", ":")) + "\n")
        records.extend(page)
    return records, n_pages


def read_landing(settings: Settings, ent: Entity, run_id: str) -> list[dict]:
    folder = settings.path(settings.landing_dir) / ent.source / ent.name / run_id
    out = []
    for f in sorted(folder.glob("page-*.jsonl")):
        out.extend(json.loads(line) for line in f.read_text().splitlines() if line)
    return out


def merge(wh: Warehouse, ent: Entity, records: list[dict], run_id: str) -> dict:
    """Idempotent merge on id. A row is written only if its content hash changed and it is
    not older than what the warehouse already holds (late, out-of-order replays are ignored)."""
    latest: dict = {}
    for rec in records:                       # newest version of an id within the batch wins
        row = ent.flatten(rec)
        prev = latest.get(rec["id"])
        if prev is None or row["updated_at"] >= prev[1]["updated_at"]:
            row["_row_hash"] = row_hash(rec)
            latest[rec["id"]] = (rec, row)
    now = utcnow()
    rows = [row for _, row in latest.values()]
    table = f"raw.{ent.table}"
    cols = [c for c, _ in TABLES[ent.table]] + [c for c, _ in META_COLS]
    counts = {"inserted": 0, "updated": 0, "unchanged": 0, "stale": 0}
    wh.execute(f"CREATE TEMP TABLE _stg AS SELECT * FROM {table} WHERE 1 = 0")
    wh.insert_frame("_stg", frame_for(ent.table, rows, run_id, now))
    stats = wh.query(f"""
        SELECT
          SUM(CASE WHEN t.id IS NULL THEN 1 ELSE 0 END),
          SUM(CASE WHEN t.id IS NOT NULL AND s._row_hash = t._row_hash THEN 1 ELSE 0 END),
          SUM(CASE WHEN t.id IS NOT NULL AND s._row_hash <> t._row_hash AND s.updated_at < t.updated_at THEN 1 ELSE 0 END),
          SUM(CASE WHEN t.id IS NOT NULL AND s._row_hash <> t._row_hash AND s.updated_at >= t.updated_at THEN 1 ELSE 0 END)
        FROM _stg s LEFT JOIN {table} t ON t.id = s.id""")[0]
    counts = dict(zip(("inserted", "unchanged", "stale", "updated"), (int(x or 0) for x in stats)))
    changed_ids = [r[0] for r in wh.query(f"""
        SELECT s.id FROM _stg s LEFT JOIN {table} t ON t.id = s.id
        WHERE t.id IS NULL OR (s._row_hash <> t._row_hash AND s.updated_at >= t.updated_at)""")]
    col_list = ", ".join(cols)
    sets = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols if c != "id")
    wh.execute(f"""
        INSERT INTO {table} ({col_list}) SELECT {col_list} FROM _stg
        ON CONFLICT (id) DO UPDATE SET {sets}
        WHERE {ent.table}._row_hash IS DISTINCT FROM EXCLUDED._row_hash AND EXCLUDED.updated_at >= {ent.table}.updated_at""")
    wh.execute("DROP TABLE _stg")
    child_rows = 0
    if ent.child_table and changed_ids:
        changed = set(changed_ids)
        children = [c for rec, _ in latest.values() if rec["id"] in changed for c in ent.child_flatten(rec)]
        # replace the children of every changed parent: lines can be removed as well as added
        wh.execute("CREATE TEMP TABLE _chg (id BIGINT)")
        wh.insert_frame("_chg", pd.DataFrame({"id": pd.array(changed_ids, dtype="Int64")}))
        wh.execute(f"DELETE FROM raw.{ent.child_table} WHERE {ent.child_fk} IN (SELECT id FROM _chg)")
        wh.execute("DROP TABLE _chg")
        if children:
            wh.insert_frame(f"raw.{ent.child_table}", _child_frame(ent.child_table, children, run_id, now))
        child_rows = len(children)
    counts["child_rows"] = child_rows
    counts["rows_written"] = counts["inserted"] + counts["updated"] + child_rows
    return counts


def _child_frame(table: str, rows: list[dict], run_id: str, now):
    for r in rows:
        r["_row_hash"] = None
    return frame_for(table, rows, run_id, now)


def ingest_entity(wh: Warehouse, client: ApiClient, settings: Settings, ent: Entity, run_id: str,
                  full_refresh: bool = False) -> dict:
    started = utcnow()
    t0 = time.perf_counter()
    before = dict(client.stats)
    wm = None if full_refresh else get_watermark(wh, ent.source, ent.name)
    since = wm - timedelta(seconds=settings.lookback_seconds) if wm else None
    status, error, metrics = "success", None, {"inserted": 0, "updated": 0, "unchanged": 0, "stale": 0, "child_rows": 0, "rows_written": 0}
    rows_read, wm_after = 0, wm
    try:
        base = settings.shopify_base_url if ent.source == "shopify" else settings.stripe_base_url
        records, n_pages = land_pages(settings, ent, run_id, ent.pages(client, base, ent.name, since, settings.page_size))
        rows_read = len(records)
        if records:
            landed = read_landing(settings, ent, run_id)
            assert len(landed) == rows_read
            newest = max(ent.flatten(r)["updated_at"] for r in landed)
            with wh.transaction():
                metrics = merge(wh, ent, landed, run_id)
                wm_after = max(newest, wm) if wm else newest
                set_watermark(wh, ent.source, ent.name, wm_after, run_id)
    except Exception as exc:
        status, error = "failed", f"{exc.__class__.__name__}: {exc}"
        traceback.print_exc()
    delta = {k: client.stats[k] - before[k] for k in ("requests", "retries", "rate_limited")}
    result = {"entity": f"{ent.source}.{ent.name}", "status": status, "rows_read": rows_read, **metrics,
              "http_requests": delta["requests"], "http_retries": delta["retries"], "rate_limited": delta["rate_limited"],
              "duration_s": round(time.perf_counter() - t0, 3), "watermark_before": wm, "watermark_after": wm_after, "error": error}
    log_run(wh, run_id, ent.source, ent.name, started_at=started, finished_at=utcnow(), duration_s=result["duration_s"],
            status=status, rows_read=rows_read, rows_inserted=metrics["inserted"], rows_updated=metrics["updated"],
            rows_unchanged=metrics["unchanged"], rows_stale=metrics["stale"], rows_written=metrics["rows_written"],
            http_requests=delta["requests"], http_retries=delta["retries"], rate_limited=delta["rate_limited"],
            watermark_before=wm, watermark_after=wm_after, error=error)
    return result


def make_clients(settings: Settings) -> dict[str, ApiClient]:
    kw = dict(max_retries=settings.max_retries, backoff_base=settings.backoff_base)
    return {
        "shopify": ApiClient({"X-Shopify-Access-Token": settings.shopify_token}, **kw),
        "stripe": ApiClient({"Authorization": f"Bearer {settings.stripe_key}"}, **kw),
    }


def extract_load(wh: Warehouse, settings: Settings, run_id: str, entities: list[str] | None = None,
                 full_refresh: bool = False, clients: dict[str, ApiClient] | None = None) -> list[dict]:
    wh.init_schema()
    clients = clients or make_clients(settings)
    results = []
    for ent in ENTITIES:
        if entities and f"{ent.source}.{ent.name}" not in entities and ent.name not in entities:
            continue
        results.append(ingest_entity(wh, clients[ent.source], settings, ent, run_id, full_refresh))
    return results
