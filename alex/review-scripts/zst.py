"""zst.py c <level> <in> <out> | d <in> <out>  -- stdlib zstd (libzstd 1.5.7), single thread, streaming."""
import sys, shutil
from compression import zstd
m = sys.argv[1]
if m == "c":
    with open(sys.argv[3], "rb") as i, zstd.open(sys.argv[4], "wb", level=int(sys.argv[2])) as o:
        shutil.copyfileobj(i, o, 1 << 20)
else:
    with zstd.open(sys.argv[2], "rb") as i, open(sys.argv[3], "wb") as o:
        shutil.copyfileobj(i, o, 1 << 20)
