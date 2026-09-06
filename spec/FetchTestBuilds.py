#!/usr/bin/env python3
"""Decode one PoB Codes batch for the existing GenerateBuilds.lua input path."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import re
import tempfile
import urllib.request
import zlib
from xml.etree import ElementTree

FEED = "https://api.pob.codes/test-builds"
MAX_BATCH, MAX_CODE, MAX_XML = 16 * 1024 * 1024, 150 * 1024, 4 * 1024 * 1024


def decode_batch(data):
    if len(data) > MAX_BATCH:
        raise ValueError("batch too large")
    batch = json.loads(data)
    if batch.get("schemaVersion") != 1 or batch.get("requestedCount") != 100:
        raise ValueError("unsupported feed schema")
    builds = batch.get("builds")
    if not isinstance(builds, list) or not 1 <= len(builds) <= 100 or batch.get("count") != len(builds):
        raise ValueError("invalid build count")
    decoded = {}
    for entry in builds:
        code, key = entry["code"], entry["sha256"]
        if not isinstance(code, str) or not 0 < len(code) <= MAX_CODE or not re.fullmatch(r"[A-Za-z0-9_+/=-]+", code):
            raise ValueError("invalid build code")
        if hashlib.sha256(code.encode("ascii")).hexdigest() != key or key + ".xml" in decoded:
            raise ValueError("hash mismatch or duplicate build")
        packed = base64.b64decode(code + "=" * (-len(code) % 4), altchars=b"-_", validate=True)
        xml = None
        for window in (zlib.MAX_WBITS, -zlib.MAX_WBITS):
            try:
                stream = zlib.decompressobj(window)
                xml = stream.decompress(packed, MAX_XML + 1)
            except zlib.error:
                continue
            if len(xml) > MAX_XML or stream.unconsumed_tail or not stream.eof or stream.unused_data:
                raise ValueError("oversized, incomplete, or trailing compressed data")
            break
        if xml is None:
            raise ValueError("invalid compressed build")
        text = xml.decode("utf-8")
        if "\0" in text or re.search(r"<!\s*(DOCTYPE|ENTITY)\b", text, re.I):
            raise ValueError("unsupported XML declaration")
        root = ElementTree.fromstring(text)
        if root.tag != "PathOfBuilding" or root.find("Build") is None:
            raise ValueError("not a PoE 1 build")
        decoded[key + ".xml"] = xml
    return decoded


def write_inputs(data, output):
    decoded = decode_batch(data)  # Validate the entire batch before writing anything.
    output = Path(output).resolve()
    if output.exists():
        raise ValueError("output must be a new directory")
    with tempfile.TemporaryDirectory(dir=output.parent) as temporary:
        staged = Path(temporary) / "inputs"
        staged.mkdir()
        for name, xml in decoded.items():
            (staged / name).write_bytes(xml)
        staged.rename(output)
    return len(decoded)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", type=Path, help="Saved JSON batch; otherwise fetch the public API once")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.batch:
        with args.batch.open("rb") as source:
            data = source.read(MAX_BATCH + 1)
    else:
        request = urllib.request.Request(FEED, headers={"Accept": "application/json", "User-Agent": "PoB-feed-proof/1"})
        with urllib.request.urlopen(request, timeout=30) as response:
            if response.status != 200 or response.headers.get_content_type() != "application/json":
                raise ValueError("unexpected API response")
            data = response.read(MAX_BATCH + 1)
    print("Validated and decoded %d feed builds" % write_inputs(data, args.output))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        raise SystemExit("Feed download/decoding failed (%s); use a new output directory and retry when ready" % type(error).__name__)
