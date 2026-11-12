"""CPU profiles for the AMD EPYC (Zen 4, e.g. EPYC 9554) versions of the codecs.

Two profiles, chosen by the mode name suffix (`amd_planes_st`, `amd_planes_mt`, ...):

st  "single core" in the strict sense of the research note: ONE software thread
    in total (no I/O thread, no worker pool, OpenMP kernels with 1 thread, zstd
    nbWorkers = 0), and the process pinned to one physical core so the scheduler
    cannot move it between CCDs (each Zen 4 CCD has its own 32 MB L3).
mt  every physical core first, then the SMT siblings. Worker threads are pinned
    round-robin over the L3 domains (CCDs) so that consecutive jobs land on
    different L3 caches before any L3 is shared; OpenMP uses
    OMP_PROC_BIND=spread / OMP_PLACES=cores.

Everything is read from /sys at run time, so the same code runs (and is measured)
on the Intel development laptop, an EPYC host or a VM; inside a VM the guest's
topology is what counts (lscpu / cgroup limits are respected via
os.sched_getaffinity).

ISA: the C kernels are built in three variants (generic x86-64-v2, AVX2 =
x86-64-v3 tuned for znver3, AVX-512 = znver4). The best one the CPU supports
is loaded; PATAMD_ISA=generic|avx2|avx512 caps it (A/B testing like AOCL's
AOCL_ENABLE_INSTRUCTIONS).
"""
import os
import threading

_lock = threading.Lock()
_next = [0]


def _read(path, default=""):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return default


def _cpulist(s):
    out = []
    for part in s.split(","):
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-")
            out += range(int(a), int(b) + 1)
        else:
            out.append(int(part))
    return out


def allowed_cpus():
    try:
        return sorted(os.sched_getaffinity(0))
    except AttributeError:                         # non-Linux
        return list(range(os.cpu_count() or 1))


def topology():
    """{'l3': [[cpus of L3 domain 0], ...], 'order': cpu order for mt pinning,
    'physical': number of physical cores, 'flags': set of cpu flags}"""
    cpus = allowed_cpus()
    l3, seen = {}, set()
    for c in cpus:
        key = _read(f"/sys/devices/system/cpu/cpu{c}/cache/index3/shared_cpu_list", "all")
        l3.setdefault(key, []).append(c)
    first_sib = []                                  # one cpu per physical core
    for c in cpus:
        sib = _cpulist(_read(f"/sys/devices/system/cpu/cpu{c}/topology/thread_siblings_list", str(c)))
        sib = [s for s in sib if s in cpus] or [c]
        if sib[0] not in seen:
            seen.add(sib[0])
            first_sib.append(sib[0])
    phys = set(first_sib)
    doms = [sorted(v, key=lambda c: (c not in phys, c)) for v in l3.values()]
    order, i = [], 0                                # round robin over L3 domains
    while any(i < len(d) for d in doms):
        for d in doms:
            if i < len(d) and d[i] in phys:
                order.append(d[i])
        i += 1
    order += [c for c in cpus if c not in phys]     # SMT siblings last
    flags = set()
    for line in _read("/proc/cpuinfo").splitlines():
        if line.startswith("flags"):
            flags = set(line.split(":", 1)[1].split())
            break
    return {"l3": list(l3.values()), "order": order, "physical": len(phys), "flags": flags}


_TOPO = None


def topo():
    global _TOPO
    if _TOPO is None:
        _TOPO = topology()
    return _TOPO


def isa():
    """ISA variant of the C kernels to load: avx512 / avx2 / generic."""
    f = topo()["flags"]
    best = ("avx512" if {"avx512f", "avx512bw", "avx512vl"} <= f else
            "avx2" if {"avx2", "bmi2"} <= f else "generic")
    cap = os.environ.get("PATAMD_ISA", "").lower()
    rank = {"generic": 0, "avx2": 1, "avx512": 2}
    if cap in rank and rank[cap] < rank[best]:
        return cap
    return best


class Profile:
    """Threading policy of one run. workers = Python worker threads (frames),
    zstd_threads = nbWorkers for the single-stream (v2) modes."""

    def __init__(self, name, threads=-1):
        self.name = name
        t = topo()
        if name == "st":
            self.workers = 1
            self.cpus = [t["order"][0]] if t["order"] else []
        else:
            n = threads if threads and threads > 0 else len(t["order"])
            self.workers = max(1, n)
            self.cpus = t["order"][:self.workers]
        self.zstd_threads = 0 if name == "st" else self.workers

    def enter(self):
        """Pin the calling (main) thread. st: to its one core; mt: no restriction
        (workers pin themselves). Returns the previous affinity."""
        prev = allowed_cpus()
        if self.name == "st" and self.cpus:
            os.sched_setaffinity(0, self.cpus)
        return prev

    @staticmethod
    def leave(prev):
        try:
            os.sched_setaffinity(0, prev)
        except OSError:
            pass

    def pin_worker(self):
        """ThreadPoolExecutor initializer: pin each new worker thread to the next
        CPU of the round-robin L3 order (Linux: affinity is per thread)."""
        if not self.cpus:
            return
        with _lock:
            c = self.cpus[_next[0] % len(self.cpus)]
            _next[0] += 1
        try:
            os.sched_setaffinity(0, [c])
        except OSError:
            pass


class InlineExecutor:
    """Executor that runs every task in the calling thread (st profile: no
    worker threads at all). Same submit()/result() surface as concurrent.futures."""

    class _F:
        def __init__(self, fn, a, kw):
            try:
                self._r, self._e = fn(*a, **kw), None
            except BaseException as e:       # re-raised by result()
                self._r, self._e = None, e

        def result(self):
            if self._e is not None:
                raise self._e
            return self._r

    def submit(self, fn, *a, **kw):
        return self._F(fn, a, kw)

    def map(self, fn, *its):
        return [fn(*x) for x in zip(*its)]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def executor(profile):
    from concurrent.futures import ThreadPoolExecutor
    if profile.name == "st":
        return InlineExecutor()
    return ThreadPoolExecutor(profile.workers, initializer=profile.pin_worker)

