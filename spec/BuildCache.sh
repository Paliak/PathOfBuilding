# Shared by GitHub Actions and the local runner so cache identity is identical.
DEV_SHA=$(git rev-parse "${DEVREF:-origin/dev}^{commit}")
if [ -z "${CORPUS_FILE:-}" ]; then
    CORPUS_FILE=$(mktemp)
    curl --fail --show-error --silent --max-time 60 \
        https://api.pob.codes/test-builds/corpus -o "$CORPUS_FILE"
fi
corpus_hash=$(sha256sum "$CORPUS_FILE" | cut -d ' ' -f 1)
test_hash=$(git ls-files -z -- .busted docker-compose.yml src/HeadlessWrapper.lua \
    spec/BuildCache.sh spec/BuildDiff.sh spec/BuildStats.lua spec/FetchTestBuilds.lua \
    spec/GenerateBuilds.lua spec/TestBuilds | xargs -0 git hash-object -- | sha256sum | cut -d ' ' -f 1)
CACHE_KEY="pob-builds-v1-$DEV_SHA-$corpus_hash-$test_hash"
export DEV_SHA CORPUS_FILE CACHE_KEY
