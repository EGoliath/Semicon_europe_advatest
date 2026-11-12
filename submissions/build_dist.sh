#!/usr/bin/env bash
# Re-sync the shared files into every package and rebuild dist/<package>.zip
set -euo pipefail
cd "$(dirname "$0")"
for d in 0*_*/; do
  d=${d%/}
  cp _shared/evaluate.py "$d/"
  if [ -f "$d/codec.py" ]; then                      # PXT1 packages
    cp _shared/patio.py "$d/"
    cp _shared/pxt_compress.py "$d/compress.py"
    cp _shared/pxt_decompress.py "$d/decompress.py"
  fi
done
rm -rf dist && mkdir dist
for d in 0*_*/; do
  d=${d%/}
  zip -qr "dist/$d.zip" "$d" -x '*/__pycache__/*' '*.so' '*/eval_*' '*/out/*' '*/restored/*'
done
ls -la dist
