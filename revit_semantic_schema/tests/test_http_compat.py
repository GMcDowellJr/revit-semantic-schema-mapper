import gzip
import json
import threading
import zlib
from http.server import BaseHTTPRequestHandler, HTTPServer

from revit_schema_mapper.http_compat import HttpClient

_PAYLOAD = {"hello": "world", "namespace": "Autodesk.Revit.DB"}


def _make_handler(content_encoding: str | None, use_raw_deflate: bool = False):
    body = json.dumps(_PAYLOAD).encode("utf-8")
    if content_encoding == "gzip":
        wire_body = gzip.compress(body)
    elif content_encoding == "deflate":
        if use_raw_deflate:
            compressor = zlib.compressobj(wbits=-zlib.MAX_WBITS)
            wire_body = compressor.compress(body) + compressor.flush()
        else:
            wire_body = zlib.compress(body)
    else:
        wire_body = body

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            if content_encoding:
                self.send_header("Content-Encoding", content_encoding)
            self.send_header("Content-Length", str(len(wire_body)))
            self.end_headers()
            self.wfile.write(wire_body)

        def log_message(self, format, *args):  # noqa: A002 - stdlib signature
            pass

    return Handler


def _fetch_via(handler_cls) -> str:
    server = HTTPServer(("127.0.0.1", 0), handler_cls)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        client = HttpClient({"User-Agent": "test"})
        result = client.get(f"http://127.0.0.1:{port}/", timeout=5)
        return result.text
    finally:
        server.shutdown()
        thread.join()


def test_uncompressed_response_is_unaffected():
    text = _fetch_via(_make_handler(None))
    assert json.loads(text) == _PAYLOAD


def test_gzip_response_is_decompressed():
    text = _fetch_via(_make_handler("gzip"))
    assert json.loads(text) == _PAYLOAD


def test_zlib_wrapped_deflate_response_is_decompressed():
    text = _fetch_via(_make_handler("deflate", use_raw_deflate=False))
    assert json.loads(text) == _PAYLOAD


def test_raw_deflate_response_is_decompressed():
    text = _fetch_via(_make_handler("deflate", use_raw_deflate=True))
    assert json.loads(text) == _PAYLOAD


def _make_post_handler(captured: dict):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            captured["body"] = json.loads(self.rfile.read(length))
            captured["headers"] = dict(self.headers)
            response = json.dumps({"echo": captured["body"]}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)

        def log_message(self, format, *args):  # noqa: A002 - stdlib signature
            pass

    return Handler


def test_post_json_sends_body_and_merged_headers_and_returns_response():
    captured: dict = {}
    server = HTTPServer(("127.0.0.1", 0), _make_post_handler(captured))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        client = HttpClient({"User-Agent": "test"})
        result = client.post_json(
            f"http://127.0.0.1:{port}/",
            headers={"Authorization": "Bearer secret"},
            json_body={"model": "test-model", "messages": [{"role": "user", "content": "hi"}]},
            timeout=5,
        )
        assert json.loads(result.text) == {"echo": {"model": "test-model", "messages": [{"role": "user", "content": "hi"}]}}
        assert captured["body"] == {"model": "test-model", "messages": [{"role": "user", "content": "hi"}]}
        assert captured["headers"]["Authorization"] == "Bearer secret"
        assert captured["headers"]["User-Agent"] == "test"
    finally:
        server.shutdown()
        thread.join()
