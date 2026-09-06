#!/bin/sh
set -eu
failed=0
count=0
for base in /outputs/base/*.build; do
    name=$(basename "$base")
    status=0
    luajit /harness/DiffOutput.lua "/outputs/head/$name" "$base" || status=$?
    if [ "$status" -gt 1 ]; then
        failed=2
    elif [ "$status" -eq 1 ] && [ "${STRICT_DIFF:-0}" = 1 ] && [ "$failed" -eq 0 ]; then
        failed=1
    fi
    count=$((count + 1))
done
printf 'Compared %s input pairs\n' "$count"
exit "$failed"
