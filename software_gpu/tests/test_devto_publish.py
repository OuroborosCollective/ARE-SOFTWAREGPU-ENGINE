"""Real loopback HTTP regression tests for DEV.to publishing (no mocks)."""
import importlib.util
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[2] / "tools/devto_publish.py"
spec = importlib.util.spec_from_file_location("devto_publish", SOURCE)
publisher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publisher)


class DevtoServer(BaseHTTPRequestHandler):
    articles = []
    requests = []
    status_code = 200
    mutation_status_code = 200

    def log_message(self, *args):
        return

    def _send(self, value, code=200):
        encoded = json.dumps(value).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self):
        self.__class__.requests.append(("GET", self.path, None))
        if self.status_code != 200:
            return self._send({"error": "request rejected"}, self.status_code)
        self._send(self.articles if "page=1" in self.path else [])

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length))
        self.__class__.requests.append(("POST", self.path, body))
        if self.mutation_status_code != 200:
            return self._send({"error": "request rejected"}, self.mutation_status_code)
        self._send({"id": 42, "url": "https://dev.to/are/example"}, 201)

    def do_PUT(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length))
        self.__class__.requests.append(("PUT", self.path, body))
        if self.mutation_status_code != 200:
            return self._send({"error": "request rejected"}, self.mutation_status_code)
        self._send({"id": 42, "url": "https://dev.to/are/example"})


class DevtoPublishTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), DevtoServer)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.api = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)

    def setUp(self):
        DevtoServer.articles = []
        DevtoServer.requests = []
        DevtoServer.status_code = 200
        DevtoServer.mutation_status_code = 200
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "docs/devto").mkdir(parents=True)
        self.markdown = self.root / "docs/devto/test-article.md"
        self.markdown.write_text("A detailed renderer investigation. " * 50, encoding="utf-8")
        self.manifest = self.root / "docs/devto/article.json"
        self.data = {
            "title": "A reproducible CPU rendering investigation",
            "description": "Practical evidence on CPU rasterization and reproducible performance experiments.",
            "tags": ["python", "graphics"],
            "markdown_file": "docs/devto/test-article.md"
        }
        self.write_manifest()

    def tearDown(self):
        self.tmp.cleanup()

    def write_manifest(self):
        self.manifest.write_text(json.dumps(self.data), encoding="utf-8")

    def sync(self, publish=False, token="not-a-real-token"):
        return publisher.sync_article(self.manifest, token=token, publish=publish,
                                      repo_root=self.root, api_base=self.api)

    def test_creates_unpublished_draft_with_canonical_source(self):
        result = self.sync()
        self.assertEqual(("created", False), (result["operation"], result["published"]))
        action = DevtoServer.requests[-1]
        self.assertEqual(("POST", "/articles"), action[:2])
        payload = action[2]["article"]
        self.assertFalse(payload["published"])
        self.assertEqual("python,graphics", payload["tags"])
        self.assertEqual(publisher.REPOSITORY_URL + "/blob/main/docs/devto/test-article.md",
                         payload["canonical_url"])

    def test_read_only_auth_probe_makes_no_mutation(self):
        self.assertTrue(publisher.check_auth("valid-test-token", api_base=self.api))
        self.assertEqual([("GET", "/articles/me/all?per_page=1&page=1", None)],
                         DevtoServer.requests)

    def test_auth_probe_rejects_missing_token_without_requests(self):
        with self.assertRaises(publisher.DevtoError):
            publisher.check_auth("", api_base=self.api)
        self.assertEqual([], DevtoServer.requests)

    def test_auth_probe_reports_401_without_leaking_token(self):
        DevtoServer.status_code = 401
        with self.assertRaises(publisher.DevtoError) as err:
            publisher.check_auth("sensitive-example", api_base=self.api)
        self.assertIn("401", str(err.exception))
        self.assertNotIn("sensitive-example", str(err.exception))
        self.assertFalse(any(m in ("POST", "PUT") for m, _, _ in DevtoServer.requests))

    def test_existing_draft_is_updated_without_creating_another(self):
        DevtoServer.articles = [{"id": 42, "published": False,
            "canonical_url": publisher.REPOSITORY_URL + "/blob/main/docs/devto/test-article.md"}]
        self.assertEqual("updated", self.sync()["operation"])
        self.assertEqual(("PUT", "/articles/42"), DevtoServer.requests[-1][:2])

    def test_existing_public_article_is_not_unpublished(self):
        DevtoServer.articles = [{"id": 42, "published": True,
            "canonical_url": publisher.REPOSITORY_URL + "/blob/main/docs/devto/test-article.md"}]
        self.sync()
        self.assertTrue(DevtoServer.requests[-1][2]["article"]["published"])

    def test_documented_published_at_keeps_public_article_published(self):
        DevtoServer.articles = [{"id": 42,
            "published_at": "2026-10-15T17:00:00Z",
            "canonical_url": publisher.REPOSITORY_URL + "/blob/main/docs/devto/test-article.md"}]
        self.sync()
        self.assertTrue(DevtoServer.requests[-1][2]["article"]["published"])

    def test_rfc3339_variants_keep_public_article_published(self):
        for value in ("2026-10-15t17:00:00z", "1990-12-31T23:59:60Z",
                      "2026-10-15T19:00:00.123+02:00"):
            with self.subTest(value=value):
                DevtoServer.articles = [{"id": 42, "published_at": value,
                    "canonical_url": publisher.REPOSITORY_URL + "/blob/main/docs/devto/test-article.md"}]
                DevtoServer.requests = []
                self.sync()
                self.assertTrue(DevtoServer.requests[-1][2]["article"]["published"])

    def test_documented_null_published_at_keeps_unpublished_draft(self):
        DevtoServer.articles = [{"id": 42, "published_at": None,
            "canonical_url": publisher.REPOSITORY_URL + "/blob/main/docs/devto/test-article.md"}]
        self.sync()
        self.assertFalse(DevtoServer.requests[-1][2]["article"]["published"])

    def test_malformed_published_at_does_not_modify_article(self):
        for value in ("not-a-timestamp", "2026-10-15", "2026-10-15T17:00:00",
                      "2026-10-15T17:00:00+00:60"):
            for publish in (False, True):
                with self.subTest(value=value, publish=publish):
                    DevtoServer.articles = [{"id": 42, "published_at": value,
                        "canonical_url": publisher.REPOSITORY_URL + "/blob/main/docs/devto/test-article.md"}]
                    DevtoServer.requests = []
                    with self.assertRaises(publisher.DevtoError):
                        self.sync(publish=publish)
                    self.assertTrue(all(method == "GET" for method, _, _ in DevtoServer.requests))

    def test_unknown_publication_state_does_not_modify_article(self):
        DevtoServer.articles = [{"id": 42,
            "canonical_url": publisher.REPOSITORY_URL + "/blob/main/docs/devto/test-article.md"}]
        with self.assertRaises(publisher.DevtoError):
            self.sync()
        self.assertTrue(all(m == "GET" for m, _, _ in DevtoServer.requests))

    def test_conflicting_publication_state_does_not_modify_article(self):
        DevtoServer.articles = [{"id": 42, "published": False,
            "published_at": "2026-10-15T17:00:00Z",
            "canonical_url": publisher.REPOSITORY_URL + "/blob/main/docs/devto/test-article.md"}]
        with self.assertRaises(publisher.DevtoError):
            self.sync()
        self.assertTrue(all(m == "GET" for m, _, _ in DevtoServer.requests))

    def test_manual_publish_flag_sets_public_state(self):
        self.assertTrue(self.sync(publish=True)["published"])
        self.assertTrue(DevtoServer.requests[-1][2]["article"]["published"])

    def test_no_api_requests_without_token(self):
        with self.assertRaises(publisher.DevtoError):
            self.sync(token="")
        self.assertEqual([], DevtoServer.requests)

    def test_duplicate_canonical_url_is_blocked(self):
        DevtoServer.articles = [
            {"id": n, "published": False,
             "canonical_url": publisher.REPOSITORY_URL + "/blob/main/docs/devto/test-article.md"}
            for n in (42, 43)]
        with self.assertRaises(publisher.DevtoError):
            self.sync()
        self.assertFalse(any(req[0] != "GET" for req in DevtoServer.requests))

    def test_http_error_sanitized_and_token_not_exposed(self):
        DevtoServer.status_code = 403
        with self.assertRaises(publisher.DevtoError) as err:
            self.sync(token="sensitive-example")
        self.assertNotIn("sensitive-example", str(err.exception))
        self.assertIn("403", str(err.exception))

    def test_create_http_error_is_not_silenced_for_draft(self):
        DevtoServer.mutation_status_code = 503
        with self.assertRaises(publisher.DevtoError) as err:
            self.sync(token="sensitive-example")
        self.assertIn("503", str(err.exception))
        self.assertNotIn("sensitive-example", str(err.exception))
        self.assertEqual("POST", DevtoServer.requests[-1][0])

    def test_update_http_error_is_not_silenced_for_draft(self):
        DevtoServer.articles = [{"id": 42, "published": False,
            "canonical_url": publisher.REPOSITORY_URL + "/blob/main/docs/devto/test-article.md"}]
        DevtoServer.mutation_status_code = 429
        with self.assertRaises(publisher.DevtoError) as err:
            self.sync(token="sensitive-example")
        self.assertIn("429", str(err.exception))
        self.assertNotIn("sensitive-example", str(err.exception))
        self.assertEqual("PUT", DevtoServer.requests[-1][0])

    def test_frontmatter_rejected(self):
        self.markdown.write_text("---\npublished: true\n---\n" + "hello " * 250)
        with self.assertRaises(publisher.DevtoError):
            publisher.load_article(self.manifest, self.root)

    def test_invalid_markdown_path_rejected(self):
        self.data["markdown_file"] = "../../secrets.md"
        self.write_manifest()
        with self.assertRaises(publisher.DevtoError):
            publisher.load_article(self.manifest, self.root)


if __name__ == "__main__":
    unittest.main()
