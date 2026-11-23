"""Mock Shopify-style and Stripe-style APIs served from one FastAPI app.

Behaviour that matters to the pipeline:
  * keyset pagination (Link header for the store API, starting_after/has_more for payments)
  * records are filtered by updated_at; the API only shows the version that was current at
    the server's "as of" clock, so advancing the clock produces changes and late updates
  * a fixed-window rate limit answering 429 with Retry-After, plus random 500s
"""
from __future__ import annotations

import base64
import json
import math
import os
import random
import time
from datetime import datetime, timezone

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from .generator import Dataset, iso, visible_slice

SHOPIFY_PREFIX = "/shopify/admin/api/2024-10"
SHOPIFY_TOKEN = os.environ.get("SHOPIFY_ACCESS_TOKEN", "shpat_mock_token")
STRIPE_KEY = os.environ.get("STRIPE_API_KEY", "sk_test_mock_key")


def parse_ts(value: str) -> int:
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).timestamp())


class Faults:
    def __init__(self, rate_limit_per_sec: int = 60, error_rate: float = 0.01, seed: int = 1):
        self.rate_limit_per_sec = rate_limit_per_sec
        self.error_rate = error_rate
        self.fail_next = 0          # force the next N requests to 500
        self.rng = random.Random(seed)
        self.window = 0
        self.count = 0
        self.stats = {"requests": 0, "rate_limited": 0, "errors": 0}

    def check(self):
        """Return a response to short-circuit the request, or None."""
        self.stats["requests"] += 1
        now = time.time()
        window = int(now)
        if window != self.window:
            self.window, self.count = window, 0
        self.count += 1
        if self.rate_limit_per_sec and self.count > self.rate_limit_per_sec:
            self.stats["rate_limited"] += 1
            retry = max(0.05, math.ceil((window + 1 - now) * 10) / 10)
            return JSONResponse({"errors": "Exceeded rate limit"}, status_code=429, headers={"Retry-After": f"{retry:.1f}"})
        if self.fail_next > 0:
            self.fail_next -= 1
            self.stats["errors"] += 1
            return JSONResponse({"errors": "Internal error"}, status_code=500)
        if self.error_rate and self.rng.random() < self.error_rate:
            self.stats["errors"] += 1
            return JSONResponse({"errors": "Internal error"}, status_code=500)
        return None


def encode_cursor(payload: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()


def decode_cursor(value: str) -> dict:
    try:
        return json.loads(base64.urlsafe_b64decode(value.encode()))
    except Exception:
        raise HTTPException(400, "invalid page_info")


def create_app(ds: Dataset, as_of: int | None = None, faults: Faults | None = None) -> FastAPI:
    app = FastAPI(title="Mock store and payments APIs")
    state = {"as_of": as_of or ds.end_ts()}
    faults = faults or Faults()
    app.state.faults = faults
    app.state.state = state

    # ---- admin helpers (not part of the simulated APIs)
    @app.get("/health")
    def health():
        return {"ok": True, "as_of": iso(state["as_of"])}

    @app.get("/admin/state")
    def admin_state():
        return {"as_of": iso(state["as_of"]), "faults": faults.stats, "counts": ds.stats}

    @app.post("/admin/as_of")
    async def set_as_of(request: Request):
        body = await request.json()
        state["as_of"] = parse_ts(body["as_of"])
        return {"as_of": iso(state["as_of"])}

    @app.post("/admin/faults")
    async def set_faults(request: Request):
        body = await request.json()
        for key in ("rate_limit_per_sec", "error_rate", "fail_next"):
            if key in body:
                setattr(faults, key, body[key])
        return {"ok": True}

    @app.get("/admin/truth")
    def truth():
        return ds.truth

    # ---- store API
    def shopify_list(request: Request, entity: str, key: str, x_shopify_access_token: str | None, limit: int,
                     updated_at_min: str | None, page_info: str | None, base_path: str):
        if x_shopify_access_token != SHOPIFY_TOKEN:
            return JSONResponse({"errors": "Invalid API key or access token"}, status_code=401)
        blocked = faults.check()
        if blocked is not None:
            return blocked
        limit = max(1, min(limit, 250))
        if page_info:
            cur = decode_cursor(page_info)
            since, after = cur["since"], (cur["ts"], cur["id"])
        else:
            since = parse_ts(updated_at_min) if updated_at_min else 0
            after = None
        rows, last = [], None
        gen = visible_slice(ds, f"shopify.{entity}", since, state["as_of"], after)
        more = False
        for e in gen:
            if len(rows) == limit:
                more = True
                break
            rows.append(e.record)
            last = e
        headers = {}
        if more and last is not None:
            token = encode_cursor({"since": since, "ts": last.ts, "id": str(last.id)})
            headers["Link"] = f'<{request.base_url}{base_path.lstrip("/")}?limit={limit}&page_info={token}>; rel="next"'
        return JSONResponse({key: rows}, headers=headers)

    def register_shopify(entity: str, key: str):
        path = f"{SHOPIFY_PREFIX}/{entity}.json"

        @app.get(path, name=f"shopify_{entity}")
        def handler(request: Request, limit: int = 50, updated_at_min: str | None = None, page_info: str | None = None,
                    x_shopify_access_token: str | None = Header(default=None)):
            return shopify_list(request, entity, key, x_shopify_access_token, limit, updated_at_min, page_info, path)

    for ent in ("orders", "customers", "products", "refunds"):
        register_shopify(ent, ent)

    # ---- payments API
    def stripe_list(entity: str, authorization: str | None, limit: int, updated_gte: int | None, starting_after: str | None):
        if authorization != f"Bearer {STRIPE_KEY}":
            return JSONResponse({"error": {"type": "invalid_request_error", "message": "Invalid API Key provided"}}, status_code=401)
        blocked = faults.check()
        if blocked is not None:
            return blocked
        limit = max(1, min(limit, 100))
        name = f"stripe.{entity}"
        after = None
        if starting_after:
            versions = ds.by_id[name].get(starting_after)
            if not versions:
                return JSONResponse({"error": {"message": f"No such object: {starting_after}"}}, status_code=400)
            vis = [v for v in versions if v.ts <= state["as_of"] and (v.next_ts is None or v.next_ts > state["as_of"])]
            ref = vis[-1] if vis else versions[0]
            after = (ref.ts, str(ref.id))
        rows, more = [], False
        for e in visible_slice(ds, name, updated_gte or 0, state["as_of"], after):
            if len(rows) == limit:
                more = True
                break
            rows.append(e.record)
        return {"object": "list", "url": f"/v1/{entity}", "has_more": more, "data": rows}

    def register_stripe(entity: str):
        @app.get(f"/stripe/v1/{entity}", name=f"stripe_{entity}")
        def handler(request: Request, limit: int = 10, starting_after: str | None = None,
                    authorization: str | None = Header(default=None)):
            raw = request.query_params.get("updated[gte]")
            return stripe_list(entity, authorization, limit, int(raw) if raw else None, starting_after)

    for ent in ("charges", "refunds", "payouts"):
        register_stripe(ent)

    return app
