#!/bin/sh
set -eu
failed=0
count=0
changed=0
for base in /outputs/base/*.build; do
    if [ ! -f "$base" ]; then
        echo "No calculated build pairs to compare"
        exit 2
    fi
    name=$(basename "$base")
    status=0
    luajit /harness/DiffOutput.lua "/outputs/head/$name" "$base" || status=$?
    if [ "$status" -ne 0 ]; then
        printf 'Input %s comparison exit status: %s\n' "$name" "$status"
    fi
    if [ "$status" -gt 1 ]; then
        failed=2
    elif [ "$status" -eq 1 ]; then
        changed=$((changed + 1))
        if [ "${STRICT_DIFF:-0}" = 1 ] && [ "$failed" -eq 0 ]; then
            failed=1
        fi
    fi
    count=$((count + 1))
done
printf 'Compared %s input pairs; %s with differences\n' "$count" "$changed"
exit "$failed"
