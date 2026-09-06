import base64
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
import zlib
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "spec"))
from FetchTestBuilds import decode_batch, write_inputs, MAX_XML


def batch_for(xml):
    code = base64.urlsafe_b64encode(zlib.compress(xml)).decode("ascii")
    return {"schemaVersion": 1, "batchId": "fixture", "period": "2026-09",
            "generatedAt": "2026-09-01T00:00:00.000Z", "patchVersion": "3.25",
            "requestedCount": 100, "count": 1,
            "builds": [{"code": code, "sha256": hashlib.sha256(code.encode()).hexdigest()}]}


class FeedTests(unittest.TestCase):
    def setUp(self):
        self.xml = (ROOT / "spec/TestBuilds/OccVortex.xml").read_bytes()
        self.batch = batch_for(self.xml)

    def test_existing_fixture_survives_the_wire_format_exactly(self):
        self.assertEqual(list(decode_batch(json.dumps(self.batch)).values()), [self.xml])

    def test_invalid_batches_do_not_create_output(self):
        bad_hash = batch_for(self.xml)
        bad_hash["builds"][0]["sha256"] = "0" * 64
        duplicate = batch_for(self.xml)
        duplicate["builds"] *= 2
        duplicate["count"] = 2
        for batch in (bad_hash, duplicate, {**self.batch, "count": 0},
                      {**self.batch, "schemaVersion": 2}, batch_for(b"not XML"),
                      batch_for(b'<!DOCTYPE x><PathOfBuilding><Build/></PathOfBuilding>'),
                      batch_for(b"x" * (MAX_XML + 1))):
            with self.subTest(batch=batch.get("schemaVersion")), tempfile.TemporaryDirectory() as tmp:
                output = Path(tmp) / "inputs"
                with self.assertRaises((ValueError, ElementTree.ParseError)):
                    write_inputs(json.dumps(batch), output)
                self.assertFalse(output.exists())

    def test_existing_inputs_are_never_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "inputs"
            self.assertEqual(write_inputs(json.dumps(self.batch), output), 1)
            before = {p.name: p.read_bytes() for p in output.iterdir()}
            with self.assertRaises(ValueError):
                write_inputs(json.dumps(self.batch), output)
            self.assertEqual({p.name: p.read_bytes() for p in output.iterdir()}, before)

    @unittest.skipUnless(os.environ.get("POB_FEED_DOCKER_TEST") == "1", "opt-in existing Docker generator proof")
    def test_existing_generator_and_comparator(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            write_inputs(json.dumps(self.batch), tmp / "inputs")
            for name in ("first", "second", "bad-output"):
                (tmp / name).mkdir()
            command = ["docker", "run", "--rm", "--network", "none",
                       "--mount", "type=bind,source=%s,target=/workdir,readonly" % ROOT,
                       "--mount", "type=bind,source=%s,target=/proof" % tmp,
                       "-w", "/workdir", "-e", "HOME=/tmp"]

            def docker(arguments, environment=()):
                return subprocess.run(command + list(environment) +
                    ["ghcr.io/paliak/busted-tests:latest"] + arguments, timeout=330,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

            def generate(inputs, output):
                return docker(["timeout", "300", "busted", "--lua=luajit", "-r", "generate"],
                    ["-e", "BUILDINPUTDIR=/proof/" + inputs, "-e", "BUILDCACHEPREFIX=/proof/" + output])

            for output in ("first", "second"):
                result = generate("inputs", output)
                self.assertEqual(result.returncode, 0, result.stdout)
                self.assertEqual(len(list((tmp / output).glob("*.build"))), 1)
            name = next((tmp / "first").glob("*.build")).name
            args = ["luajit", "spec/DiffOutput.lua", "/proof/first/" + name, "/proof/second/" + name]
            self.assertEqual(docker(args).returncode, 0)
            saved = (tmp / "second" / name).read_text()
            changed, count = re.subn(r'(<PlayerStat stat="[^"]+" value=")[^"]+', r'\g<1>123456789', saved, count=1)
            self.assertEqual(count, 1, "generator must save calculated stats")
            (tmp / "second" / name).write_text(changed)
            self.assertEqual(docker(args).returncode, 1, "existing comparator must detect changed stats")
            bad = re.sub(br'targetVersion="[^"]+"', b'targetVersion="unsupported"', self.xml, count=1)
            write_inputs(json.dumps(batch_for(bad)), tmp / "bad-input")
            result = generate("bad-input", "bad-output")
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertFalse(list((tmp / "bad-output").glob("*.build")))


if __name__ == "__main__":
    unittest.main()
