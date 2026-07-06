"""HTTP fetch abstraction: prefers ``requests`` when installed, falls back to
the standard library's ``urllib.request`` otherwise.

This lets the crawler run on a bare Python install with no third-party
packages -- useful in locked-down environments where installing packages
from PyPI needs approval. Behavior (headers, timeout, raising on non-2xx)
is kept equivalent across both backends; callers (``crawl.py``) don't need
to know which one is active.
"""

from __future__ import annotations

import urllib.error
import urllib.request
from dataclasses import dataclass

try:
    import requests

    HAVE_REQUESTS = True
except ImportError:
    requests = None  # type: ignore[assignment]
    HAVE_REQUESTS = False


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
            with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed http(s) scheme, scoped by caller
                charset = response.headers.get_content_charset() or "utf-8"
                body = response.read().decode(charset, errors="replace")
                return FetchResult(text=body, status_code=response.status)
        except urllib.error.HTTPError as exc:
            raise HttpError(f"HTTP {exc.code} for {url}") from exc
        except urllib.error.URLError as exc:
            raise HttpError(f"Failed to reach {url}: {exc.reason}") from exc
