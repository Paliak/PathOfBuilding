#!/bin/sh
set -eo pipefail
umask 0

git config --global safe.directory '*'

if [ -f "/cache/corpus_$BASE_BRANCH_SHA.json" ]; then
    # Cache not found for current BASE_BRANCH_SHA. Make a working copy to revert to BASE_BRANCH_SHA
    rm -rf /tmp/workdir && mkdir /tmp/workdir && cp -rf "/workdir/." /tmp/workdir/ && cd /tmp/workdir/src
    
    git config --global --unset-all 'url.https://github.com/.insteadOf' 2>/dev/null || true
    git config --global --add 'url.https://github.com/.insteadOf' 'git@github.com:'
    git config --global --add 'url.https://github.com/.insteadOf' 'ssh://git@github.com/'
    
    git status

    # Retain specific tests related files in case they were just updated in the current working branch
    git diff --no-color "$BASE_BRANCH_SHA" -- ../.busted _SimpleGraphic.def.lua HeadlessWrapper.lua ../spec/ > /tmp/HeadPatch
    git reset --hard "$BASE_BRANCH_SHA"
    git clean -fd
    cd .. && git apply /tmp/HeadPatch && cd src
    
    git status
    cat /tmp/HeadPatch
    cat ../spec/GenerateBuilds.lua

    rm -- /tmp/workdir/src/Settings.xml || true

    # Get a new list of builds to compute
    curl --fail --show-error --silent --max-time 60 \
        https://api.pob.codes/test-builds/corpus -o "/cache/corpus_$BASE_BRANCH_SHA.json"
    
    luajit -l HeadlessWrapper ../spec/GenerateBuilds.lua    
fi


