import socket
import threading
import time
from datetime import date

import pytest
import uvicorn

from mock_sources.app import Faults, create_app, parse_ts
from mock_sources.generator import GenConfig, generate
from pipeline.config import Settings

SMALL = GenConfig(seed=7, start=date(2025, 1, 1), end=date(2025, 3, 31), n_customers=300)


@pytest.fixture(scope="session")
def small_ds():
    return generate(SMALL)


class LiveServer:
    def __init__(self, ds):
        self.ds = ds
        self.faults = Faults(rate_limit_per_sec=0, error_rate=0.0)
        self.app = create_app(ds, faults=self.faults)
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            self.port = s.getsockname()[1]
        self.server = uvicorn.Server(uvicorn.Config(self.app, host="127.0.0.1", port=self.port, log_level="error"))
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def start(self):
        self.thread.start()
        for _ in range(100):
            if self.server.started:
                return self
            time.sleep(0.05)
        raise RuntimeError("mock server did not start")

    def stop(self):
        self.server.should_exit = True
        self.thread.join(timeout=5)

    def set_as_of(self, iso: str):
        self.app.state.state["as_of"] = parse_ts(iso)

    @property
    def base(self):
        return f"http://127.0.0.1:{self.port}"


@pytest.fixture
def server(small_ds):
    s = LiveServer(small_ds).start()
    yield s
    s.stop()


@pytest.fixture
def settings(tmp_path, server):
    return Settings(shopify_base_url=server.base + "/shopify", stripe_base_url=server.base + "/stripe",
                    landing_dir=str(tmp_path / "landing"), report_dir=str(tmp_path / "reports"),
                    duckdb_path=str(tmp_path / "wh.duckdb"), backoff_base=0.01, page_size=60, max_retries=8)
