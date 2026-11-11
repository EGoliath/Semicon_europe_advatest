#!/bin/bash
# One archive at a time: unzip Vectors.vec -> bench.py (compress, separate-dir decompress, SHA-256 check,
# record, delete decompressed + compressed) -> delete .vec. Aborts if the review dir exceeds 20 GB.
H=/c/Users/Alex/Documents/Hackatoon-Challenge-Semi/hackathon/hackathon
R=$(cd "$(dirname "$0")/.." && pwd)
CAP=$((20 * 1024 * 1024))  # KB
cd "$R" || exit 1
for a in $H/001.pat.zip $H/002.pat.zip $H/003.pat.zip $H/0{04..29}.pat; do
  n=$(basename "$a" | cut -c1-3)
  used=$(du -sk "$R" | cut -f1); [ "$used" -gt "$CAP" ] && { echo "ABORT: $used KB > 20 GB"; exit 1; }
  d=hack/in/$n; rm -rf hack/in; mkdir -p "$d"
  unzip -q -o "$a" Vectors.vec -d "$d" || { echo "UNZIP FAIL $n"; continue; }
  mv "$d/Vectors.vec" "$d/$n.vec"
  sz=$(stat -c %s "$d/$n.vec")
  m=pack1,pack9,zstd3,zstd9,gzip6
  [ "$sz" -lt 100000000 ] && m=$m,zstd19,xz6   # slow baselines only where they finish in minutes
  python -I scripts/bench.py work hack.csv $m "$d/$n.vec"
  echo "peak KB in review dir before delete: $(du -sk "$R" | cut -f1)"
  rm -rf hack/in
done
echo ALLDONE
