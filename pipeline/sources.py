"""Page iterators for the two source APIs. Each yields lists of raw records."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterator

from .client import ApiClient


def to_iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def shopify_pages(client: ApiClient, base_url: str, entity: str, since: datetime | None, page_size: int) -> Iterator[list[dict]]:
    """Cursor pagination through the Link header; the filter lives in the first request only."""
    url = f"{base_url}/admin/api/2024-10/{entity}.json"
    params: dict | None = {"limit": page_size}
    if since is not None:
        params["updated_at_min"] = to_iso(since)
    while url:
        resp = client.get(url, params=params)
        yield resp.json()[entity]
        url, params = resp.links.get("next", {}).get("url"), None


def stripe_pages(client: ApiClient, base_url: str, entity: str, since: datetime | None, page_size: int) -> Iterator[list[dict]]:
    """starting_after / has_more pagination. `updated[gte]` is a mock extension: the real
    API has no updated filter, so a production sync would read the events endpoint instead."""
    url = f"{base_url}/v1/{entity}"
    params: dict = {"limit": min(page_size, 100)}
    if since is not None:
        params["updated[gte]"] = int(since.replace(tzinfo=timezone.utc).timestamp())
    while True:
        body = client.get(url, params=params).json()
        data = body["data"]
        if data:
            yield data
        if not body.get("has_more") or not data:
            return
        params["starting_after"] = data[-1]["id"]
