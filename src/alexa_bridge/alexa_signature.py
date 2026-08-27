from __future__ import annotations

import base64
import binascii
import datetime as dt
from collections.abc import Callable, Mapping
from dataclasses import dataclass
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
    # Verify each certificate is directly issued by the next one up the chain.
    # Real-world CAs commonly serve a chain whose last certificate is itself a
    # cross-sign issued by an unrelated CA (e.g. Amazon's echo-api chain ends
    # in "Amazon Root CA 1", which is issued by Starfield's root, not
    # self-signed) rather than a literal self-signed root, so the top-most
    # served certificate is not required to be self-signed here.
    for cert, issuer in zip(certs, certs[1:], strict=False):
        try:
            cert.verify_directly_issued_by(issuer)
        except (InvalidSignature, ValueError, TypeError) as exc:
            raise AlexaSignatureError("certificate chain signature is invalid") from exc
    return leaf


def _leaf_public_key(url: str, now: dt.datetime, http_get: Callable[[str], bytes]):
    cached = _cert_cache.get(url)
    if cached and cached.expires_at > now:
        return cached.public_key
    try:
        certs = x509.load_pem_x509_certificates(http_get(url))
    except httpx.HTTPError as exc:
        raise AlexaSignatureError("could not fetch certificate chain") from exc
    except ValueError as exc:
        raise AlexaSignatureError("malformed certificate chain") from exc
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
