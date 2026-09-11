#!/bin/sh
set -eo pipefail
umask 0

# Work on a copy: checking out the base must not change the user's checkout.
rm -rf /tmp/workdir
mkdir /tmp/workdir
cp -rf "$WORKDIR"/. /tmp/workdir/
cd /tmp/workdir
git config --global --add safe.directory /tmp/workdir
git config --global --add advice.detachedHead false
if [ -n "$HEADREF" ]; then
    git diff --binary "$HEADREF" -- .busted src/HeadlessWrapper.lua spec/ > /tmp/HeadPatch
    git reset --hard "$HEADREF"
    git clean -fd
    git apply --allow-empty --index /tmp/HeadPatch
fi
headsha=$(git rev-parse HEAD)

# The same response and test tools identify the inputs and calculated base.
. ./spec/BuildCache.sh
export CACHEDIR="${CACHEDIR:-/tmp/cachedir}/$CACHE_KEY"
mkdir -p "$CACHEDIR"
echo "[+] Baseline cache: $CACHE_KEY"
if [ ! -f "$CACHEDIR/$DEV_SHA" ]; then
    rm -f "$CACHEDIR"/*.build "$CACHEDIR"/*.time
    cp "$CORPUS_FILE" "$CACHEDIR/corpus.json"
    luajit spec/FetchTestBuilds.lua "$CACHEDIR"
fi
cp "$CACHEDIR/builds.txt" spec/builds.txt

# Restart PoB after each batch of 50, then calculate the checked-in fixtures.
calculate() {
    export BUILDCACHEPREFIX="$1"
    mkdir -p "$BUILDCACHEPREFIX"
    cat spec/builds.txt | dos2unix | parallel --jobs "${BUILD_JOBS:-2}" --halt now,fail=1 --will-cite --ungroup --pipe -N50 \
        'batch=$(mktemp); cat > "$batch"; BUILDLINKS="$batch" busted --lua=luajit -r generate'
    busted --lua=luajit -r generate
    expected=$(( $(wc -l < spec/builds.txt) + $(find spec/TestBuilds -maxdepth 1 -name '*.xml' | wc -l) ))
    actual=$(find "$BUILDCACHEPREFIX" -maxdepth 1 -name '*.build' | wc -l)
    [ "$actual" -eq "$expected" ] || { echo "Expected $expected saved builds; got $actual" >&2; exit 1; }
    echo "[+] Calculated $actual builds into $BUILDCACHEPREFIX"
}

# Normal PR/local runs calculate head. The nightly job only prepares the base.
if [ "${BASE_ONLY:-0}" != 1 ]; then
    rm -rf /tmp/headsha
    rm -f src/Settings.xml
    calculate /tmp/headsha
fi
if [ ! -f "$CACHEDIR/$DEV_SHA" ]; then
    # Carry the same test harness across revisions, without copying game calculations.
    git diff --binary "$DEV_SHA" -- .busted src/HeadlessWrapper.lua spec/ > /tmp/DevPatch
    git reset --hard "$DEV_SHA"
    git clean -fd
    git apply --allow-empty --index /tmp/DevPatch
    calculate "$CACHEDIR"
    date > "$CACHEDIR/$DEV_SHA"
    echo "[+] Base calculated: $DEV_SHA"
else
    echo "[+] Base reused: $DEV_SHA"
fi
[ "${BASE_ONLY:-0}" != 1 ] || exit 0

# Keep the full report, collecting stat differences for the final summary/check.
: > /tmp/build-stat-diffs
report() {
    title=$1; language=$2; shift 2
    if output=$("$@"); then return; else status=$?; fi
    [ "$status" -eq 1 ] && [ -n "$output" ] || return "$status"
    printf '## %s\n```%s\n%s\n```\n' "$title" "$language" "$output"
    case "$title" in
        "Output Diff for "*) printf '## %s\n%s\n' "$title" "$output" >> /tmp/build-stat-diffs ;;
    esac
}
compared=0
for base in "$CACHEDIR"/*.build; do
    name=$(basename "$base" .build)
    report "Runtime comparison for $name.time" '' luajit spec/DiffRuntime.lua "/tmp/headsha/$name.time" "$CACHEDIR/$name.time" "$name.time"
    xmllint --exc-c14n "$base" > /tmp/base.xml
    xmllint --exc-c14n "/tmp/headsha/$name.build" > /tmp/head.xml
    report "Savefile Diff for $name.build" diff diff /tmp/base.xml /tmp/head.xml
    report "Output Diff for $name.build" '' luajit spec/DiffOutput.lua "/tmp/headsha/$name.build" "$base"
    compared=$((compared + 1))
done
echo "[+] Compared $compared builds: $DEV_SHA -> $headsha"
luajit spec/BuildSummary.lua /tmp/build-stat-diffs "$compared" "$DEV_SHA" "$headsha"
