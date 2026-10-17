"""Shipped HTTP launch must preserve the socket peer for failed-auth backoff."""
from pedigree.cli import serve
from pedigree.config import Settings


def test_serve_does_not_trust_caller_forwarding_headers(monkeypatch):
    observed = {}

    def run(*args, **kwargs):
        observed.update(kwargs)

    monkeypatch.setattr("uvicorn.run", run)
    assert serve(Settings(_env_file=None), "127.0.0.1", 8000) == 0
    assert observed.get("proxy_headers") is False
