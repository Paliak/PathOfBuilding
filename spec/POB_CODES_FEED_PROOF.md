# PoB Codes feed integration proof

This opt-in proof connects one batch from `https://api.pob.codes/test-builds`
to the existing `GenerateBuilds.lua` generator. It leaves `BuildDiff.sh`,
`DiffOutput.lua`, Docker Compose, and the existing scheduled workflows in place.
It adds no FIFO, scheduled feed refresh, persisted corpus, or reporting system.

The adapter validates every code/hash and bounded XML before creating a new
input directory. It never replaces existing inputs. It makes one public request;
there is no API secret. On failure, retry later with a new output directory.

Run from the repository root with Python 3 and Docker:

```sh
POB_FEED_DOCKER_TEST=1 python3 -m unittest discover -s tests -p test_pob_codes_feed.py -v
python3 spec/FetchTestBuilds.py --output /tmp/pob-codes-inputs
mkdir /tmp/pob-codes-output
chmod 777 /tmp/pob-codes-output
docker compose run --rm --no-TTY -v /tmp/pob-codes-inputs:/inputs:ro -v /tmp/pob-codes-output:/outputs -e BUILDINPUTDIR=/inputs -e BUILDCACHEPREFIX=/outputs busted-tests timeout 300 busted --lua=luajit -r generate
```

`--batch saved.json` reads an offline API response instead. `BUILDINPUTDIR` selects
decoded files and rejects simultaneous `BUILDLINKS`; unset it for the original
behavior. In this opt-in mode, failed imports and incomplete initialization fail
instead of saving a default build as a successful feed input.

The test wraps an existing fixture in the API format, decodes it, calculates it
twice with the existing generator, checks equality with `DiffOutput.lua`, then
changes one saved stat to prove differences are detected. An unsupported target
version must fail. PR tests use saved fixtures; manual workflow runs also check
the live download/decoding boundary. No live calculation is implied by that check.

The old tests-branch runtime does not support current exports. A live calculation
may therefore fail even when download/decoding succeeds. Runtime compatibility
must be resolved before a recurring modern-build comparison is enabled. This
PR provides the starting proof; FIFO and broader runner changes can be reviewed
separately. Manual workflow dispatch requires the workflow to be registered on
the repository's default branch; the local commands work before that merge.
