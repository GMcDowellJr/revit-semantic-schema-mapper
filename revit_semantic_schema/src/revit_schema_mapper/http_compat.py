"""HTTP fetch abstraction: prefers ``requests`` when installed, falls back to
the standard library's ``urllib.request`` otherwise.

This lets the crawler run on a bare Python install with no third-party
packages -- useful in locked-down environments where installing packages
from PyPI needs approval. Behavior (headers, timeout, raising on non-2xx)
is kept equivalent across both backends; callers (``crawl.py``) don't need
to know which one is active.

GZIP: unlike ``requests`` (via urllib3) and real browsers, plain
``urllib.request`` does not transparently decompress a
``Content-Encoding: gzip``/``deflate`` response -- some CDN-hosted static
assets (e.g. a prebuilt, precompressed ``*_min.json``) are served this way
regardless of the client's ``Accept-Encoding``. Decoding those raw
compressed bytes as UTF-8 doesn't raise cleanly; it silently produces
mostly-garbage text (the gzip magic byte ``0x8b`` isn't valid UTF-8 and
becomes a replacement character), which then fails downstream with a
confusing error -- e.g. ``json.loads`` raising
``JSONDecodeError('Expecting value: line 1 column 1 (char 0)')``, which
looks like "the response was empty" but actually means "the response was
compressed and never decompressed." The urllib fallback path below checks
``Content-Encoding`` explicitly and decompresses before decoding as text.

TLS ON CORPORATE NETWORKS: environments with SSL-inspecting proxies
(Zscaler, Netskope, Palo Alto, etc.) re-sign HTTPS traffic with an internal
root CA. Windows/browsers often trust that CA fine, but OpenSSL 3.2+ (used
by Python's ``ssl`` module) added a stricter X.509 chain-building check
that some corporate root CAs fail -- typically surfacing as
``CERTIFICATE_VERIFY_FAILED: ... Missing Authority Key Identifier``. That
is a certificate-hygiene problem on the intercepting proxy's CA, not a bug
in this code or in the target site. The correct fix is for your IT/security
team to reissue that root CA properly or to exempt the target domain from
inspection. As a stopgap, setting the environment variable
``REVIT_SCHEMA_MAPPER_RELAX_TLS_STRICT=1`` turns off *only* that newer
strict-compliance check (``ssl.VERIFY_X509_STRICT``) on the fallback
urllib path -- full certificate chain-of-trust and hostname verification
stay on. It is opt-in and off by default; don't set it unless you've hit
exactly this error and understand it's a workaround, not a fix.
"""

from __future__ import annotations

import gzip
import json as json_module
import os
import ssl
import urllib.error
import urllib.request
import zlib
from dataclasses import dataclass

try:
    import requests

    HAVE_REQUESTS = True
except ImportError:
    requests = None  # type: ignore[assignment]
    HAVE_REQUESTS = False

RELAX_TLS_STRICT = os.environ.get("REVIT_SCHEMA_MAPPER_RELAX_TLS_STRICT") == "1"


def _make_ssl_context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    if RELAX_TLS_STRICT and hasattr(ssl, "VERIFY_X509_STRICT"):
        context.verify_flags &= ~ssl.VERIFY_X509_STRICT
    return context


@dataclass
class FetchResult:
    text: str
    status_code: int


class HttpError(Exception):
    """Raised on a non-2xx response or transport failure, from either backend."""


class HttpClient:
    """Minimal session-like object: fixed headers, one GET method.

    Uses ``requests.Session`` when available, otherwise a plain
    ``urllib.request`` call with the same headers/timeout passed through.
    """

    def __init__(self, headers: dict[str, str]):
        self._headers = headers
        self._session = requests.Session() if HAVE_REQUESTS else None
        if self._session is not None:
            self._session.headers.update(headers)

    def get(self, url: str, timeout: float) -> FetchResult:
        if self._session is not None:
            try:
                response = self._session.get(url, timeout=timeout)
                response.raise_for_status()
            except requests.RequestException as exc:  # noqa: BLE001 - normalize to HttpError
                raise HttpError(str(exc)) from exc
            return FetchResult(text=response.text, status_code=response.status_code)

        request = urllib.request.Request(url, headers=self._headers)
        try:
            with urllib.request.urlopen(request, timeout=timeout, context=_make_ssl_context()) as response:  # noqa: S310 - fixed http(s) scheme, scoped by caller
                raw = response.read()
                raw = _decompress(raw, response.headers.get("Content-Encoding", ""))
                charset = response.headers.get_content_charset() or "utf-8"
                body = raw.decode(charset, errors="replace")
                return FetchResult(text=body, status_code=response.status)
        except urllib.error.HTTPError as exc:
            raise HttpError(f"HTTP {exc.code} for {url}") from exc
        except urllib.error.URLError as exc:
            raise HttpError(f"Failed to reach {url}: {exc.reason}") from exc

    def post_json(self, url: str, *, headers: dict[str, str], json_body: dict, timeout: float) -> FetchResult:
        """POST a JSON body with extra headers merged on top of this
        client's fixed headers -- used by ``community.py``'s optional
        OpenRouter labeling call. Same requests/urllib fallback as ``get``.
        """
        merged_headers = {**self._headers, **headers, "Content-Type": "application/json"}

        if self._session is not None:
            try:
                response = self._session.post(url, json=json_body, headers=merged_headers, timeout=timeout)
                response.raise_for_status()
            except requests.RequestException as exc:  # noqa: BLE001 - normalize to HttpError
                raise HttpError(str(exc)) from exc
            return FetchResult(text=response.text, status_code=response.status_code)

        data = json_module.dumps(json_body).encode("utf-8")
        request = urllib.request.Request(url, data=data, headers=merged_headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout, context=_make_ssl_context()) as response:  # noqa: S310 - fixed http(s) scheme, scoped by caller
                raw = response.read()
                raw = _decompress(raw, response.headers.get("Content-Encoding", ""))
                charset = response.headers.get_content_charset() or "utf-8"
                body = raw.decode(charset, errors="replace")
                return FetchResult(text=body, status_code=response.status)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
            raise HttpError(f"HTTP {exc.code} for {url}: {detail[:300]}") from exc
        except urllib.error.URLError as exc:
            raise HttpError(f"Failed to reach {url}: {exc.reason}") from exc


def _decompress(raw: bytes, content_encoding: str) -> bytes:
    encoding = content_encoding.strip().lower()
    if encoding == "gzip":
        return gzip.decompress(raw)
    if encoding == "deflate":
        try:
            return zlib.decompress(raw)
        except zlib.error:
            # Some servers send a raw deflate stream without the zlib
            # header/checksum; -15 (negative window bits) tells zlib to
            # skip expecting that wrapper.
            return zlib.decompress(raw, -zlib.MAX_WBITS)
    return raw
