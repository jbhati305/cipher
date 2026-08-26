# Alexa Direct-Connect (No Lambda) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an Echo Dot talk to the Cipher Bridge running on a laptop directly over a Tailscale
Funnel HTTPS URL, with no AWS Lambda, AWS account, or Cloudflare Tunnel involved — first deployment
proves the wiring works with a simple echo reply, no OpenClaw call required yet.

**Architecture:** Alexa signs every request it sends; the bridge must verify that signature itself
now that Lambda (which used to do this via Amazon's SDK) is gone. A new `alexa_signature.py` module
implements Amazon's documented verification algorithm directly against `cryptography` (already a
resolved dependency, now pinned directly). `app.py`'s `/alexa/query` becomes the literal Alexa skill
endpoint — parsing the raw request envelope and building Alexa's response JSON — instead of a
narrow endpoint that only understood a pre-shaped payload from Lambda.

**Tech Stack:** Python 3.12, FastAPI, `cryptography`, `httpx`, `pytest`/`pytest-asyncio`.

**Spec:** `docs/superpowers/specs/2026-08-27-alexa-direct-connect-design.md`

## Global Constraints

- No OpenClaw call on this pass when `OPENCLAW_GATEWAY_TOKEN` is unset — respond with an echo
  instead (explicit user request: prove wiring first, add OpenClaw later).
- Raw Alexa user ID is hashed immediately on receipt and never logged or stored — same guarantee
  the old Lambda provided, now enforced in the bridge itself.
- No dependency on the low-maintenance `ask-sdk-webservice-support` package — implement the
  documented algorithm directly.
- Timestamp tolerance for Alexa signature verification: 150 seconds (Amazon's documented maximum).
- Signature verification failures return HTTP 400 (Amazon's documented requirement — not 401).
- `ALEXA_BRIDGE_HOST` accepts a loopback address or `0.0.0.0` (fixes a pre-existing bug where the
  Docker Compose deployment's `0.0.0.0` was rejected by validation); `OPENCLAW_BASE_URL` still
  requires strict loopback — these are two different checks, not the same relaxed one.
- Delete `alexa/lambda/`, `infra/aws/`, `infra/cloudflare/` entirely — no unused alternate path.

---

### Task 1: Alexa request-signature verification module

**Files:**
- Modify: `pyproject.toml` (add `cryptography` as a direct pin, matching the version already
  resolved transitively — check with `uv run python -c "import cryptography; print(cryptography.__version__)"`
  and pin exactly that version)
- Create: `src/alexa_bridge/alexa_signature.py`
- Test: `tests/test_alexa_signature.py`

**Interfaces:**
- Produces: `AlexaSignatureError(AuthenticationError)` (import `AuthenticationError` from
  `alexa_bridge.security`); `verify_alexa_signature(body: bytes, headers: Mapping[str, str],
  request_timestamp: str, max_age_seconds: int, *, now: datetime.datetime | None = None,
  http_get: Callable[[str], bytes] | None = None) -> None` — raises `AlexaSignatureError` on any
  failure, returns `None` on success. Task 3 imports both names from this module.

- [ ] **Step 1: Check the resolved `cryptography` version and pin it directly**

Run: `uv run python -c "import cryptography; print(cryptography.__version__)"`
Expected: prints a version like `50.0.1`. Add that exact version to `pyproject.toml`'s
`dependencies` list (alongside `httpx==0.28.1`, etc.): `"cryptography==<printed version>",`. Run
`uv lock` afterward to refresh `uv.lock`.

- [ ] **Step 2: Write the failing tests**

Create `tests/test_alexa_signature.py`:

```python
from __future__ import annotations

import base64
import datetime as dt

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import NameOID

from alexa_bridge.alexa_signature import AlexaSignatureError, verify_alexa_signature

CHAIN_URL = "https://s3.amazonaws.com/echo.api/echo-api-cert.pem"
BODY = b'{"request":{"timestamp":"2026-01-01T00:00:00Z"}}'
TIMESTAMP = "2026-01-01T00:00:00Z"
NOW = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)


def _build_chain(*, san: str = "echo-api.amazon.com") -> tuple[object, bytes]:
    root_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    root_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Test Root CA")])
    now = dt.datetime.now(dt.UTC)
    root_cert = (
        x509.CertificateBuilder()
        .subject_name(root_name)
        .issuer_name(root_name)
        .public_key(root_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(days=1))
        .not_valid_after(now + dt.timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(root_key, hashes.SHA256())
    )
    leaf_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    leaf_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, san)])
    leaf_cert = (
        x509.CertificateBuilder()
        .subject_name(leaf_name)
        .issuer_name(root_name)
        .public_key(leaf_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(days=1))
        .not_valid_after(now + dt.timedelta(days=365))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(san)]), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(root_key, hashes.SHA256())
    )
    chain_pem = leaf_cert.public_bytes(serialization.Encoding.PEM) + root_cert.public_bytes(
        serialization.Encoding.PEM
    )
    return leaf_key, chain_pem


def _sign(body: bytes, leaf_key) -> str:  # noqa: ANN001
    signature = leaf_key.sign(body, padding.PKCS1v15(), hashes.SHA256())
    return base64.b64encode(signature).decode("ascii")


def _headers(body: bytes, leaf_key, *, chain_url: str = CHAIN_URL) -> dict[str, str]:  # noqa: ANN001
    return {"signaturecertchainurl": chain_url, "signature-256": _sign(body, leaf_key)}


def test_valid_signature_is_accepted():
    leaf_key, chain_pem = _build_chain()
    verify_alexa_signature(
        BODY, _headers(BODY, leaf_key), TIMESTAMP, 150, now=NOW, http_get=lambda url: chain_pem
    )


def test_tampered_body_is_rejected():
    leaf_key, chain_pem = _build_chain()
    headers = _headers(BODY, leaf_key)
    with pytest.raises(AlexaSignatureError):
        verify_alexa_signature(
            BODY + b"tampered", headers, TIMESTAMP, 150, now=NOW, http_get=lambda url: chain_pem
        )


def test_expired_timestamp_is_rejected():
    leaf_key, chain_pem = _build_chain()
    headers = _headers(BODY, leaf_key)
    late = NOW + dt.timedelta(seconds=200)
    with pytest.raises(AlexaSignatureError):
        verify_alexa_signature(
            BODY, headers, TIMESTAMP, 150, now=late, http_get=lambda url: chain_pem
        )


def test_wrong_cert_chain_url_host_is_rejected():
    leaf_key, chain_pem = _build_chain()
    headers = _headers(BODY, leaf_key, chain_url="https://evil.example.com/echo.api/cert.pem")
    with pytest.raises(AlexaSignatureError):
        verify_alexa_signature(
            BODY, headers, TIMESTAMP, 150, now=NOW, http_get=lambda url: chain_pem
        )


def test_wrong_san_is_rejected():
    leaf_key, chain_pem = _build_chain(san="not-echo-api.example.com")
    headers = _headers(BODY, leaf_key)
    with pytest.raises(AlexaSignatureError):
        verify_alexa_signature(
            BODY, headers, TIMESTAMP, 150, now=NOW, http_get=lambda url: chain_pem
        )


def test_missing_headers_are_rejected():
    with pytest.raises(AlexaSignatureError):
        verify_alexa_signature(BODY, {}, TIMESTAMP, 150, now=NOW, http_get=lambda url: b"")
```

- [ ] **Step 2b: Run the tests to verify they fail**

Run: `uv run pytest tests/test_alexa_signature.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'alexa_bridge.alexa_signature'`

- [ ] **Step 3: Write the implementation**

Create `src/alexa_bridge/alexa_signature.py`:

```python
from __future__ import annotations

import base64
import binascii
import datetime as dt
from dataclasses import dataclass
from typing import Callable, Mapping
from urllib.parse import urlparse

import httpx
from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.x509.oid import ExtensionOID

from .security import AuthenticationError

_CERT_CHAIN_HOST = "s3.amazonaws.com"
_CERT_CHAIN_PATH_PREFIX = "/echo.api/"
_REQUIRED_SAN = "echo-api.amazon.com"
_CERT_CACHE_MAX_SECONDS = 3600


class AlexaSignatureError(AuthenticationError):
    """Raised when an Alexa request fails signature, certificate, or timestamp checks."""


@dataclass
class _CachedLeaf:
    public_key: object
    expires_at: dt.datetime


_cert_cache: dict[str, _CachedLeaf] = {}


def _default_http_get(url: str) -> bytes:
    response = httpx.get(url, timeout=5.0)
    response.raise_for_status()
    return response.content


def _validate_cert_chain_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise AlexaSignatureError("invalid certificate chain URL scheme")
    if (parsed.hostname or "").lower() != _CERT_CHAIN_HOST:
        raise AlexaSignatureError("invalid certificate chain URL host")
    if parsed.port not in (None, 443):
        raise AlexaSignatureError("invalid certificate chain URL port")
    if not parsed.path.startswith(_CERT_CHAIN_PATH_PREFIX):
        raise AlexaSignatureError("invalid certificate chain URL path")


def _validate_chain(certs: list[x509.Certificate], now: dt.datetime) -> x509.Certificate:
    if not certs:
        raise AlexaSignatureError("empty certificate chain")
    leaf = certs[0]
    if now < leaf.not_valid_before_utc or now > leaf.not_valid_after_utc:
        raise AlexaSignatureError("certificate is not currently valid")
    try:
        san_ext = leaf.extensions.get_extension_for_oid(ExtensionOID.SUBJECT_ALTERNATIVE_NAME)
        names = san_ext.value.get_values_for_type(x509.DNSName)
    except x509.ExtensionNotFound:
        names = []
    if _REQUIRED_SAN not in names:
        raise AlexaSignatureError("certificate is missing the required Alexa hostname")
    for cert, issuer in zip(certs, certs[1:]):
        try:
            cert.verify_directly_issued_by(issuer)
        except (InvalidSignature, ValueError, TypeError) as exc:
            raise AlexaSignatureError("certificate chain signature is invalid") from exc
    root = certs[-1]
    try:
        root.verify_directly_issued_by(root)
    except (InvalidSignature, ValueError, TypeError) as exc:
        raise AlexaSignatureError("certificate chain root is not self-signed") from exc
    return leaf


def _leaf_public_key(url: str, now: dt.datetime, http_get: Callable[[str], bytes]):
    cached = _cert_cache.get(url)
    if cached and cached.expires_at > now:
        return cached.public_key
    try:
        certs = x509.load_pem_x509_certificates(http_get(url))
    except httpx.HTTPError as exc:
        raise AlexaSignatureError("could not fetch certificate chain") from exc
    leaf = _validate_chain(certs, now)
    public_key = leaf.public_key()
    expires_at = min(
        leaf.not_valid_after_utc, now + dt.timedelta(seconds=_CERT_CACHE_MAX_SECONDS)
    )
    _cert_cache[url] = _CachedLeaf(public_key=public_key, expires_at=expires_at)
    return public_key


def verify_alexa_signature(
    body: bytes,
    headers: Mapping[str, str],
    request_timestamp: str,
    max_age_seconds: int,
    *,
    now: dt.datetime | None = None,
    http_get: Callable[[str], bytes] | None = None,
) -> None:
    cert_chain_url = headers.get("signaturecertchainurl")
    signature_b64 = headers.get("signature-256")
    if not cert_chain_url or not signature_b64:
        raise AlexaSignatureError("missing signature headers")
    _validate_cert_chain_url(cert_chain_url)
    current = now or dt.datetime.now(dt.UTC)
    public_key = _leaf_public_key(cert_chain_url, current, http_get or _default_http_get)
    try:
        signature = base64.b64decode(signature_b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise AlexaSignatureError("invalid signature encoding") from exc
    try:
        public_key.verify(signature, body, padding.PKCS1v15(), hashes.SHA256())
    except InvalidSignature as exc:
        raise AlexaSignatureError("signature does not match request body") from exc
    try:
        request_time = dt.datetime.fromisoformat(request_timestamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AlexaSignatureError("invalid request timestamp") from exc
    if abs((current - request_time).total_seconds()) > max_age_seconds:
        raise AlexaSignatureError("stale request timestamp")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_alexa_signature.py -v`
Expected: 6 passed

- [ ] **Step 5: Lint**

Run: `uv run ruff check src/alexa_bridge/alexa_signature.py tests/test_alexa_signature.py`
Expected: All checks passed (fix any `noqa` needs, e.g. unused `url` parameter in lambdas is fine
as-is since ruff doesn't flag lambda parameters).

---

### Task 2: `BridgeSettings` changes

**Files:**
- Modify: `src/alexa_bridge/settings.py` (full replacement below)
- Test: `tests/test_alexa_bridge.py` (settings-only tests added in this task; the rest of the file
  is rewritten in Task 3 — for now only touch the `settings()` fixture and the loopback/secrets
  tests, since Task 3 depends on this fixture's new shape)

**Interfaces:**
- Produces: `BridgeSettings` with fields `id_hmac_secret: str`, `skill_id: str`, `host: str`,
  `port: int`, `max_body_bytes: int`, `signature_max_age_seconds: int`, `rate_limit_per_minute: int`,
  `sync_budget_seconds: float`, `openclaw_timeout_seconds: float`, `openclaw_base_url: str`,
  `openclaw_gateway_token: str`, `openclaw_agent_id: str`, `state_dir: Path`, `log_level: str`,
  `verbose_request_logging: bool`. `bridge_secret` and `hmac_max_age_seconds` no longer exist.
  `validate(require_secrets: bool = True) -> None` raises `ValueError` on: `id_hmac_secret` under
  32 chars (only when `require_secrets`), empty `skill_id` (only when `require_secrets`), any
  numeric field out of range, invalid `openclaw_agent_id`, non-loopback/non-`0.0.0.0` `host`,
  invalid or non-loopback `openclaw_base_url`. Task 3 consumes all of this unchanged from how
  `app.py` already used the old `BridgeSettings`.

- [ ] **Step 1: Replace `src/alexa_bridge/settings.py`**

```python
from __future__ import annotations

import ipaddress
import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

_AGENT_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")


def _is_loopback_host(host: str | None) -> bool:
    if not host:
        return False
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _is_valid_bind_host(host: str | None) -> bool:
    # "0.0.0.0" is accepted only for the bridge's own bind address: a container's port publish
    # (see docker-compose.yml) is what actually restricts external exposure to loopback, since a
    # process bound to 127.0.0.1 inside a container is unreachable through Docker's port
    # publishing. This does NOT apply to OPENCLAW_BASE_URL, which must stay strictly loopback.
    if host == "0.0.0.0":  # noqa: S104
        return True
    return _is_loopback_host(host)


@dataclass(frozen=True)
class BridgeSettings:
    id_hmac_secret: str
    skill_id: str
    host: str
    port: int
    max_body_bytes: int
    signature_max_age_seconds: int
    rate_limit_per_minute: int
    sync_budget_seconds: float
    openclaw_timeout_seconds: float
    openclaw_base_url: str
    openclaw_gateway_token: str
    openclaw_agent_id: str
    state_dir: Path
    log_level: str
    verbose_request_logging: bool

    @classmethod
    def from_env(cls) -> BridgeSettings:
        return cls(
            id_hmac_secret=os.getenv("ALEXA_ID_HMAC_SECRET", ""),
            skill_id=os.getenv("ALEXA_SKILL_ID", ""),
            host=os.getenv("ALEXA_BRIDGE_HOST", "127.0.0.1"),
            port=int(os.getenv("ALEXA_BRIDGE_PORT", "8787")),
            max_body_bytes=int(os.getenv("ALEXA_REQUEST_MAX_BYTES", "16384")),
            signature_max_age_seconds=int(os.getenv("ALEXA_SIGNATURE_MAX_AGE_SECONDS", "150")),
            rate_limit_per_minute=int(os.getenv("ALEXA_RATE_LIMIT_PER_MINUTE", "20")),
            sync_budget_seconds=float(os.getenv("ALEXA_SYNC_BUDGET_SECONDS", "6")),
            openclaw_timeout_seconds=float(os.getenv("ALEXA_OPENCLAW_TIMEOUT_SECONDS", "120")),
            openclaw_base_url=os.getenv("OPENCLAW_BASE_URL", "http://127.0.0.1:18789").rstrip("/"),
            openclaw_gateway_token=os.getenv("OPENCLAW_GATEWAY_TOKEN", ""),
            openclaw_agent_id=os.getenv("OPENCLAW_AGENT_ID", "cipher"),
            state_dir=Path(os.getenv("CIPHER_STATE_DIR", "state")).resolve(),
            log_level=os.getenv("CIPHER_LOG_LEVEL", "INFO"),
            verbose_request_logging=os.getenv("CIPHER_VERBOSE_REQUEST_LOGGING", "false").lower()
            in {"1", "true", "yes"},
        )

    def validate(self, *, require_secrets: bool = True) -> None:
        if require_secrets and len(self.id_hmac_secret) < 32:
            raise ValueError("ALEXA_ID_HMAC_SECRET must contain at least 32 characters")
        if require_secrets and not self.skill_id:
            raise ValueError("ALEXA_SKILL_ID is required")
        if not (1024 <= self.max_body_bytes <= 1_048_576):
            raise ValueError("ALEXA_REQUEST_MAX_BYTES is outside the safe range")
        if not (1 <= self.port <= 65535):
            raise ValueError("ALEXA_BRIDGE_PORT is invalid")
        if not (1 <= self.signature_max_age_seconds <= 3600):
            raise ValueError("ALEXA_SIGNATURE_MAX_AGE_SECONDS is outside the safe range")
        if not (1 <= self.rate_limit_per_minute <= 10_000):
            raise ValueError("ALEXA_RATE_LIMIT_PER_MINUTE is outside the safe range")
        if not (0 < self.sync_budget_seconds <= self.openclaw_timeout_seconds <= 3600):
            raise ValueError("Alexa/OpenClaw timeouts are invalid")
        if not _AGENT_ID_RE.fullmatch(self.openclaw_agent_id):
            raise ValueError("OPENCLAW_AGENT_ID is invalid")
        if not _is_valid_bind_host(self.host):
            raise ValueError("ALEXA_BRIDGE_HOST must be loopback (or 0.0.0.0 for container use)")
        parsed = urlparse(self.openclaw_base_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ValueError("OPENCLAW_BASE_URL is invalid")
        if not _is_loopback_host(parsed.hostname):
            raise ValueError("OPENCLAW_BASE_URL must use a loopback host")
```

- [ ] **Step 2: Replace the top of `tests/test_alexa_bridge.py` with the new settings fixture**

This file currently fails to import (`bridge_secret` no longer exists) — that's expected and fixed
fully in Task 3. For this task, only prove the settings logic itself works via a throwaway check:

Run:
```bash
uv run python -c "
from dataclasses import replace
from pathlib import Path
from alexa_bridge.settings import BridgeSettings

base = BridgeSettings(
    id_hmac_secret='i' * 64, skill_id='amzn1.ask.skill.test', host='127.0.0.1', port=8787,
    max_body_bytes=4096, signature_max_age_seconds=150, rate_limit_per_minute=20,
    sync_budget_seconds=1, openclaw_timeout_seconds=5, openclaw_base_url='http://127.0.0.1:18789',
    openclaw_gateway_token='', openclaw_agent_id='cipher', state_dir=Path('/tmp'),
    log_level='CRITICAL', verbose_request_logging=False,
)
base.validate(require_secrets=True)
replace(base, host='0.0.0.0').validate(require_secrets=True)
print('accepted loopback and 0.0.0.0 as expected')
try:
    replace(base, host='10.0.0.5').validate(require_secrets=True)
    raise SystemExit('should have rejected 10.0.0.5')
except ValueError:
    print('rejected non-loopback, non-zero host as expected')
try:
    replace(base, openclaw_base_url='http://10.0.0.5:18789').validate(require_secrets=True)
    raise SystemExit('should have rejected non-loopback OPENCLAW_BASE_URL')
except ValueError:
    print('rejected non-loopback OPENCLAW_BASE_URL as expected')
"
```
Expected: prints all three "as expected" lines with no `SystemExit`.

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml uv.lock src/alexa_bridge/settings.py \
  src/alexa_bridge/alexa_signature.py tests/test_alexa_signature.py
git commit -m "feat: add Alexa signature verification and update bridge settings"
```
(Skip if not asked to commit this session — leave staged/unstaged per the user's standing "don't
commit unless asked" instruction; treat this step as informational only.)

---

### Task 3: Rewrite the Alexa Bridge endpoint

**Files:**
- Modify: `src/alexa_bridge/app.py` (full replacement below)
- Modify: `src/alexa_bridge/security.py` (remove `verify_hmac_request`, keep everything else)
- Modify: `tests/test_alexa_bridge.py` (full replacement below)

**Interfaces:**
- Consumes: `verify_alexa_signature`/`AlexaSignatureError` from Task 1;
  `BridgeSettings`/`_is_valid_bind_host` shape from Task 2; `ReplayStore.accept_once(key: str,
  expires_at: int) -> bool` and `RateLimiter.allow(key: str) -> bool` from `security.py`
  (unchanged); `TaskStore` (unchanged); `OpenClawClient.ask(query, requester_hash,
  correlation_id) -> str` (unchanged).
- Produces: `create_app(...)` unchanged signature; `AlexaRequestEnvelope` pydantic model (not
  consumed elsewhere, internal to this module).

- [ ] **Step 1: Remove `verify_hmac_request` from `src/alexa_bridge/security.py`**

Delete the `verify_hmac_request` function entirely (the whole function body from `def
verify_hmac_request(` through its closing line). Keep `AuthenticationError`, `ReplayStore`, and
`RateLimiter` exactly as they are — `ReplayStore.accept_once` is reused as-is in `app.py` below,
just called with a different kind of key (Alexa's `requestId` instead of an HMAC signature).

- [ ] **Step 2: Write the failing tests — replace `tests/test_alexa_bridge.py` entirely**

```python
from __future__ import annotations

import asyncio
import hashlib
import hmac as hmac_module
import uuid
from dataclasses import replace
from pathlib import Path

import httpx
import pytest

import alexa_bridge.app as app_module
from alexa_bridge.alexa_signature import AlexaSignatureError
from alexa_bridge.app import create_app
from alexa_bridge.security import ReplayStore
from alexa_bridge.settings import BridgeSettings
from alexa_bridge.tasks import TaskStore

SKILL_ID = "amzn1.ask.skill.test"
RAW_USER_ID = "amzn1.ask.account.test-user"
ID_HMAC_SECRET = "i" * 64


class FakeOpenClaw:
    def __init__(self, answer: str = "All healthy.", delay: float = 0) -> None:
        self.answer = answer
        self.delay = delay
        self.calls = []

    async def ask(self, query, requester_hash, correlation_id):  # noqa: ANN001, ANN201
        self.calls.append((query, requester_hash, correlation_id))
        if self.delay:
            await asyncio.sleep(self.delay)
        return self.answer


def settings(
    tmp_path: Path, *, budget: float = 1, openclaw_token: str = "gateway-token"
) -> BridgeSettings:
    return BridgeSettings(
        id_hmac_secret=ID_HMAC_SECRET,
        skill_id=SKILL_ID,
        host="127.0.0.1",
        port=8787,
        max_body_bytes=4096,
        signature_max_age_seconds=150,
        rate_limit_per_minute=20,
        sync_budget_seconds=budget,
        openclaw_timeout_seconds=5,
        openclaw_base_url="http://127.0.0.1:18789",
        openclaw_gateway_token=openclaw_token,
        openclaw_agent_id="cipher",
        state_dir=tmp_path,
        log_level="CRITICAL",
        verbose_request_logging=False,
    )


def envelope(
    *,
    request_type: str = "IntentRequest",
    intent_name: str = "CipherQueryIntent",
    query: str | None = "check my server",
    request_id: str | None = None,
) -> dict:
    body: dict = {
        "version": "1.0",
        "session": {
            "application": {"applicationId": SKILL_ID},
            "user": {"userId": RAW_USER_ID},
        },
        "request": {
            "type": request_type,
            "requestId": request_id or f"amzn1.echo-api.request.{uuid.uuid4()}",
            "timestamp": "2026-01-01T00:00:00Z",
        },
    }
    if request_type == "IntentRequest":
        body["request"]["intent"] = {"name": intent_name, "slots": {}}
        if intent_name == "CipherQueryIntent" and query is not None:
            body["request"]["intent"]["slots"] = {"Query": {"value": query}}
    return body


def make_app(
    tmp_path: Path, fake: FakeOpenClaw, *, budget: float = 1, openclaw_token: str = "gateway-token"
):
    config = settings(tmp_path, budget=budget, openclaw_token=openclaw_token)
    return create_app(
        config,
        openclaw_client=fake,
        replay_store=ReplayStore(tmp_path / "replay.sqlite3"),
        task_store=TaskStore(tmp_path / "tasks.sqlite3"),
    )


@pytest.fixture(autouse=True)
def _accept_signature(monkeypatch):
    monkeypatch.setattr(app_module, "verify_alexa_signature", lambda *a, **k: None)  # noqa: ARG005


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("host", "10.0.0.5"),
        ("openclaw_base_url", "http://192.168.1.20:18789"),
        ("openclaw_base_url", "http://user:password@127.0.0.1:18789"),
    ],
)
def test_bridge_rejects_non_loopback_or_credentialed_endpoints(tmp_path, field, value):
    with pytest.raises(ValueError):
        replace(settings(tmp_path), **{field: value}).validate(require_secrets=True)


def test_bridge_accepts_zero_bind_host_for_container_use(tmp_path):
    replace(settings(tmp_path), host="0.0.0.0").validate(require_secrets=True)


@pytest.mark.asyncio
async def test_launch_request_greets(tmp_path):
    app = make_app(tmp_path, FakeOpenClaw())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/alexa/query", json=envelope(request_type="LaunchRequest"))
    assert response.status_code == 200
    assert "Cipher online" in response.json()["response"]["outputSpeech"]["text"]


@pytest.mark.asyncio
async def test_help_intent(tmp_path):
    app = make_app(tmp_path, FakeOpenClaw())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/alexa/query", json=envelope(intent_name="AMAZON.HelpIntent")
        )
    assert response.json()["response"]["shouldEndSession"] is False
    assert "Ask me a question" in response.json()["response"]["outputSpeech"]["text"]


@pytest.mark.asyncio
async def test_stop_intent_ends_session(tmp_path):
    app = make_app(tmp_path, FakeOpenClaw())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/alexa/query", json=envelope(intent_name="AMAZON.StopIntent")
        )
    assert response.json()["response"]["shouldEndSession"] is True


@pytest.mark.asyncio
async def test_query_intent_echoes_when_openclaw_not_configured(tmp_path):
    app = make_app(tmp_path, FakeOpenClaw(), openclaw_token="")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/alexa/query", json=envelope(query="check my server"))
    text = response.json()["response"]["outputSpeech"]["text"]
    assert "Cipher heard you say: check my server" in text
    assert "isn't connected yet" in text


@pytest.mark.asyncio
async def test_query_intent_calls_openclaw_when_configured(tmp_path):
    fake = FakeOpenClaw()
    app = make_app(tmp_path, fake)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/alexa/query", json=envelope(query="check my server"))
    assert response.json()["response"]["outputSpeech"]["text"] == "All healthy."
    expected_hash = hmac_module.new(
        ID_HMAC_SECRET.encode(), RAW_USER_ID.encode(), hashlib.sha256
    ).hexdigest()
    assert fake.calls[0] == ("check my server", expected_hash, fake.calls[0][2])


@pytest.mark.asyncio
async def test_empty_query_slot_reprompts(tmp_path):
    app = make_app(tmp_path, FakeOpenClaw())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/alexa/query", json=envelope(query=""))
    assert "didn't catch" in response.json()["response"]["outputSpeech"]["text"]


@pytest.mark.asyncio
async def test_wrong_application_id_rejected(tmp_path):
    app = make_app(tmp_path, FakeOpenClaw())
    body = envelope()
    body["session"]["application"]["applicationId"] = "amzn1.ask.skill.someone-else"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/alexa/query", json=body)
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_invalid_signature_returns_400(tmp_path, monkeypatch):
    def _raise(*_args, **_kwargs):
        raise AlexaSignatureError("bad signature")

    monkeypatch.setattr(app_module, "verify_alexa_signature", _raise)
    app = make_app(tmp_path, FakeOpenClaw())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/alexa/query", json=envelope())
    assert response.status_code == 400
    assert response.json() == {"error": "invalid_signature"}


@pytest.mark.asyncio
async def test_replayed_request_id_rejected(tmp_path):
    app = make_app(tmp_path, FakeOpenClaw())
    body = envelope(request_id="amzn1.echo-api.request.fixed")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        first = await client.post("/alexa/query", json=body)
        second = await client.post("/alexa/query", json=body)
    assert first.status_code == 200
    assert second.status_code == 400


@pytest.mark.asyncio
async def test_unconfigured_bridge_refuses_queries(tmp_path):
    config = replace(settings(tmp_path), id_hmac_secret="")
    app = create_app(
        config,
        openclaw_client=FakeOpenClaw(),
        replay_store=ReplayStore(tmp_path / "replay.sqlite3"),
        task_store=TaskStore(tmp_path / "tasks.sqlite3"),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/alexa/query", json=envelope())
    assert response.status_code == 503
    assert response.json() == {"error": "not_ready"}


@pytest.mark.asyncio
async def test_malformed_body_returns_400(tmp_path):
    app = make_app(tmp_path, FakeOpenClaw())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/alexa/query", content=b"{not json", headers={"content-type": "application/json"}
        )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_timeout_returns_pending_without_cancelling_work(tmp_path):
    fake = FakeOpenClaw(answer="Analysis complete.", delay=0.1)
    app = make_app(tmp_path, fake, budget=0.001)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/alexa/query", json=envelope(query="analyze a large log")
        )
        await asyncio.sleep(0.12)
        result_response = await client.post(
            "/alexa/query",
            json=envelope(
                query="what's the result of my last task",
                request_id="amzn1.echo-api.request.result",
            ),
        )
    assert response.status_code == 200
    text = response.json()["response"]["outputSpeech"]["text"]
    assert "still working" in text
    assert result_response.json()["response"]["outputSpeech"]["text"] == "Analysis complete."
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_alexa_bridge.py -v`
Expected: FAIL — `app.py` still references removed `BridgeSettings` fields and the old
`{"answer": ...}` response shape (import errors / attribute errors / assertion failures).

- [ ] **Step 4: Replace `src/alexa_bridge/app.py` entirely**

```python
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError

from .alexa_signature import AlexaSignatureError, verify_alexa_signature
from .logging import configure_logging
from .openclaw import OpenClawClient
from .security import RateLimiter, ReplayStore
from .settings import BridgeSettings
from .tasks import TaskStore

LOGGER = logging.getLogger("cipher.alexa_bridge")
_LAST_RESULT_QUERIES = {
    "what is the result of my last task",
    "what's the result of my last task",
    "whats the result of my last task",
    "get the result of my last task",
    "my last task",
}


class _Slot(BaseModel):
    value: str | None = None


class _Intent(BaseModel):
    name: str
    slots: dict[str, _Slot] = Field(default_factory=dict)


class _AlexaRequestBody(BaseModel):
    type: str
    requestId: str
    timestamp: str
    intent: _Intent | None = None


class _User(BaseModel):
    userId: str


class _Application(BaseModel):
    applicationId: str


class _SessionSection(BaseModel):
    application: _Application | None = None
    user: _User | None = None


class _System(BaseModel):
    application: _Application
    user: _User | None = None


class _ContextSection(BaseModel):
    System: _System


class AlexaRequestEnvelope(BaseModel):
    version: str
    session: _SessionSection | None = None
    context: _ContextSection | None = None
    request: _AlexaRequestBody

    @property
    def application_id(self) -> str:
        if self.session and self.session.application:
            return self.session.application.applicationId
        if self.context:
            return self.context.System.application.applicationId
        return ""

    @property
    def raw_user_id(self) -> str:
        if self.session and self.session.user:
            return self.session.user.userId
        if self.context and self.context.System.user:
            return self.context.System.user.userId
        return ""


def _normalize_query(value: str) -> str:
    return " ".join(value.strip().lower().rstrip(".?!").split())


def _latest_result_response(store: TaskStore, requester_hash: str) -> str:
    task = store.latest(requester_hash)
    if not task:
        return "You don't have a recent Cipher task."
    if task["status"] == "completed":
        return str(task["result"])
    if task["status"] == "running":
        return "I'm still working on your last task. Ask me again in a moment."
    if task["status"] == "interrupted":
        return "Your last task was interrupted when the Cipher bridge restarted. Please ask again."
    return "Your last task failed. Please try again or check Cipher's private logs."


def _alexa_response(
    text: str, *, end_session: bool, reprompt: str | None = None
) -> dict[str, Any]:
    response: dict[str, Any] = {
        "outputSpeech": {"type": "PlainText", "text": text},
        "shouldEndSession": end_session,
    }
    if reprompt:
        response["reprompt"] = {"outputSpeech": {"type": "PlainText", "text": reprompt}}
    return {"version": "1.0", "sessionAttributes": {}, "response": response}


def create_app(
    settings: BridgeSettings | None = None,
    *,
    openclaw_client: OpenClawClient | None = None,
    replay_store: ReplayStore | None = None,
    task_store: TaskStore | None = None,
) -> FastAPI:
    config = settings or BridgeSettings.from_env()
    config.validate(require_secrets=False)
    configure_logging(config.log_level)
    replay = replay_store or ReplayStore(config.state_dir / "alexa-replay.sqlite3")
    tasks = task_store or TaskStore(config.state_dir / "alexa-tasks.sqlite3")
    rate_limiter = RateLimiter(config.rate_limit_per_minute)
    client = openclaw_client or OpenClawClient(
        base_url=config.openclaw_base_url,
        token=config.openclaw_gateway_token,
        agent_id=config.openclaw_agent_id,
        timeout_seconds=config.openclaw_timeout_seconds,
    )
    app = FastAPI(title="Cipher Alexa Bridge", docs_url=None, redoc_url=None)
    app.state.background_tasks = set()

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    async def readyz() -> JSONResponse:
        try:
            config.validate(require_secrets=True)
        except ValueError as exc:
            return JSONResponse({"status": "not_ready", "reason": str(exc)}, status_code=503)
        return JSONResponse({"status": "ready"})

    @app.post("/alexa/query")
    async def alexa_query(request: Request) -> JSONResponse:
        started = time.monotonic()
        correlation_id = str(uuid.uuid4())
        try:
            config.validate(require_secrets=True)
        except ValueError:
            return JSONResponse({"error": "not_ready"}, status_code=503)
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > config.max_body_bytes:
                    return JSONResponse({"error": "request_too_large"}, status_code=413)
            except ValueError:
                return JSONResponse({"error": "invalid_content_length"}, status_code=400)
        body = await request.body()
        if len(body) > config.max_body_bytes:
            return JSONResponse({"error": "request_too_large"}, status_code=413)
        try:
            raw = json.loads(body)
            envelope = AlexaRequestEnvelope.model_validate(raw)
        except (json.JSONDecodeError, ValidationError):
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        try:
            verify_alexa_signature(
                body,
                request.headers,
                envelope.request.timestamp,
                config.signature_max_age_seconds,
            )
        except AlexaSignatureError:
            LOGGER.warning(
                "alexa signature rejected",
                extra={
                    "request_id": correlation_id,
                    "channel": "alexa",
                    "operation": "authenticate",
                    "status": "rejected",
                },
            )
            return JSONResponse({"error": "invalid_signature"}, status_code=400)
        if envelope.application_id != config.skill_id:
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        if not replay.accept_once(
            envelope.request.requestId, int(time.time()) + config.signature_max_age_seconds
        ):
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        raw_user_id = envelope.raw_user_id
        if not raw_user_id:
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        user_hash = hmac.new(
            config.id_hmac_secret.encode("utf-8"), raw_user_id.encode("utf-8"), hashlib.sha256
        ).hexdigest()

        req = envelope.request
        if req.type == "LaunchRequest":
            return JSONResponse(
                _alexa_response(
                    "Cipher online. What do you need?",
                    end_session=False,
                    reprompt="What do you need?",
                )
            )
        if req.type == "SessionEndedRequest":
            return JSONResponse({})
        if req.type != "IntentRequest" or req.intent is None:
            return JSONResponse(
                _alexa_response(
                    "I didn't understand that request. Please try again.", end_session=False
                )
            )
        name = req.intent.name
        if name in ("AMAZON.StopIntent", "AMAZON.CancelIntent"):
            return JSONResponse(_alexa_response("Cipher offline.", end_session=True))
        if name == "AMAZON.HelpIntent":
            return JSONResponse(
                _alexa_response(
                    "Ask me a question or give me a task. For example, say check my server "
                    "health.",
                    end_session=False,
                    reprompt="What should Cipher do?",
                )
            )
        if name == "CipherQueryIntent":
            slot = req.intent.slots.get("Query")
            query = (slot.value or "").strip() if slot else ""
        elif name == "AMAZON.YesIntent":
            query = "yes"
        elif name == "AMAZON.NoIntent":
            query = "no"
        else:
            return JSONResponse(
                _alexa_response(
                    "I can't handle that Alexa intent. Try asking Cipher directly.",
                    end_session=False,
                )
            )
        if not query:
            return JSONResponse(
                _alexa_response(
                    "I didn't catch the request. Please say it again.",
                    end_session=False,
                    reprompt="What do you need?",
                )
            )
        if not config.openclaw_gateway_token:
            return JSONResponse(
                _alexa_response(
                    f"Cipher heard you say: {query}. The full assistant isn't connected yet.",
                    end_session=False,
                )
            )
        if not rate_limiter.allow(user_hash):
            return JSONResponse({"error": "rate_limited"}, status_code=429)
        if _normalize_query(query) in _LAST_RESULT_QUERIES:
            answer = _latest_result_response(tasks, user_hash)
            return JSONResponse(
                _alexa_response(answer, end_session=False, reprompt="Anything else?")
            )

        task_id = tasks.create(user_hash)

        async def run_task() -> str:
            try:
                answer = await client.ask(query, user_hash, correlation_id)
            except Exception as exc:
                tasks.fail(task_id, type(exc).__name__)
                raise
            tasks.complete(task_id, answer)
            return answer

        running = asyncio.create_task(run_task(), name=f"cipher-alexa-{task_id}")
        app.state.background_tasks.add(running)
        running.add_done_callback(app.state.background_tasks.discard)
        try:
            answer = await asyncio.wait_for(
                asyncio.shield(running), timeout=config.sync_budget_seconds
            )
            status = "completed"
            speech, reprompt = answer, "Anything else?"
        except TimeoutError:
            status = "pending"
            speech = "I'm still working on that. Ask me for the result in a moment."
            reprompt = None
        except Exception:
            status = "failed"
            speech = "I couldn't reach Cipher safely. Please try again in a moment."
            reprompt = None
        LOGGER.info(
            "request completed",
            extra={
                "request_id": correlation_id,
                "channel": "alexa",
                "operation": "openclaw_response",
                "duration_ms": round((time.monotonic() - started) * 1000),
                "status": status,
            },
        )
        return JSONResponse(_alexa_response(speech, end_session=False, reprompt=reprompt))

    return app


app = create_app()


def main() -> None:
    import uvicorn

    settings = BridgeSettings.from_env()
    settings.validate(require_secrets=True)
    uvicorn.run("alexa_bridge.app:app", host=settings.host, port=settings.port, proxy_headers=False)


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_alexa_bridge.py tests/test_alexa_signature.py -v`
Expected: all pass (14 tests in `test_alexa_bridge.py` + 6 in `test_alexa_signature.py`)

- [ ] **Step 6: Lint**

Run: `uv run ruff check src/alexa_bridge/ tests/test_alexa_bridge.py`
Expected: All checks passed

- [ ] **Step 7: Commit** (informational only per the standing no-commit instruction — stage/verify, don't commit unless asked)

```bash
git add src/alexa_bridge/app.py src/alexa_bridge/security.py tests/test_alexa_bridge.py
```

---

### Task 4: Remove Lambda/AWS/Cloudflare and update the CLI, doctor, and env template

**Files:**
- Delete: `alexa/lambda/` (entire directory: `index.mjs`, `index.test.mjs`, `package.json`)
- Delete: `infra/aws/` (entire directory: `template.yaml`)
- Delete: `infra/cloudflare/` (entire directory: `config.example.yml`)
- Modify: `scripts/package-alexa.py`
- Modify: `cipher` (the CLI entry point)
- Modify: `scripts/doctor.py`
- Modify: `.env.example`
- Modify: `scripts/bootstrap.sh`
- Modify: `tests/test_policy_and_tools.py`

**Interfaces:**
- Produces: `./cipher alexa package` (stages interaction models + skill manifest, no Lambda
  artifact); `./cipher tunnel setup` / `./cipher tunnel status` (Tailscale-based, replacing the
  cloudflared-based versions).

- [ ] **Step 1: Delete the AWS/Lambda/Cloudflare directories**

```bash
rm -rf alexa/lambda infra/aws infra/cloudflare
```

- [ ] **Step 2: Replace `scripts/package-alexa.py`**

```python
#!/usr/bin/env python3
from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist" / "alexa"


def main() -> None:
    if DIST.exists():
        shutil.rmtree(DIST)
    (DIST / "interaction-models").mkdir(parents=True)
    shutil.copytree(
        ROOT / "alexa/interaction-models", DIST / "interaction-models", dirs_exist_ok=True
    )
    shutil.copy2(ROOT / "alexa/skill-package/skill.json", DIST / "skill.json")
    print(f"Skill assets ready for manual import into the Alexa Developer Console: {DIST}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Update the `cipher` CLI**

In the `cipher` file:
1. Remove the now-unused `from urllib.parse import urlparse` import.
2. Replace the `alexa` function:

```python
def alexa(_args: argparse.Namespace) -> None:
    load_env()
    run(sys.executable, str(ROOT / "scripts/package-alexa.py"))
```

3. Replace the `tunnel` function:

```python
def tunnel(args: argparse.Namespace) -> None:
    load_env()
    if shutil.which("tailscale") is None:
        raise SystemExit("tailscale is not installed. See docs/ALEXA.md.")
    port = os.environ.get("ALEXA_BRIDGE_PORT", "8787")
    if args.tunnel_command == "status":
        run("tailscale", "funnel", "status", check=False)
        return
    print("Opening Tailscale's interactive login flow.")
    run("tailscale", "up")
    print("Enable HTTPS certificates and Funnel for this tailnet in the Tailscale admin console.")
    print(f"Then run: sudo tailscale funnel {port}")
    print("Paste the printed https://<name>.ts.net URL into the Alexa Developer Console.")
    print("See docs/ALEXA.md for the full walkthrough.")
```

4. In `build_parser()`, update the two parser definitions:

```python
    alexa_parser = sub.add_parser("alexa", help="Stage Alexa skill assets for manual console import")
    alexa_parser.add_argument("alexa_command", choices=("package",))
    alexa_parser.set_defaults(func=alexa)
    tunnel_parser = sub.add_parser("tunnel", help="Set up or inspect the Tailscale Funnel")
    tunnel_parser.add_argument("tunnel_command", choices=("setup", "status"))
    tunnel_parser.set_defaults(func=tunnel)
```

- [ ] **Step 4: Update `scripts/doctor.py`**

Replace this block (the `CIPHER_PUBLIC_URL` check and the Cloudflare Tunnel check at the end of
`check_integrations()`):

```python
    public_url = urlparse(os.getenv("CIPHER_PUBLIC_URL", ""))
    if public_url.scheme == "https" and public_url.hostname:
        result("PASS", "Alexa ingress", "HTTPS URL configured; only /alexa/* should route")
    elif os.getenv("CIPHER_PUBLIC_URL"):
        result("FAIL", "Alexa ingress", "CIPHER_PUBLIC_URL must be a valid HTTPS origin")
    else:
        result("SETUP", "Alexa ingress", "configure Cloudflare Tunnel or another HTTPS ingress")
```

and

```python
    tunnel_id = os.getenv("CLOUDFLARE_TUNNEL_ID", "")
    if tunnel_id and shutil.which("cloudflared"):
        tunnel = command("cloudflared", "tunnel", "info", tunnel_id)
        if tunnel and tunnel.returncode == 0:
            result("PASS", "Cloudflare Tunnel", "configured tunnel found")
        else:
            result("FAIL", "Cloudflare Tunnel", "tunnel lookup failed")
    else:
        result("OPTIONAL", "Cloudflare Tunnel", "not configured")
```

with a single Tailscale-based check placed where the first block was:

```python
    if shutil.which("tailscale"):
        funnel = command("tailscale", "funnel", "status")
        bridge_port = os.getenv("ALEXA_BRIDGE_PORT", "8787")
        if funnel and funnel.returncode == 0 and bridge_port in funnel.stdout:
            result("PASS", "Alexa ingress", "Tailscale Funnel is serving the bridge port")
        else:
            result("SETUP", "Alexa ingress", f"run: sudo tailscale funnel {bridge_port}")
    else:
        result("SETUP", "Alexa ingress", "install Tailscale; see docs/ALEXA.md")
```

`urlparse` stays imported (still used for `OPENCLAW_BASE_URL` a few lines below).

- [ ] **Step 5: Update `.env.example`**

Replace:
```env
# Alexa bridge. Generate with: openssl rand -hex 32
ALEXA_BRIDGE_SECRET=
ALEXA_ID_HMAC_SECRET=
ALEXA_SKILL_ID=
ALEXA_BRIDGE_HOST=127.0.0.1
ALEXA_BRIDGE_PORT=8787
ALEXA_SYNC_BUDGET_SECONDS=6
ALEXA_OPENCLAW_TIMEOUT_SECONDS=120
ALEXA_REQUEST_MAX_BYTES=16384
ALEXA_HMAC_MAX_AGE_SECONDS=60
ALEXA_RATE_LIMIT_PER_MINUTE=20
CIPHER_PUBLIC_URL=

# Optional Cloudflare tunnel metadata (credentials never belong here).
CLOUDFLARE_TUNNEL_ID=
CLOUDFLARE_TUNNEL_HOSTNAME=
CLOUDFLARE_CREDENTIALS_FILE=
```
with:
```env
# Alexa bridge. Generate with: openssl rand -hex 32
ALEXA_ID_HMAC_SECRET=
# From the Alexa Developer Console: Custom Skill -> Endpoint -> Skill ID.
ALEXA_SKILL_ID=
ALEXA_BRIDGE_HOST=127.0.0.1
ALEXA_BRIDGE_PORT=8787
ALEXA_SYNC_BUDGET_SECONDS=6
ALEXA_OPENCLAW_TIMEOUT_SECONDS=120
ALEXA_REQUEST_MAX_BYTES=16384
ALEXA_SIGNATURE_MAX_AGE_SECONDS=150
ALEXA_RATE_LIMIT_PER_MINUTE=20
```

- [ ] **Step 6: Update `scripts/bootstrap.sh`**

Remove this line (the `ALEXA_BRIDGE_SECRET` generation — `ALEXA_ID_HMAC_SECRET` generation stays,
it's still a real secret the bridge now consumes directly):
```bash
  sed -i "s/^ALEXA_BRIDGE_SECRET=.*/ALEXA_BRIDGE_SECRET=${secret}/" .env
```
and remove the now-unused `secret="$(openssl rand -hex 32)"` line above it (keep `id_secret` and
`gateway_token`).

- [ ] **Step 7: Fix `tests/test_policy_and_tools.py`**

Replace:
```python
    monkeypatch.setenv("ALEXA_BRIDGE_SECRET", "must-not-leak")
```
and
```python
    assert "ALEXA_BRIDGE_SECRET" not in captured["env"]
```
with `ALEXA_ID_HMAC_SECRET` in both places (same test intent — a secret env var must never reach a
subprocess — using a variable name that still exists after this change).

- [ ] **Step 8: Run the affected tests**

Run: `uv run pytest tests/test_policy_and_tools.py tests/test_alexa_bridge.py tests/test_alexa_signature.py -v`
Expected: all pass

Run: `bash -n scripts/package-alexa.py 2>&1; python3 -m py_compile scripts/package-alexa.py cipher scripts/doctor.py`
Expected: no output (both are Python, `bash -n` on a `.py` file will error — only run `py_compile`
on the two `.py` files and `cipher`; `bash -n` isn't applicable here, skip it for this step)

Run: `bash -n scripts/bootstrap.sh`
Expected: no output

- [ ] **Step 9: Commit** (informational — stage only, per no-commit-unless-asked)

```bash
git add -A alexa/lambda infra/aws infra/cloudflare scripts/package-alexa.py cipher \
  scripts/doctor.py .env.example scripts/bootstrap.sh tests/test_policy_and_tools.py
```

---

### Task 5: Documentation updates

**Files:**
- Modify: `docs/ALEXA.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/INSTALL.md`
- Modify: `docs/TROUBLESHOOTING.md`
- Modify: `docs/SECURITY.md`
- Modify: `README.md` (architecture diagram and feature bullets only — the mandated opening two
  lines are untouched)

- [ ] **Step 1: Rewrite `docs/ALEXA.md`**

Replace the "Package and deploy" section (from `## Package and deploy` through the official
references list) with:

```markdown
## Connect your laptop

No AWS account or Lambda function is needed — Alexa calls the Cipher Bridge on your laptop
directly over a [Tailscale Funnel](https://tailscale.com/docs/features/tailscale-funnel) HTTPS
URL, which Amazon accepts as a self-hosted web-service endpoint as long as it presents a
publicly-trusted certificate (Funnel's `*.ts.net` certificate, issued by Let's Encrypt, qualifies)
and verifies the request signature itself — which the bridge now does
(`src/alexa_bridge/alexa_signature.py`).

1. Install Tailscale on the laptop and sign in: `sudo tailscale up`.
2. In the Tailscale admin console, enable HTTPS certificates and Funnel for this tailnet (Funnel
   is off by default).
3. Start the bridge (`./cipher up`), then expose it: `sudo tailscale funnel 8787`. Tailscale
   prints a public URL such as `https://<device-name>.<tailnet-name>.ts.net`.
4. In the Alexa Developer Console, create a **Custom** skill named Cipher with invocation name
   `cipher`. Enable `en-US` and `en-IN`.
5. Copy the skill ID to `ALEXA_SKILL_ID` in `.env`, and generate `ALEXA_ID_HMAC_SECRET` (see
   `./cipher setup`, which generates it automatically).
6. Set the skill's endpoint to the Funnel URL from step 3, path `/alexa/query`
   (`https://<device-name>.<tailnet-name>.ts.net/alexa/query`), and choose "My development
   endpoint has a certificate from a trusted certificate authority."
7. Run `./cipher alexa package` and import/build `alexa/interaction-models/en-US.json` and
   `en-IN.json` in their locales from the generated `dist/alexa/` assets.
8. Test `LaunchRequest`, a query, and Yes/No confirmation in the Alexa simulator before trying a
   real Echo device.

The bridge verifies every request's Alexa signature and checks `applicationId` against
`ALEXA_SKILL_ID` before doing anything else — an unsigned or mis-addressed request never reaches
intent handling. It HMAC-hashes the raw Alexa user ID immediately on receipt and never logs it.

`./cipher tunnel setup` runs `tailscale up` and prints the exact next steps; `./cipher tunnel
status` runs `tailscale funnel status`.

Official references reviewed 2026-08-27:
[custom skill invocation](https://developer.amazon.com/en-US/docs/alexa/custom-skills/understanding-how-users-invoke-custom-skills.html),
[`AMAZON.SearchQuery`](https://developer.amazon.com/en-GB/docs/alexa/custom-skills/slot-type-reference.html),
[hosting a custom skill as a web service](https://developer.amazon.com/en-US/docs/alexa/custom-skills/host-a-custom-skill-as-a-web-service.html),
and [request handling](https://developer.amazon.com/en-US/docs/alexa/custom-skills/handle-requests-sent-by-alexa.html).
```

Also update the earlier paragraph in the same file that still says "Yes and No are forwarded into
the same stable OpenClaw conversation so an exact pending action can continue" — leave that
sentence as-is (still true once OpenClaw is connected); no other edits needed in the file above
this section.

- [ ] **Step 2: Update `docs/ARCHITECTURE.md`**

Replace the "Boundaries" diagram's first two lines:
```text
Alexa -> Lambda -> TLS ingress -> 127.0.0.1:8787 Alexa Bridge
                                      |
```
with:
```text
Alexa -> Tailscale Funnel (public HTTPS) -> 127.0.0.1:8787 Alexa Bridge
                                      |
```
And replace the sentence "The Cloudflare ingress has one hostname/path rule for `/alexa/*`,
followed by a required 404 catch-all. It has no route to the Gateway, Home Assistant, Codex,
Claude, MCP, or host admin UI." with: "Tailscale Funnel exposes only the bridge's port; nothing
else on the laptop is reachable through it, since Funnel forwards exactly one local port and the
Gateway/Codex/Claude/MCP/Home Assistant ports are never passed to `tailscale funnel`."

- [ ] **Step 3: Update `docs/INSTALL.md`**

Remove the entire `## Cloudflare Tunnel` section (from that heading through the official
references paragraph that follows it), replacing it with:

```markdown
## Tailscale Funnel

See `docs/ALEXA.md`'s "Connect your laptop" section for the full walkthrough
(`tailscale up`, enabling Funnel, `sudo tailscale funnel 8787`, and configuring the Alexa skill
endpoint).
```

Keep the "Container deployment (optional)" section added in the previous session as-is.

- [ ] **Step 4: Update `docs/TROUBLESHOOTING.md`**

Replace:
```markdown
## Alexa says it could not reach Cipher

Check, in order: `./cipher status`, `/readyz`, tunnel ingress validation, Lambda environment values,
matching bridge secrets, and the Lambda's skill-ID trigger. HMAC failures intentionally return only
`unauthorized`; use the bridge correlation logs without enabling raw request logging.
```
with:
```markdown
## Alexa says it could not reach Cipher

Check, in order: `./cipher status`, `/readyz`, `tailscale funnel status`, that `ALEXA_SKILL_ID` in
`.env` matches the Developer Console exactly, and that the console's endpoint path is
`/alexa/query`. Signature and application-ID failures intentionally return only
`invalid_signature`/`invalid_request`; use the bridge's correlation-ID logs without enabling raw
request logging.
```

- [ ] **Step 5: Update `docs/SECURITY.md`**

Replace the three table rows:
```markdown
| Malicious/replayed Alexa request | Lambda skill-ID restriction; HMAC over timestamp/body; 60-second freshness; one-time replay database; size and rate limits |
| Stolen bridge secret | Rotate both Lambda and `.env`; tunnel path still exposes only bridge; inspect structured request IDs; rate limiting limits immediate abuse |
| Exposed Cloudflare hostname | Path-only ingress plus final 404; bridge authentication; no Gateway route |
```
with:
```markdown
| Malicious/replayed Alexa request | Bridge verifies Alexa's request signature and certificate chain directly; `applicationId` checked against `ALEXA_SKILL_ID`; 150-second freshness; one-time replay database keyed on Alexa's `requestId`; size and rate limits |
| Stolen `ALEXA_ID_HMAC_SECRET` | Rotate in `.env` and restart the bridge; an attacker still cannot forge a valid Alexa request signature, since that key never leaves Amazon |
| Exposed Tailscale Funnel URL | Funnel forwards exactly one local port (the bridge); Gateway/Codex/Claude/MCP/Home Assistant ports are never funneled; bridge authentication (Alexa signature + `applicationId` check) still applies |
```

- [ ] **Step 6: Update `README.md`**

Replace:
```text
Alexa Custom Skill -> AWS Lambda -> HTTPS tunnel -> Alexa Bridge (loopback)
```
with:
```text
Alexa Custom Skill -> Tailscale Funnel -> Alexa Bridge (loopback)
```
Replace:
```markdown
- HMAC-authenticated Alexa bridge with replay defense, rate/size limits, private logging, stable
  conversations, and long-task result retrieval.
```
with:
```markdown
- Alexa-signature-verified bridge with replay defense, rate/size limits, private logging, stable
  conversations, and long-task result retrieval.
```
Replace:
```markdown
- Cloudflare Tunnel, AWS SAM, systemd, CI, health checks, and management CLI assets.
```
with:
```markdown
- Tailscale Funnel, systemd, CI, health checks, and management CLI assets.
```

- [ ] **Step 7: Commit** (informational — stage only, per no-commit-unless-asked)

```bash
git add docs/ALEXA.md docs/ARCHITECTURE.md docs/INSTALL.md docs/TROUBLESHOOTING.md \
  docs/SECURITY.md README.md
```

---

### Task 6: Full verification

**Files:** none — this task only runs checks and fixes anything they reveal.

- [ ] **Step 1: Run the full suite**

```bash
uv run ruff check .
uv run pytest
node --test alexa/lambda/index.test.mjs 2>&1 || echo "expected to fail: alexa/lambda was deleted"
bash -n scripts/*.sh
python3 -m py_compile $(git ls-files --others --cached --exclude-standard '*.py')
./cipher help
./cipher alexa package
git diff --check
```

Expected: `ruff check` all-clean; `pytest` all-green (should be roughly 38-40 tests now: the
original suite minus the fully-replaced `test_alexa_bridge.py` tests, plus the new
`test_alexa_signature.py` and rewritten `test_alexa_bridge.py`); the `node --test` line is expected
to fail/error since `alexa/lambda/` no longer exists — that's correct, not a regression, since the
Lambda and its test are deleted by design; `bash -n` clean; `py_compile` clean; `./cipher help`
prints the updated help text (`alexa`/`tunnel` descriptions changed); `./cipher alexa package`
prints "Skill assets ready for manual import" and creates `dist/alexa/`; `git diff --check` clean.

- [ ] **Step 2: Remove the Node test-runner line from CI** (since `alexa/lambda/` is gone)

In `.github/workflows/ci.yml`, remove the line:
```yaml
      - run: node --test alexa/lambda/index.test.mjs
```
and the `actions/setup-node@v7` step above it, since nothing in the repository uses Node anymore
once the Lambda is deleted.

- [ ] **Step 3: Re-run the full suite one more time to confirm nothing regressed**

```bash
uv run ruff check . && uv run pytest && bash -n scripts/*.sh && ./cipher help && ./cipher alexa package && git diff --check && echo ALL GREEN
```
Expected: `ALL GREEN` printed at the end.

- [ ] **Step 4: Commit** (informational — stage only, per no-commit-unless-asked)

```bash
git add -A
```

---

## Self-Review Notes

- **Spec coverage:** Task 1 covers the spec's §1 (signature module); Task 2 covers §3 (settings,
  including the pre-existing `0.0.0.0` bug fix); Task 3 covers §2/§4 (bridge rewrite, security.py
  cleanup); Task 4 covers §5 (removed Lambda/AWS/Cloudflare, CLI/doctor/env updates); Task 5 covers
  §6 (docs); Task 6 covers overall verification. The spec's "Out of scope" section (OpenClaw
  wiring verification, deeper tunnel automation, MCP/HA/Docker/uv changes) has no corresponding
  task, correctly.
- **Placeholder scan:** no TBD/TODO markers; every step has literal code or an exact command.
- **Type consistency:** `BridgeSettings` field names introduced in Task 2 (`id_hmac_secret`,
  `skill_id`, `signature_max_age_seconds`) are used with those exact names in Task 3's `app.py` and
  test fixtures. `AlexaSignatureError`/`verify_alexa_signature` names from Task 1 match their usage
  in Task 3's `app.py` import line and monkeypatch target (`app_module.verify_alexa_signature`).
  `_alexa_response` is defined once (Task 3) and used consistently for every response branch in
  the same task — no other task references it.
