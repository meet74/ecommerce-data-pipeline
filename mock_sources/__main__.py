"""python -m mock_sources [--port 8100] [--seed 42] : serve the mock APIs."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import os
import pickle
from dataclasses import asdict
from pathlib import Path

import uvicorn

from .app import Faults, create_app
from .generator import GenConfig, Dataset, generate


def load_dataset(cfg: GenConfig, cache_dir: str = "data/mock") -> Dataset:
    key = hashlib.md5(repr(sorted(asdict(cfg).items())).encode()).hexdigest()[:10]
    path = Path(cache_dir) / f"dataset-{key}.pkl.gz"
    if path.exists():
        with gzip.open(path, "rb") as fh:
            ds = pickle.load(fh)
        ds.index()
        return ds
    ds = generate(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wb", compresslevel=3) as fh:
        pickle.dump(ds, fh)
    return ds


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=int(os.environ.get("MOCK_PORT", 8100)))
    ap.add_argument("--seed", type=int, default=int(os.environ.get("MOCK_SEED", 42)))
    ap.add_argument("--rate-limit", type=int, default=int(os.environ.get("MOCK_RATE_LIMIT_PER_SEC", 60)))
    ap.add_argument("--error-rate", type=float, default=float(os.environ.get("MOCK_ERROR_RATE", 0.01)))
    ap.add_argument("--as-of", default=None, help="ISO timestamp the APIs pretend it is (default: end of data)")
    args = ap.parse_args()
    ds = load_dataset(GenConfig(seed=args.seed))
    as_of = None
    if args.as_of:
        from .app import parse_ts
        as_of = parse_ts(args.as_of)
    app = create_app(ds, as_of=as_of, faults=Faults(args.rate_limit, args.error_rate, args.seed))
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
