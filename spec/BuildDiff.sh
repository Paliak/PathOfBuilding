#!/bin/sh
set -eu
# Run on the host with Python 3.12+ and Docker. No downloads inside calculation.
exec python3 spec/RunBuildDiff.py --base "${DEVREF:?set DEVREF}" --head "${HEADREF:?set HEADREF}" --corpus "${CORPUS_DIR:?set CORPUS_DIR}" --output "${OUTPUT_DIR:?set OUTPUT_DIR}"
