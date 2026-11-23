# E-commerce Data Pipeline

Pulls orders, customers, products, refunds and payments from a store API and a payments API, loads only what changed into a warehouse, builds tested SQL models, and sends a daily KPI dashboard and Slack summary.

![E-commerce Data Pipeline](assets/cover.png)

## The problem

A shop owner has sales in the store platform and money in the payment provider, and the two never quite agree. Refunds arrive weeks after the order, customers show up twice under different spellings of their email, test orders inflate the numbers, and half the sales are in US dollars. Someone ends up rebuilding the same spreadsheet every Monday. This project replaces that with a pipeline that runs every morning, reconciles the two systems, and says plainly what yesterday looked like.

## What it does

- Extracts orders (with line items), customers, products and refunds from a Shopify-style API, and charges, refunds and payouts from a Stripe-style API.
- Loads incrementally by `updated_at`, so late edits and refunds on old orders are picked up. Re-running is safe.
- Keeps every API response on disk (JSONL landing zone) and in typed raw tables, with run metadata for each entity.
- Builds staging, intermediate and mart models with dbt: `fct_orders`, `dim_customers`, `daily_kpis`, `monthly_cohort_retention`, `product_performance`, `fct_payment_reconciliation`. All money is normalised to CAD.
- Runs 85 data tests, including reconciliation checks between layers and between the store and the payment provider.
- Writes a single-file HTML dashboard (Plotly) and a Slack message with yesterday's numbers.
- Ships an n8n workflow that runs it all at 7am and posts to Slack, with an alert path when anything fails.
- Runs on DuckDB with no setup, or on Postgres with `--target postgres`.

## How it works

```mermaid
flowchart LR
    subgraph Sources
        S[Store API<br/>orders, customers,<br/>products, refunds]
        P[Payments API<br/>charges, refunds,<br/>payouts]
    end
    S --> X[Extract<br/>cursor pagination,<br/>retry + Retry-After]
    P --> X
    X --> L[(Landing zone<br/>JSONL per run)]
    L --> M[Merge on id<br/>hash + updated_at guard]
    M --> R[(raw schema<br/>typed tables)]
    M --> W[(meta.watermarks<br/>meta.run_log)]
    R --> D[dbt<br/>staging, intermediate, marts]
    D --> T{dbt tests}
    T --> K[(marts)]
    K --> H[HTML dashboard]
    K --> J[summary.json]
    J --> SL[Slack summary]
    N8N[n8n, 7am daily] -. runs .-> X
    N8N -. posts .-> SL
```

Per entity, the loader reads the high-water mark from `meta.watermarks`, asks the API for records updated since then (minus a two minute overlap), writes each page to `data/landing/<source>/<entity>/<run_id>/`, and then, in one transaction, merges the rows and advances the watermark. If the run dies before that commit, the watermark does not move and the next run re-reads the same window.

### Data model

```mermaid
erDiagram
    stg_shopify__orders ||--o{ stg_shopify__order_lines : has
    stg_shopify__orders ||--o{ stg_shopify__refunds : has
    stg_shopify__products ||--o{ stg_shopify__order_lines : sold_as
    stg_stripe__charges ||--o{ stg_stripe__refunds : has
    stg_shopify__orders ||--o| stg_stripe__charges : "paid by (order_id)"
    int_orders ||--|| fct_orders : "adds refunds and fees"
    fct_orders }o--|| dim_customers : customer_key
    fct_orders ||--o{ daily_kpis : "by order date"
    fct_orders ||--o{ monthly_cohort_retention : "first order month"
    int_order_lines }o--|| product_performance : product_id
    int_orders ||--o| fct_payment_reconciliation : "vs charge"
    int_charges ||--o| fct_payment_reconciliation : "vs order"
```

Layers: `raw` (loaded as-is, typed), `staging` (cleaned, one view per source table), `intermediate` (calendar, FX, valid orders, CAD conversion), `marts` (what people query). Staging keeps flagged rows instead of deleting them (`is_test`, `is_duplicate`, `is_cancelled`), so the cleaning is countable.

Metric definitions:

| Metric | Definition |
| --- | --- |
| Revenue | Order total minus tax, converted to CAD at the order-date rate, valid orders only |
| Refunds | Refund amount minus its share of tax, converted at the refund-date rate, counted on the day of the refund |
| Fees | Stripe processing fees on succeeded charges, by charge date |
| Net revenue | Revenue - refunds - fees |
| Refund rate | Share of a day's orders that have since been refunded |
| New vs returning | By the customer's first valid order; orders with no email and no account count as guests |

## Results

Measured on this repo's synthetic data (546 days, 2025-01-01 to 2026-06-30), with the mock APIs running locally and injecting rate limits (429 with `Retry-After`) and random 500s. Machine: 2 vCPU, DuckDB file warehouse. Raw numbers are in [`docs/benchmark.json`](docs/benchmark.json); `make bench` reproduces them.

| | Full run | Next day (incremental) | Re-run, nothing new |
| --- | --- | --- | --- |
| Records read from the APIs | 63,011 (all) | 324 | 8 (the overlap window) |
| Rows written to the warehouse | 112,524 | 655 | 0 |
| Extract + load | 12.0 s | 0.3 s | 0.6 s |
| dbt models + tests + report | 8.9 s | 9.9 s | not run |
| Whole run | 21.3 s | 10.6 s | 0.6 s |

- Warehouse at the end of the benchmark (full run plus one incremental): 112,924 raw rows (27,842 order records, 49,690 line items, 26,710 charges, 4,641 customers), 26,726 valid orders, 4,536 customers after merging duplicates.
- Across the three runs the mock servers answered 456 requests, of which 3 were rate-limit responses and 8 were server errors. The client retried through all of them with no failed entity.
- Data tests: 84 pass, 1 warns (by design, it warns whenever reconciliation finds a mismatch), 0 fail. The same 84 pass on PostgreSQL 16.
- Python tests: 45 pass (43 on DuckDB only; the two end-to-end tests run a second time against Postgres when `TEST_POSTGRES_URL` is set).
- Planted problems versus what the pipeline found:

| Problem planted in the source data | Planted | Found |
| --- | --- | --- |
| Paid orders with no Stripe charge | 32 | 32 |
| Charges whose amount differs from the order total | 32 | 32 |
| Charges with no matching order | 16 | 16 |
| Refunds that differ between store and Stripe | 10 | 10 |
| Charge currency differs from order currency | 8 | 8 |
| Duplicate orders (same order number) | 213 | 213 flagged and dropped |
| Test orders | 327 | 327 flagged and dropped |
| Duplicate customer records (email casing/spacing) | 105 | 105 merged |
| Cancelled orders | 576 | 576 flagged and dropped |

The generator is seeded, so these counts are reproducible. They show the checks work on the planted cases; they say nothing about the recall on problems nobody thought to plant.

Example Slack message (from `python -m pipeline slack --dry-run`, rendered here as an image; the JSON is in [`docs/example-slack-payload.json`](docs/example-slack-payload.json)):

![Slack summary](assets/slack-summary.png)

The HTML dashboard it links to (KPI tiles, revenue trend, new vs returning, top products, cohort heatmap, reconciliation issues):

![Dashboard](assets/dashboard.png)

## Run it yourself

```bash
git clone <this repo> && cd ecommerce-data-pipeline
make setup                 # venv, dependencies, .env from .env.example
make serve                 # terminal 1: mock store + payments APIs on :8100
make run                   # terminal 2: extract, load, dbt run, dbt test, report
open reports/dashboard.html
.venv/bin/python -m pipeline slack --dry-run     # print the Slack payload
make test
```

`make demo` does the serve-and-run steps in one command. The first start of the mock server takes about 10 seconds while it generates the dataset (cached afterwards in `data/mock/`).

Postgres instead of DuckDB:

```bash
.venv/bin/pip install -r requirements-postgres.txt
.venv/bin/python -m pipeline all --target postgres --db-url postgresql+psycopg2://user:pass@host:5432/dbname
```

To post to Slack, set `SLACK_WEBHOOK_URL` in `.env` and run `python -m pipeline all --notify`, or use the n8n workflow below. To point the pipeline at real APIs, change the base URLs and keys in `.env`; the store client expects the Shopify REST shape and the payments client the Stripe list shape.

Other commands: `python -m pipeline status` (watermarks and recent runs), `--full-refresh` (ignore watermarks), `--entities orders charges` (partial run).

### n8n workflow

`workflows/ecommerce-daily-summary.json`: Schedule trigger at 07:00, run `make run`, read `reports/summary.json`, check health, render the Slack message, post it. A failed command, a failed data test or any workflow error goes to a second Slack message through the Error Trigger and the node's error output.

To use it: import the file in n8n, create a Slack credential named `Slack account`, set the channel, and start n8n with `PIPELINE_DIR` pointing at this folder. n8n 2.x disables the Execute Command node by default, so also set `NODES_EXCLUDE=[]`. For the Error Trigger branch, set this workflow as its own error workflow in its settings.

Checked here against n8n 2.48.7 in a throwaway instance: the file imports cleanly, and `scripts/check_workflow.py` runs it end to end with the Slack nodes swapped for a local webhook. A healthy run posted the Block Kit summary for 2026-06-30, and a run with the sources unreachable posted the failure alert. The real Slack nodes were not exercised, since that needs a Slack workspace.

## Project structure

```
mock_sources/      FastAPI mock store and payments APIs, seeded data generator
pipeline/          client (retries), sources (pagination), ingest (landing + merge),
                   warehouse (DuckDB/Postgres), transform (dbt), summary, report, slack, CLI
dbt_project/       models/{staging,intermediate,marts}, seeds/fx_rates.csv, tests/, macros/
workflows/         n8n workflow
scripts/           benchmark, demo, workflow check, screenshots, fx seed generator
tests/             pytest suite
docs/              benchmark.json, example Slack payload
reports/           generated dashboard and summary.json (not committed)
```

## Design decisions

- **Watermark from the data, not the clock.** The high-water mark is the newest `updated_at` actually loaded, not `now()`, so clock skew cannot skip rows. Each run re-reads a two minute overlap, which is safe because the merge writes a row only when its content hash changed and its `updated_at` is not older than what is stored. A stale replay can never overwrite newer data.
- **Land, then load.** Pages are written to disk before anything touches the warehouse, so a bad parse can be replayed without hitting the API again. The merge, child-row replacement and watermark update share one transaction.
- **Flag, do not delete, in staging.** Duplicates, test orders and cancellations stay visible with flags, which is why the table above can compare "planted" with "found". Customer identity is the normalised email, because the same person appears under several ids.
- **FX is an as-of join.** Rates exist for business days only, so each day takes the latest earlier rate. The rates are a synthetic seed file; in production this is a feed. Refunds are converted at the refund date and have the order's tax share removed so they can be subtracted from revenue, which excludes tax.
- **Marts are rebuilt every run.** About 5 seconds at this size, and it keeps late-arriving refunds correct without incremental-model edge cases. When a rebuild gets slow, `fct_orders` and `daily_kpis` are the first candidates for incremental models.
- **SQL that runs on two engines.** Models use `cast`, window functions, recursive CTEs and `date_trunc` only, and avoid integer division and engine-specific functions. The suite ran green on DuckDB and on PostgreSQL 16 here. A test also parses every compiled model with a Postgres parser.
- **Reconciliation has a grace window and two severities.** Orders younger than an hour may not have a charge yet, so they are not flagged. Any mismatch raises a warning; a mismatch rate above 2% fails the run.

## Limitations and next steps

- The sources are mocks. The Stripe-like API has an `updated[gte]` filter that the real API lacks; against real Stripe the sync should read the events endpoint. Real Shopify uses a leaky-bucket rate limit and returns `Retry-After` differently under load; the client handles the header but was only tested against the mock's fixed-window limiter.
- Only the store's order total is compared with the charge. Partial captures, multiple charges per order and split payments would need a many-to-many match.
- No schema drift handling: a new field in an API response is ignored until the typed table is extended.
- Cohorts leave out orders with no email at all, and the one-order-per-email identity rule would merge two people sharing an address.
- DuckDB allows one writer, so the pipeline closes its connection before dbt runs and nothing else can write meanwhile. Postgres does not have that limit.
- Next: dbt incremental models, source freshness checks, a backfill command for a date range, and alerting on volume anomalies rather than only on test failures.

MIT licensed.
