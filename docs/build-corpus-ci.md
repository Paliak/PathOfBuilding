# Build corpus CI

PoB Codes publishes up to 100 monthly builds at
`https://api.pob.codes/test-builds`. This repository retains up to 500 unique
encoded builds in a FIFO on `build-test-corpus`. Comparisons load one saved
corpus and calculate every input on both Git revisions, alongside every XML
fixture under `spec/TestBuilds`, including versioned subdirectories.

The API supplies inputs. This repository owns retention and calculations.
There is no migration of old build lists or saved calculated-output baseline.
Existing Busted commands, fixture files, and legacy generation tools remain.

## Run locally

Requirements: Python 3.12+, Git, and Linux Docker containers. Both compared
revisions must support the builds' game/tree version. Current 3.29 inputs work
with PoB release v2.67.2 (`b32759ab0f31a1c8499a0d420cb0f0633d4fe478`). A 3.25
runtime cannot calculate those inputs: this runner does not downgrade builds,
skip incompatible inputs, or silently substitute a different runtime.

Run from the repository root. Use new output directories for each run:

```sh
# A missing prior directory bootstraps an empty corpus.
python spec/UpdateBuildCorpus.py --url https://api.pob.codes/test-builds --prior ../corpus-prior --output ../corpus-next

# Use actual, locally available Git refs or commit SHAs.
python spec/RunBuildDiff.py --base <base-sha> --head <candidate-sha> --corpus ../corpus-next --output ../comparison --strict

# Fixed fixtures only; no corpus or API access required.
python spec/RunBuildDiff.py --base <base-sha> --head <candidate-sha> --fixtures-only --output ../fixture-comparison --strict

# Refresh into a new directory; the prior corpus remains intact.
python spec/UpdateBuildCorpus.py --url https://api.pob.codes/test-builds --prior ../corpus-next --output ../corpus-later
```

Commit calculation edits before comparing: the runner archives committed
`src` and `runtime` from each ref, so uncommitted calculation edits are excluded.
It uses the harness in the current checkout identically for both revisions.
`--repo` can select another local Git checkout explicitly; the normal case
compares this checkout's own base/head. No source revisions are fetched implicitly.

Outputs are saved in `base/` and `head/` beneath the result directory. Logs name
each input, both resolved SHAs, the corpus digest, and the Docker image ID.
Exit 0 means the requested comparison completed. With `--strict`, exit 1 means
all calculations completed but stats differ. Exit 2 means invalid arguments,
inputs, calculations, or comparison execution. Without `--strict`, differences
are reported in the log and exit 0; execution errors still fail.

The runner builds `Dockerfile.test-builds` automatically. Its two source images
are digest-pinned; the existing dependencies use a GC64-capable LuaJIT to avoid
the older allocator's memory limit. `--image <local-image>` reuses an image;
both sides use the same inspected image ID. `--parallel 1` runs one container
at a time instead of two. `--extra-fixtures <directory>` adds local XML inputs.

Calculation containers have no network, read-only runtime/input mounts, two
CPUs, and 2 GiB memory. Batches contain at most 25 inputs, with a 30-second
per-input alarm and a 300-second container deadline. Missing player stats,
missing active-minion stats, import popups, incomplete output sets, and runtime
errors fail the run. A failed batch cancels queued batches; running containers
remain bounded by their deadlines. Reordered XML attributes do not create
false comparison failures.

## Test the harness

```sh
python -m unittest discover -s tests -p 'test_update_build_corpus.py' -v
python -m unittest discover -s tests -p 'test_build_diff_contract.py' -v
docker build -t pob-corpus-tests -f Dockerfile.test-builds .
docker run --rm --network none --mount "type=bind,source=$PWD,target=/workdir,readonly" -w /workdir pob-corpus-tests luajit tests/test_diff_output.lua
```

The last command uses POSIX shell syntax; in PowerShell, use an absolute path
for the mount's `source`. The existing `docker compose run --rm --no-TTY
busted-tests` command still runs the application's Busted suite.

## Corpus contract and publication

Schema 1 has `batchId`, UTC `period` (`YYYY-MM`), canonical millisecond UTC
`generatedAt`, `patchVersion`, `requestedCount: 100`, `count: 1..100`, and
`builds: [{code, sha256}]`. SHA-256 covers the exact UTF-8 code string. Limits:
150 KiB encoded per input, 4 MiB inflated XML, 16 MiB per API response.

Validate the complete batch before writing the new corpus. Append new hashes
in batch order and evict the oldest beyond 500. Replays do nothing; a changed
payload under an accepted batch ID fails. Older/same-period replacement batches
are ignored. Duplicates in later months do not reorder retained builds.
`manifest.json` and `codes/<sha256>.txt` are published together in one Git commit.

Refreshes use ETags and bounded retries for transport errors, HTTP 429 and 5xx.
They honor `Retry-After`. Invalid responses never replace the prior corpus.
A normal fast-forward push rejects a competing writer; the next run refetches
and reapplies. The API needs no authentication. Calculation jobs never call it.

## GitHub activation

1. Put the CI changes on a branch with a compatible PoB runtime. For PR
   comparisons, the target/base must also be compatible with the corpus.
2. Manually run **Refresh monthly build corpus** on that branch to bootstrap
   `build-test-corpus`. Manual dispatch is allowed before setting a repository
   variable; only a maintainer-triggered refresh has `contents: write`.
3. Manually run **Compare saved builds**. Optional `base_ref`/`head_ref` select
   explicit revisions; empty inputs compare the dispatched commit to itself.
   Enable `strict` for a zero-difference control. Manual runs require the saved
   corpus branch and fail if it is absent.
4. Set `TEST_BUILD_CORPUS_ENABLED=true` to enable rotating comparisons on PRs.
   Fixed fixtures and harness tests run without this variable. PR comparisons
   always use the actual event's base/head SHAs and have read-only credentials.
5. For daily conditional polling, put the refresh workflow and helpers on the
   default branch and enable the same variable. A manual run on a development
   branch does not activate GitHub's schedule.

The job checks the API daily but only retains a new batch once per month.
Provider outages do not affect comparisons using the saved corpus. PR stat
differences are advisory; import/calculation failures are errors in both modes.
Confirm hosted-runner permissions and performance before making the rotating
job required. FIFO retention at 500 is covered by tests; 500 distinct live
builds require accumulation over multiple monthly batches to benchmark.
