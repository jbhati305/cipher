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


def _build_chain(
    *, san: str = "echo-api.amazon.com", now: dt.datetime = NOW
) -> tuple[object, bytes]:
    root_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    root_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Test Root CA")])
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


def test_malformed_certificate_chain_is_rejected():
    leaf_key, _chain_pem = _build_chain()
    headers = _headers(BODY, leaf_key)
    with pytest.raises(AlexaSignatureError):
        verify_alexa_signature(
            BODY, headers, TIMESTAMP, 150, now=NOW, http_get=lambda url: b"not a certificate"
        )
