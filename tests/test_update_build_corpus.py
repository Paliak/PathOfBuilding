import base64
from copy import deepcopy
from email.message import Message
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import urllib.error
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "spec"))
import UpdateBuildCorpus as corpus


def entry(number):
    xml = '<PathOfBuilding><Build level="90"/><Notes>%d</Notes></PathOfBuilding>' % number
    code = base64.urlsafe_b64encode(zlib.compress(xml.encode())).decode().rstrip("=")
    return {"code": code, "sha256": corpus.digest(code.encode())}


def batch(month=1, start=0, count=100):
    return {"schemaVersion": 1, "batchId": "batch-%d" % month, "period": "2026-%02d" % month,
            "generatedAt": "2026-%02d-01T00:00:00.000Z" % month, "patchVersion": "3.29",
            "requestedCount": 100, "count": count, "builds": [entry(i) for i in range(start, start + count)]}


class CorpusTests(unittest.TestCase):
    def test_shared_provider_wire_fixture(self):
        fixture = Path(__file__).parent / "fixtures" / "test-build-batch-v1.json"
        self.assertEqual(corpus.validate_batch(corpus.load_json_bytes(fixture.read_bytes()))["count"], 2)

    def test_fifo_500_repeats_duplicates_stale_and_conflicting_batches(self):
        manifest, codes = corpus.empty_manifest(), {}
        for month in range(1, 7):
            manifest, codes = corpus.apply_batch(batch(month, (month-1)*100), manifest, codes)
        self.assertEqual(len(codes), 500)
        self.assertEqual(manifest["entries"][0]["sha256"], entry(100)["sha256"])
        same = corpus.apply_batch(batch(6, 500), manifest, codes)
        self.assertEqual(same, (manifest, codes))
        duplicate, duplicate_codes = corpus.apply_batch(batch(7, 500), manifest, codes)
        self.assertEqual(duplicate["entries"], manifest["entries"])
        self.assertEqual(len(duplicate["batches"]), 7)
        self.assertEqual(duplicate_codes, codes)
        self.assertEqual(corpus.apply_batch(batch(1, 0), manifest, codes), (manifest, codes))
        changed = batch(6, 700)
        with self.assertRaises(ValueError):
            corpus.apply_batch(changed, manifest, codes)

    def test_shortfall_and_disk_roundtrip_detect_corruption(self):
        m, c = corpus.apply_batch(batch(count=2), corpus.empty_manifest(), {}, '"accepted"')
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "corpus"
            corpus.write_corpus(path, m, c)
            self.assertEqual(corpus.read_corpus(path), (m, c))
            with self.assertRaises(ValueError):
                corpus.write_corpus(path, m, c)
            next((path / "codes").iterdir()).write_text("corrupt")
            with self.assertRaises(ValueError):
                corpus.read_corpus(path)

    def test_rejects_malformed_envelopes_before_mutating_prior(self):
        valid = batch(count=1)
        variants = []
        for field, value in (("schemaVersion", True), ("count", 0), ("count", True),
                             ("count", 101), ("period", "2026-99"), ("generatedAt", "2026-02-30T00:00:00.000Z"),
                             ("batchId", ""), ("patchVersion", None)):
            broken = deepcopy(valid); broken[field] = value; variants.append(broken)
        broken = deepcopy(valid); broken["builds"][0]["sha256"] = broken["builds"][0]["sha256"].upper(); variants.append(broken)
        broken = deepcopy(valid); broken["builds"][0]["code"] += " "; variants.append(broken)
        broken = deepcopy(valid); broken["builds"] *= 2; broken["count"] = 2; variants.append(broken)
        for broken in variants:
            with self.subTest(broken=broken.keys()), self.assertRaises(ValueError):
                corpus.validate_batch(broken)

    def test_rejects_bombs_trailing_data_and_doctype(self):
        for data in (b"x" * (corpus.MAX_XML+1), b'<!DOCTYPE x [<!ENTITY e "x">]><PathOfBuilding><Build/></PathOfBuilding>',
                     '<PathOfBuilding><Build/></PathOfBuilding>'.encode("utf-16-le")):
            code = base64.urlsafe_b64encode(zlib.compress(data)).decode()
            with self.assertRaises(ValueError):
                corpus.decode_code(code)
        packed = base64.urlsafe_b64decode(entry(0)["code"] + "=" * (-len(entry(0)["code"]) % 4)) + b"trailing"
        with self.assertRaises(ValueError):
            corpus.decode_code(base64.urlsafe_b64encode(packed).decode())

    def test_fetch_retries_preserves_etag_and_stops_on_invalid_status(self):
        headers = Message(); headers["Content-Type"] = "application/json"; headers["ETag"] = '"new"'
        delays, calls = [], []
        class Response(io.BytesIO):
            status = 200
        def opener(request, timeout):
            calls.append(request)
            if len(calls) == 1:
                retry = Message(); retry["Retry-After"] = "65"
                raise urllib.error.HTTPError(request.full_url, 429, "rate limit", retry, io.BytesIO())
            response = Response(json.dumps(batch(count=1)).encode()); response.headers = headers
            return response
        accepted, etag = corpus.fetch_batch("https://api.pob.codes/test-builds", '"old"', True, opener=opener, sleep=delays.append, clock=lambda: 0)
        self.assertEqual(delays, [65]); self.assertEqual(etag, '"new"'); self.assertEqual(accepted["count"], 1)
        self.assertEqual(calls[1].get_header("If-none-match"), '"old"')
        for status in (400, 404):
            def unavailable(request, timeout):
                raise urllib.error.HTTPError(request.full_url, status, "unavailable", Message(), io.BytesIO())
            with self.assertRaises(ValueError):
                corpus.fetch_batch("https://api.pob.codes/test-builds", None, False, opener=unavailable)

    def test_304_requires_valid_prior_and_retries_without_etag_once(self):
        calls = []
        def opener(request, timeout):
            calls.append(request)
            raise urllib.error.HTTPError(request.full_url, 304, "not modified", Message(), io.BytesIO())
        self.assertEqual(corpus.fetch_batch("https://api.pob.codes/test-builds", '"ok"', True, opener=opener), (None, '"ok"'))
        with self.assertRaises(ValueError):
            corpus.fetch_batch("https://api.pob.codes/test-builds", '"bad"', False, opener=opener)
        self.assertIsNone(calls[-1].get_header("If-none-match"))

    def test_invalid_cli_refresh_leaves_prior_bytes_unchanged(self):
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp); prior = temp / "prior"
            manifest, codes = corpus.apply_batch(batch(count=1), corpus.empty_manifest(), {})
            corpus.write_corpus(prior, manifest, codes)
            original = (prior / "manifest.json").read_bytes()
            (temp / "bad.json").write_text("{}")
            result = subprocess.run([sys.executable, str(Path(corpus.__file__)), "--prior", str(prior), "--batch", str(temp / "bad.json"), "--output", str(temp / "next")], capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual((prior / "manifest.json").read_bytes(), original)
            self.assertFalse((temp / "next").exists())


if __name__ == "__main__":
    unittest.main()
