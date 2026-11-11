# bench_all.sh: one archive at a time:
#   1. unzip Vectors.vec
#   2. compress with pack L1, pack L9 and zstd L9 to disk
#   3. decompress each stored file to disk and check it against the original with SHA-256 and cmp
#   4. keep only the end file, then delete the work dir
# End file = pack L9. If pack cannot handle the file (not fixed-width lines), it is the zstd L9 file instead (user decision).
# Times are wall clock around each process, including disk I/O. MB = 10^6 bytes of the original .vec.
# usage: bash bench_all.sh <archive dir> <work dir> <results dir>
H=$1; W=$2; R=$3
T=$(cd "$(dirname "$0")" && pwd)/tries.exe
[ -d "$H" ] && [ -n "$W" ] && [ -n "$R" ] || { echo "usage: bench_all.sh <archive dir> <work dir> <results dir>"; exit 2; }
mkdir -p "$R"
CSV=$R/bench.csv
echo "archive,method,vec_B,compr_B,ratio,compr_s,compr_MBps,decomp_s,decomp_MBps,verified,note" > "$CSV"
now() { date +%s.%N; }
for a in $(ls "$H" | grep -E '^[0-9]{3}\.pat(\.zip)?$' | sort); do
  id=${a:0:3}
  rm -rf "$W"; mkdir -p "$W"
  # disk cap (user: 60 GB max): results so far + .vec + one decompressed copy + 1 GB for the compressed files
  need=$(( $(du -sb "$R" | cut -f1) + 2 * $(unzip -l "$H/$a" Vectors.vec | awk '/Vectors.vec/{print $1}') + 1000000000 ))
  if [ $need -gt 60000000000 ]; then echo "$id: STOP, would need $need B > 60 GB disk cap"; break; fi
  if ! unzip -q -o "$H/$a" Vectors.vec -d "$W"; then echo "$id,extract,,,,,,,,no,unzip failed" | tee -a "$CSV"; continue; fi
  in=$W/Vectors.vec; n=$(stat -c %s "$in"); ref=$(sha256sum "$in" | cut -c1-64)
  declare -A ok=()
  for c in pack:1 pack:9 zstd:9; do
    m=${c%:*}; l=${c#*:}; o=$W/${m}_$l
    t0=$(now); err=$("$T" c $m $l "$in" $o.compr 2>&1 >/dev/null); rc=$?; t1=$(now)
    if [ $rc -ne 0 ]; then echo "$id,${m}_L$l,$n,,,,,,,no,unsupported: $err" | tee -a "$CSV"; rm -f $o.compr; continue; fi
    cs=$(stat -c %s $o.compr)
    t2=$(now); derr=$("$T" d $o.compr $o.vec 2>&1 >/dev/null); t3=$(now)
    h=$(sha256sum $o.vec 2>/dev/null | cut -c1-64); on=$(stat -c %s $o.vec 2>/dev/null)
    note=""
    if [ "$h" = "$ref" ] && [ "$on" = "$n" ] && cmp -s "$in" $o.vec; then v=yes; ok[$c]=1
    else v=no; note="DIFFERENT: size $on vs $n, $(cmp -l "$in" $o.vec 2>/dev/null | wc -l) bytes differ $derr"; fi
    rm -f $o.vec
    awk -v id=$id -v m=${m}_L$l -v n=$n -v cs=$cs -v a=$t0 -v b=$t1 -v c=$t2 -v d=$t3 -v v=$v -v note="$note" \
      'BEGIN{printf "%s,%s,%d,%d,%.3f,%.3f,%.1f,%.3f,%.1f,%s,%s\n", id, m, n, cs, n/cs, b-a, n/1e6/(b-a), d-c, n/1e6/(d-c), v, note}' | tee -a "$CSV"
  done
  if [ -n "${ok[pack:9]}" ]; then mv $W/pack_9.compr "$R/${id}_pack9.compr"
  elif [ -n "${ok[zstd:9]}" ]; then mv $W/zstd_9.compr "$R/${id}_zstd9_fallback.compr"; echo "$id: end file is the zstd L9 fallback"
  else echo "$id: NO verified end file"; fi
  unset ok
  rm -rf "$W"
done
echo "== totals (verified rows only)"
awk -F, 'NR>1 && $10=="yes" {v[$2]+=$3; c[$2]+=$4; ct[$2]+=$6; dt[$2]+=$8; k[$2]++}
  END {for (m in v) printf "%s: %d files, %.0f MB -> %.1f MB (%.2fx), compr %.1f MB/s, decomp %.1f MB/s\n", m, k[m], v[m]/1e6, c[m]/1e6, v[m]/c[m], v[m]/1e6/ct[m], v[m]/1e6/dt[m]}' "$CSV"
echo "== done"
