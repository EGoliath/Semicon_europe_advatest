import csv,sys
rows=list(csv.DictReader(open(sys.argv[1])))
files=[]; [files.append(r["file"]) for r in rows if r["file"] not in files]
ms=[m for m in ["pack1","pack9","zstd3","zstd9","zstd19","gzip6","xz6"] if any(r["method"]==m for r in rows)]
by={(r["file"],r["method"]):r for r in rows}
size={r["file"]:r["size"] for r in rows}
print("file|size|"+"|".join(ms)+"|pack9/zstd9")
for f in files:
    cells=[]
    for m in ms:
        r=by.get((f,m))
        if not r: cells.append("-"); continue
        ok=r["sha_ok"]=="True" and r["c_rc"]=="0" and r["d_rc"]=="0"
        cells.append(r["ratio"] if ok else f"FAIL{r['c_rc']}/{r['d_rc']}")
    a,b=by.get((f,"pack9")),by.get((f,"zstd9"))
    rel=f"{int(b['csize'])/int(a['csize']):.3f}" if a and b and a["c_rc"]=="0" and int(a["csize"])>0 else ""
    print(f"{f}|{size[f]}|"+"|".join(cells)+"|"+rel)
print("\nspeed MB/s c/d and peak MB c/d, files>1MB")
for f in files:
    if int(size[f])<1e6: continue
    print(f, " ; ".join(f"{m}:{by[(f,m)]['c_MBps']}/{by[(f,m)]['d_MBps']} {by[(f,m)]['c_peakMB']}/{by[(f,m)]['d_peakMB']}" for m in ms if (f,m) in by and by[(f,m)]["c_rc"]=="0"))
print("side:",[(r["file"],r["method"],r["side_files"]) for r in rows if r["side_files"]])
print("sha mismatches with rc0/0:",[(r["file"],r["method"]) for r in rows if r["sha_ok"]!="True" and r["c_rc"]=="0" and r["d_rc"]=="0"])
