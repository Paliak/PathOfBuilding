#!/usr/bin/env python3
"""Fetch/validate monthly PoB inputs and construct a deterministic, bounded FIFO.

No calculation or source-provider downloads occur while applying a batch.
Publication is the caller's atomic Git commit, never a partial HTTP refresh.
"""
import argparse
import base64
import hashlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from xml.etree import ElementTree

MAX_CODE = 150 * 1024
MAX_XML = 4 * 1024 * 1024
MAX_BATCH = 16 * 1024 * 1024
MAX_CORPUS = 500
HASH = re.compile(r"[a-f0-9]{64}")


def digest(value):
    return hashlib.sha256(value).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def decode_code(code):
    if not isinstance(code, str) or not 0 < len(code) <= MAX_CODE or not re.fullmatch(r"[A-Za-z0-9_+/=-]+", code):
        raise ValueError("invalid encoded build")
    try:
        packed = base64.b64decode(code + "=" * (-len(code) % 4), altchars=b"-_", validate=True)
    except (ValueError, UnicodeError) as exc:
        raise ValueError("invalid base64") from exc
    xml = None
    for window in (zlib.MAX_WBITS, -zlib.MAX_WBITS):
        try:
            stream = zlib.decompressobj(window)
            candidate = stream.decompress(packed, MAX_XML + 1)
            if len(candidate) > MAX_XML or stream.unconsumed_tail:
                raise ValueError("inflated build exceeds limit")
            if not stream.eof or stream.unused_data:
                raise ValueError("incomplete or trailing compressed data")
            xml = candidate
            break
        except zlib.error:
            continue
    if xml is None or re.search(br"<!\s*(DOCTYPE|ENTITY)\b", xml, re.I):
        raise ValueError("invalid or unsafe XML")
    # UTF-8 matches the public feed; do not accept alternate-encoding DTD bypasses.
    try:
        text = xml.decode("utf-8")
        if "\0" in text:
            raise ValueError("non UTF-8 XML representation")
        root = ElementTree.fromstring(text)
    except (UnicodeError, ElementTree.ParseError) as exc:
        raise ValueError("invalid XML") from exc
    if root.tag != "PathOfBuilding" or root.find("Build") is None:
        raise ValueError("not a PoE 1 build")
    return xml


def load_json_bytes(data):
    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result
    return json.loads(data, object_pairs_hook=unique_keys)


def validate_batch(batch):
    if not isinstance(batch, dict) or batch.get("schemaVersion") != 1 or type(batch.get("schemaVersion")) is not int:
        raise ValueError("unsupported batch schema")
    if type(batch.get("requestedCount")) is not int or batch["requestedCount"] != 100:
        raise ValueError("invalid requestedCount")
    if not isinstance(batch.get("batchId"), str) or not batch["batchId"].strip() or len(batch["batchId"]) > 200:
        raise ValueError("invalid batch identity")
    if not isinstance(batch.get("period"), str) or not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", batch["period"]):
        raise ValueError("invalid period")
    if not isinstance(batch.get("patchVersion"), str) or not re.fullmatch(r"\d+\.\d+", batch["patchVersion"]):
        raise ValueError("invalid patch")
    stamp = batch.get("generatedAt", "")
    if not isinstance(stamp, str) or not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z", stamp):
        raise ValueError("invalid generatedAt")
    datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%S.%fZ")
    if stamp[:7] != batch["period"]:
        raise ValueError("period/timestamp mismatch")
    builds = batch.get("builds")
    if not isinstance(builds, list) or type(batch.get("count")) is not int or not 1 <= batch["count"] <= 100 or len(builds) != batch["count"]:
        raise ValueError("invalid batch count")
    hashes = set()
    for entry in builds:
        if not isinstance(entry, dict) or not isinstance(entry.get("sha256"), str) or not HASH.fullmatch(entry["sha256"]):
            raise ValueError("invalid hash representation")
        code = entry.get("code")
        decode_code(code)
        if digest(code.encode("utf-8")) != entry["sha256"] or entry["sha256"] in hashes:
            raise ValueError("hash mismatch or duplicate build")
        hashes.add(entry["sha256"])
    if len(canonical(batch)) > MAX_BATCH:
        raise ValueError("batch exceeds limit")
    return batch


def empty_manifest():
    return {"schemaVersion": 1, "entries": [], "batches": [], "etag": None,
            "corpusDigest": digest(canonical([]))}


def read_corpus(directory, allow_empty=False):
    directory = Path(directory)
    manifest_path = directory / "manifest.json"
    if not manifest_path.exists():
        if allow_empty and not (directory / "codes").exists():
            return empty_manifest(), {}
        raise ValueError("missing corpus manifest")
    if manifest_path.is_symlink() or manifest_path.stat().st_size > MAX_BATCH:
        raise ValueError("invalid manifest file")
    manifest = load_json_bytes(manifest_path.read_bytes())
    if not isinstance(manifest, dict):
        raise ValueError("invalid corpus manifest")
    entries, batches = manifest.get("entries"), manifest.get("batches")
    if manifest.get("schemaVersion") != 1 or not isinstance(entries, list) or not 1 <= len(entries) <= MAX_CORPUS:
        raise ValueError("invalid corpus entries")
    if not isinstance(batches, list) or not 1 <= len(batches) <= 12000:
        raise ValueError("invalid applied batch history")
    identities = set()
    last_period = ""
    for batch in batches:
        if not isinstance(batch, dict) or not isinstance(batch.get("batchId"), str) or not batch["batchId"] or batch["batchId"] in identities or not HASH.fullmatch(batch.get("digest", "")):
            raise ValueError("invalid applied batch")
        period = batch.get("period", "")
        if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", period) or period <= last_period:
            raise ValueError("invalid applied batch order")
        identities.add(batch["batchId"])
        last_period = period
    if manifest.get("etag") is not None and (not isinstance(manifest["etag"], str) or len(manifest["etag"]) > 256 or "\n" in manifest["etag"] or "\r" in manifest["etag"]):
        raise ValueError("invalid ETag")
    codes = {}
    if (directory / "codes").is_symlink():
        raise ValueError("symlink corpus directory")
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("invalid corpus entry")
        key = entry.get("sha256", "")
        if not isinstance(key, str) or not HASH.fullmatch(key) or key in codes or entry.get("batchId") not in identities:
            raise ValueError("invalid corpus identity")
        path = directory / "codes" / (key + ".txt")
        if path.is_symlink() or path.stat().st_size > MAX_CODE:
            raise ValueError("invalid corpus file")
        code = path.read_text(encoding="utf-8")
        if digest(code.encode("utf-8")) != key:
            raise ValueError("corrupt corpus file")
        decode_code(code)
        codes[key] = code
    expected = {key + ".txt" for key in codes}
    if {p.name for p in (directory / "codes").iterdir()} != expected:
        raise ValueError("extra/missing corpus files")
    if manifest.get("corpusDigest") != digest(canonical(entries)):
        raise ValueError("corrupt corpus digest")
    return manifest, codes


def apply_batch(batch, prior, codes, etag=None):
    validate_batch(batch)
    fingerprint = digest(canonical(batch))
    for applied in prior["batches"]:
        if applied["batchId"] == batch["batchId"]:
            if applied["digest"] != fingerprint:
                raise ValueError("accepted batch identity changed contents")
            return prior, codes
    if prior["batches"] and batch["period"] <= prior["batches"][-1]["period"]:
        return prior, codes
    entries = list(prior["entries"])
    next_codes = dict(codes)
    for entry in batch["builds"]:
        key = entry["sha256"]
        if key not in next_codes:
            entries.append({"sha256": key, "batchId": batch["batchId"]})
            next_codes[key] = entry["code"]
    entries = entries[-MAX_CORPUS:]
    next_codes = {entry["sha256"]: next_codes[entry["sha256"]] for entry in entries}
    manifest = {"schemaVersion": 1, "entries": entries, "batches": prior["batches"] + [
        {"batchId": batch["batchId"], "period": batch["period"], "digest": fingerprint}],
        "etag": etag, "corpusDigest": digest(canonical(entries))}
    return manifest, next_codes


class SameHostRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        old, new = urllib.parse.urlsplit(req.full_url), urllib.parse.urlsplit(newurl)
        if new.scheme != "https" or (old.hostname, old.port) != (new.hostname, new.port):
            raise ValueError("unapproved redirect")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_batch(url, etag, has_corpus, opener=None, sleep=time.sleep, clock=time.monotonic):
    target = urllib.parse.urlsplit(url)
    if target.scheme != "https" or target.username or target.password or target.fragment:
        raise ValueError("feed must use HTTPS without credentials")
    opener = opener or urllib.request.build_opener(SameHostRedirect()).open
    deadline = clock() + 240
    for attempt in range(3):
        headers = {"Accept": "application/json", "User-Agent": "PoB-CI-monthly-corpus/1"}
        if etag:
            headers["If-None-Match"] = etag
        status, response_headers = 0, {}
        try:
            with opener(urllib.request.Request(url, headers=headers), timeout=30) as response:
                status = response.status
                response_headers = response.headers
                if status == 200:
                    if response.headers.get_content_type() != "application/json":
                        raise ValueError("unexpected feed content type")
                    data = response.read(MAX_BATCH + 1)
                    if len(data) > MAX_BATCH:
                        raise ValueError("oversized feed")
                    accepted_etag = response.headers.get("ETag")
                    if accepted_etag and (len(accepted_etag) > 256 or "\r" in accepted_etag or "\n" in accepted_etag):
                        raise ValueError("invalid ETag")
                    return validate_batch(load_json_bytes(data)), accepted_etag
        except urllib.error.HTTPError as exc:
            status, response_headers = exc.code, exc.headers
            exc.close()
        except (urllib.error.URLError, TimeoutError):
            status = 0
        if status == 304:
            if has_corpus and etag:
                return None, etag
            if attempt == 0:
                etag = None
                continue
            raise ValueError("unexpected 304 without accepted corpus")
        if status not in (0, 429) and not 500 <= status < 600:
            raise ValueError("feed unavailable or invalid HTTP response: %s" % status)
        delay = 60
        retry = response_headers.get("Retry-After", "")
        if retry.isdigit():
            delay = max(delay, int(retry))
        elif retry:
            try:
                delay = max(delay, (parsedate_to_datetime(retry) - datetime.now(timezone.utc)).total_seconds())
            except (TypeError, ValueError):
                pass
        if attempt == 2 or clock() + delay + 30 > deadline:
            break
        sleep(delay)
    raise ValueError("feed retry budget exhausted")


def write_corpus(directory, manifest, codes):
    directory = Path(directory)
    if directory.exists() and any(directory.iterdir()):
        raise ValueError("output must be a new/empty directory")
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "codes").mkdir()
    for key, code in codes.items():
        (directory / "codes" / (key + ".txt")).write_bytes(code.encode("utf-8"))
    (directory / "manifest.json").write_bytes(canonical(manifest) + b"\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prior", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--batch", type=Path)
    source.add_argument("--url")
    source.add_argument("--materialize", action="store_true")
    args = parser.parse_args()
    prior, codes = read_corpus(args.prior, allow_empty=not args.materialize)
    if args.materialize:
        if args.output.exists():
            raise ValueError("materialization directory must not exist")
        args.output.mkdir(parents=True)
        for entry in prior["entries"]:
            key = entry["sha256"]
            (args.output / (key + ".xml")).write_bytes(decode_code(codes[key]))
        print("Materialized %d verified builds; corpus %s" % (len(codes), prior["corpusDigest"]))
        return
    if args.batch:
        if args.batch.stat().st_size > MAX_BATCH:
            raise ValueError("oversized batch file")
        batch, etag = load_json_bytes(args.batch.read_bytes()), None
    else:
        batch, etag = fetch_batch(args.url, prior["etag"], bool(codes))
    if batch is not None:
        prior, codes = apply_batch(batch, prior, codes, etag)
    write_corpus(args.output, prior, codes)
    print("Retained %d builds across %d accepted monthly batches" % (len(codes), len(prior["batches"])))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError, TypeError) as exc:
        # No raw inputs or URL/HTTP exception bodies in CI logs.
        raise SystemExit("Corpus refresh/materialization failed (%s); prior corpus preserved" % type(exc).__name__)
