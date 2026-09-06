#!/usr/bin/env python3
"""Offline comparison of one verified corpus on two explicit Git revisions."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
from pathlib import Path
import subprocess
import tarfile
import tempfile
import time
from xml.etree import ElementTree

from UpdateBuildCorpus import read_corpus, decode_code


def run(command, **kwargs):
    return subprocess.run(command, check=True, **kwargs)


def revision(repo, ref):
    return subprocess.check_output(["git", "-C", str(repo), "rev-parse", "--verify", ref + "^{commit}"], text=True).strip()


def checkout_runtime(repo, sha, destination):
    destination.mkdir()
    with tempfile.TemporaryFile() as archive:
        run(["git", "-C", str(repo), "archive", sha, "src", "runtime"], stdout=archive)
        archive.seek(0)
        with tarfile.open(fileobj=archive) as contents:
            contents.extractall(destination, filter="data")
    if not (destination / "src" / "HeadlessWrapper.lua").is_file():
        raise ValueError("runtime lacks HeadlessWrapper.lua")


def saved_stats(path):
    if not path.is_file() or path.is_symlink() or path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError("missing/oversized output")
    data = path.read_bytes()
    if b"<!DOCTYPE" in data or b"<!ENTITY" in data:
        raise ValueError("unsafe output XML")
    root = ElementTree.fromstring(data)
    player = root.findall("./Build/PlayerStat")
    if root.tag != "PathOfBuilding" or not player:
        raise ValueError("missing calculated player stats")
    return {(kind, stat.attrib["stat"]): stat.attrib["value"]
            for kind in ("PlayerStat", "MinionStat") for stat in root.findall("./Build/" + kind)}


def validate_outputs(directory, expected):
    found = {p.name for p in directory.iterdir()}
    if found != {name + ".build" for name in expected}:
        raise ValueError("expected/completed build set differs")
    for name in expected:
        saved_stats(directory / (name + ".build"))


def docker_mount(path, target, readonly=True):
    return ["--mount", "type=bind,source=%s,target=%s%s" % (path, target, ",readonly" if readonly else "")]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--corpus", type=Path)
    parser.add_argument("--fixtures-only", action="store_true")
    parser.add_argument("--extra-fixtures", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--parallel", type=int, default=2, choices=(1, 2))
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--image", help="Already-built image, primarily for offline reproduction")
    args = parser.parse_args()
    if bool(args.corpus) == args.fixtures_only:
        parser.error("choose --corpus or explicit --fixtures-only")
    repo = args.repo.resolve()
    harness = Path(__file__).resolve().parent
    base, head = revision(repo, args.base), revision(repo, args.head)
    output = args.output.resolve()
    if output.exists():
        parser.error("output must not already exist")
    output.mkdir(parents=True)
    started = time.monotonic()
    image = args.image
    if not image:
        dockerfile = harness.parent / "Dockerfile.test-builds"
        image = "pob-ci:" + hashlib.sha256(dockerfile.read_bytes()).hexdigest()[:16]
        run(["docker", "build", "-t", image, "-f", str(dockerfile), str(harness.parent)], timeout=600)
    image_id = subprocess.check_output(["docker", "image", "inspect", "--format", "{{.Id}}", image], text=True).strip()
    print("Runtime base=%s head=%s image=%s" % (base, head, image_id), flush=True)
    with tempfile.TemporaryDirectory(prefix="pob-corpus-") as scratch:
        scratch = Path(scratch)
        inputs = scratch / "inputs"
        inputs.mkdir()
        if args.corpus:
            manifest, codes = read_corpus(args.corpus)
            print("Corpus %s; rotating builds=%d" % (manifest["corpusDigest"], len(codes)), flush=True)
            for key, code in codes.items():
                (inputs / (key + ".xml")).write_bytes(decode_code(code))
        # Copy the harness's fixed fixtures identically to both runtime revisions.
        for folder in (harness / "TestBuilds", args.extra_fixtures):
            if folder is None:
                continue
            for source in sorted(folder.glob("*.xml")):
                if source.is_symlink() or source.stat().st_size > 4 * 1024 * 1024:
                    raise ValueError("invalid fixed fixture")
                xml = source.read_bytes()
                name = "fixture-" + hashlib.sha256(xml).hexdigest() + ".xml"
                (inputs / name).write_bytes(xml)
        names = sorted(p.name for p in inputs.iterdir())
        if not names:
            raise ValueError("empty input set")
        lists = scratch / "lists"
        lists.mkdir()
        jobs = []
        for label, sha in (("base", base), ("head", head)):
            source = scratch / label
            checkout_runtime(repo, sha, source)
            destination = output / label
            destination.mkdir()
            for index in range(0, len(names), 25):
                batch = lists / ("batch-%d.txt" % index)
                batch.write_bytes(("\n".join(names[index:index+25]) + "\n").encode("utf-8"))
                jobs.append((source, destination, batch.name))

        def calculate(job):
            source, destination, batch = job
            # The OS deadline bounds the whole batch; Lua's alarm bounds an input.
            command = ["docker", "run", "--rm", "--network", "none", "--cpus", "2", "--memory", "2g",
                       "--security-opt", "no-new-privileges", "--cap-drop", "ALL"]
            command += docker_mount(source, "/workdir") + docker_mount(harness, "/harness")
            command += docker_mount(inputs, "/inputs") + docker_mount(lists, "/lists") + docker_mount(destination, "/outputs", False)
            command += ["-w", "/workdir/src", "-e", "CI=true", image_id, "timeout", "300", "luajit", "/harness/RunBuildBatch.lua", "/lists/" + batch]
            run(command, timeout=330)

        with ThreadPoolExecutor(max_workers=args.parallel) as pool:
            list(pool.map(calculate, jobs))
        validate_outputs(output / "base", names)
        validate_outputs(output / "head", names)
        command = ["docker", "run", "--rm", "--network", "none", "--security-opt", "no-new-privileges", "--cap-drop", "ALL"]
        command += docker_mount(harness, "/harness") + docker_mount(output, "/outputs")
        command += ["-e", "STRICT_DIFF=" + ("1" if args.strict else "0"), image_id, "sh", "/harness/CompareBuilds.sh"]
        run(command, timeout=300)
    print("Completed %d identical input pairs in %.1fs" % (len(names), time.monotonic()-started), flush=True)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError, ElementTree.ParseError, subprocess.SubprocessError) as exc:
        raise SystemExit("Build comparison failed (%s)" % type(exc).__name__)
