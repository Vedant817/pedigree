"""Admission invariants: deterministic windows, atomic multi-bucket reservation."""
from concurrent.futures import ThreadPoolExecutor

import pytest

from pedigree.errors import RateLimited
from pedigree.rate_limit import RateLimiter


def test_independent_budgets_and_exact_window():
    now = [0.0]
    limiter = RateLimiter(clock=lambda: now[0], read_limit=2, write_limit=2)
    for _ in range(2):
        limiter.admit('t', 'read')
        limiter.admit('t', 'write')
    with pytest.raises(RateLimited) as error:
        limiter.admit('t', 'write')
    assert error.value.detail['retry_after'] == 60
    now[0] = 59.999
    with pytest.raises(RateLimited):
        limiter.admit('t', 'read')
    now[0] = 60
    limiter.admit('t', 'read')
    limiter.admit('t', 'write')


def test_concurrent_exact_threshold():
    limiter = RateLimiter(write_limit=8)
    def attempt(_):
        try:
            limiter.admit('t', 'write')
            return True
        except RateLimited:
            return False
    with ThreadPoolExecutor(max_workers=16) as pool:
        assert sum(pool.map(attempt, range(40))) == 8


def test_rejected_destructive_does_not_consume_other_bucket():
    limiter = RateLimiter(read_limit=2, write_limit=2, destructive_limit=1)
    limiter.admit('t', 'revoke')
    with pytest.raises(RateLimited):
        limiter.admit('t', 'reinstate', dry_run=True)
    limiter.admit('t', 'read')
    limiter.admit('t', 'read')
    limiter.admit('t', 'write')
    with pytest.raises(RateLimited):
        limiter.admit('t', 'write')


def test_gate_and_whatif_classification():
    limiter = RateLimiter(read_limit=1, write_limit=2)
    limiter.admit('t', 'gate')
    limiter.admit('t', 'gate', record=True)
    limiter.admit('t', 'whatif')
    with pytest.raises(RateLimited):
        limiter.admit('t', 'read')
    with pytest.raises(RateLimited):
        limiter.admit('t', 'write')


def test_failed_auth_threshold_and_expiry():
    now = [0.0]
    limiter = RateLimiter(clock=lambda: now[0])
    for _ in range(10):
        limiter.check_peer('peer')
        limiter.failed_auth('peer')
    with pytest.raises(RateLimited):
        limiter.check_peer('peer')
    limiter.check_peer('other')
    now[0] = 60
    limiter.check_peer('peer')
    assert limiter._buckets == {}


def test_capacity_never_evicts_active_allowance_and_atomic_multi_keys():
    now = [0.0]
    limiter = RateLimiter(clock=lambda: now[0], max_keys=1, write_limit=1)
    with pytest.raises(RateLimited):
        limiter.admit('t', 'revoke')
    assert limiter._buckets == {}
    limiter.admit('t', 'write')
    for tenant in ('t', 'other'):
        with pytest.raises(RateLimited):
            limiter.admit(tenant, 'write')
    assert len(limiter._buckets) == 1
    assert len(next(iter(limiter._buckets.values()))) == 1
    now[0] = 60
    limiter.admit('other', 'write')
