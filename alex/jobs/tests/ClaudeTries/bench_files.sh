# Clean file-based benchmark: 1) compress all to disk, 2) decompress all stored files to disk, 3) compare.
# Times are wall clock around each process (date +%s.%N), MB = 10^6 bytes of the original .vec.
S=/c/Users/Alex/AppData/Local/Temp/claude/C--Users-Alex-Documents-Hackatoon-Challenge-Semi-jobs/463d473b-655b-47fa-a29e-a294d90d686c/scratchpad
T=/c/Users/Alex/Documents/Hackatoon-Challenge-Semi/jobs/tests/ClaudeTries/tries.exe
CFG="zstd:1 zstd:9 pack:1 pack:9"
tm() { local a=$(date +%s.%N); "$@" > /dev/null || echo "FAILED: $*"; local b=$(date +%s.%N); awk "BEGIN{printf \"%.3f\", $b - $a}"; }
echo "== phase 1: compress"
for i in 1 2 3 4 5; do mkdir -p $S/out/00$i; in=$S/in/00$i/Vectors.vec; n=$(stat -c %s $in)
  for c in $CFG; do m=${c%:*}; l=${c#*:}; t=$(tm $T c $m $l $in $S/out/00$i/${m}_$l.compr)
    echo "C,00$i,$m,L$l,$n,$(stat -c %s $S/out/00$i/${m}_$l.compr),$t,$(awk "BEGIN{printf \"%.1f\", $n/1e6/$t}")"; done; done
echo "== phase 2: decompress stored files"
for i in 1 2 3 4 5; do n=$(stat -c %s $S/in/00$i/Vectors.vec)
  for c in $CFG; do m=${c%:*}; l=${c#*:}; t=$(tm $T d $S/out/00$i/${m}_$l.compr $S/out/00$i/${m}_$l.vec)
    echo "D,00$i,$m,L$l,$n,$(stat -c %s $S/out/00$i/${m}_$l.vec),$t,$(awk "BEGIN{printf \"%.1f\", $n/1e6/$t}")"; done; done
echo "== phase 3: compare"
for i in 1 2 3 4 5; do in=$S/in/00$i/Vectors.vec; ref=$(sha256sum $in | cut -c1-64); echo "H,00$i,original,$ref"
  for c in $CFG; do m=${c%:*}; l=${c#*:}; o=$S/out/00$i/${m}_$l.vec
    h=$(sha256sum $o | cut -c1-64); d=$(cmp -l $in $o 2>&1 | wc -l)
    echo "H,00$i,${m}_L$l,$h,$([ "$h" = "$ref" ] && echo SAME || echo DIFFERENT),cmp_diff_lines=$d"; done
  cmp $S/out/00$i/zstd_9.vec $S/out/00$i/pack_9.vec && echo "X,00$i,zstd_9.vec == pack_9.vec"; done
echo "== done"
