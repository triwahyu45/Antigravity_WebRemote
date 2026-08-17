"""
E2E Test Suite for Antigravity WebRemote v6
==========================================

This package contains the complete test suite for Antigravity WebRemote v6,
covering all 32 inventoried features across 5 rigorous test tiers:
- Tier 1: Equivalence class feature coverage (>=160 tests)
- Tier 2: Boundary & corner cases (>=160 tests)
- Tier 3: Cross-feature pairwise combinations (>=32 tests)
- Tier 4: Real-world mobile user workflows & E2E scenarios (>=16 tests)
- Tier 5: Adversarial hardening suite

Harness Exports:
----------------
- MockCDPServer: In-process async WebSocket & HTTP mock server emulating Chrome DevTools Protocol.
- MockPushService: Intercepts pywebpush HTTP requests, validating encryption headers and VAPID JWTs.
- MockDOMGenerator: Generates realistic Antigravity chat DOMs, Lexical editors, dialogs, cards, CSS.
- TestClientWrapper: Sync & async FastAPI TestClient wrapper with typed helpers for all 32 endpoints.
- Assertion Helpers: assert_valid_snapshot, assert_valid_djb2_hash, assert_sanitized_html, etc.
- HarnessTestCase: Base test case class with automatic fixture lifecycle and async runner support.
"""

from tests.harness import (
    MockCDPServer,
    MockPushService,
    MockDOMGenerator,
    TestClientWrapper,
    HarnessTestCase,
    async_test,
    with_mock_cdp,
    with_mock_push,
    compute_djb2,
    compute_composite_hash,
    assert_valid_snapshot,
    assert_valid_djb2_hash,
    assert_sanitized_html,
    assert_vapid_key_valid,
    assert_push_subscription_valid,
    assert_push_payload_valid,
    assert_responsive_css,
    assert_service_worker_contract,
    find_free_port,
)

__version__ = "6.0.0"
__all__ = [
    "MockCDPServer",
    "MockPushService",
    "MockDOMGenerator",
    "TestClientWrapper",
    "HarnessTestCase",
    "async_test",
    "with_mock_cdp",
    "with_mock_push",
    "compute_djb2",
    "compute_composite_hash",
    "assert_valid_snapshot",
    "assert_valid_djb2_hash",
    "assert_sanitized_html",
    "assert_vapid_key_valid",
    "assert_push_subscription_valid",
    "assert_push_payload_valid",
    "assert_responsive_css",
    "assert_service_worker_contract",
    "find_free_port",
]
