"""Does the handedness matchup carry information the projection is missing --
and more importantly, information the POSTED LINE is missing?

Design notes, so the result can be trusted or dismissed on its merits:

  * The predictor is the opponent's 2025 strikeout rate against the hand the
    starter throws. 2025, not 2026, so nothing about the games being scored
    can leak backwards into the thing predicting them. The graded starts all
    fall in a six-day window at the end of August 2026.
  * Nothing is fitted. No coefficient is estimated on the same rows it is
    then scored against. Test A and C are plain correlations; test B applies
    a mechanical batters-faced conversion with the multiplier stated up front
    and its sensitivity reported.
  * 86 graded starts, 85 distinct pitchers, so the rows are near-independent.
"""
import json, math, random, statistics
from pathlib import Path

ROOT = Path("/tmp/cps/craftypicks")

HANDS_RAW = """453286|R 476594|R 518876|R 519242|L 543037|R 543243|R 571510|L
592332|R 592662|L 593958|L 594798|R 605280|R 605483|L 607074|L 607192|R
607200|R 607625|R 608372|R 608379|R 623454|R 624133|L 640455|L 641816|R
641927|R 642547|R 645261|R 650633|R 656550|R 656849|L 656876|R 663554|R
663556|L 663623|R 663776|L 663903|R 664285|L 666157|L 666200|L 667755|R
669302|R 669373|L 669432|L 669713|R 669923|R 671096|L 671737|R 672456|R
674841|L 675512|R 676083|R 676282|L 676440|R 676917|R 680570|R 681035|R
681190|R 681517|R 685299|R 686613|R 687312|R 687473|R 687562|L 690279|R
690986|L 691587|R 693433|R 693645|R 693821|R 693855|L 694738|R 694819|R
695076|R 695549|R 695611|L 696149|R 701542|R 702021|L 702070|L 703615|R
800048|L 800600|L 801139|L 805673|R 807739|L 808967|R"""
HAND = {}
for tok in HANDS_RAW.split():
    pid, code = tok.split("|")
    HAND[int(pid)] = code

SPLITS_RAW = """158|vl|354|1821 141|vr|798|4560 116|vl|380|1702 141|vl|301|1620
143|vr|873|4220 139|vr|941|4185 146|vr|864|4309 111|vl|411|1777 147|vl|400|1697
135|vr|818|4236 133|vl|367|1479 119|vl|378|1709 121|vr|923|4398 158|vr|912|4406
109|vl|351|1836 111|vr|1008|4429 143|vl|464|1946 133|vr|1039|4672 117|vl|286|1310
119|vr|975|4478 112|vl|340|1588 109|vr|965|4374 118|vr|1039|4573 113|vr|1070|4581
138|vl|373|1682 117|vr|1015|4777 112|vr|937|4574 144|vl|368|1678 147|vr|1063|4538
120|vr|920|4279 136|vr|987|4348 145|vl|358|1556 135|vl|343|1851 144|vr|1003|4508
138|vr|948|4387 137|vr|980|4449 142|vl|392|1697 136|vl|459|1852 115|vl|354|1443
116|vr|1074|4391 140|vr|933|4374 142|vr|980|4362 110|vr|1039|4322 121|vl|402|1780
118|vl|300|1435 115|vr|1177|4465 134|vr|1043|4539 139|vl|456|1860 146|vl|383|1833
110|vl|418|1698 113|vl|345|1501 108|vl|309|1145 145|vr|1006|4431 120|vl|431|1703
114|vr|918|4159 140|vl|394|1672 108|vr|1318|4855 114|vl|426|1784 134|vl|379|1469
137|vl|400|1623"""
SPLIT = {}
for tok in SPLITS_RAW.split():
    tid, code, so, pa = tok.split("|")
    SPLIT.setdefault(int(tid), {})[code] = 100.0 * int(so) / int(pa)
MEAN = {c: statistics.mean(v[c] for v in SPLIT.values() if c in v)
        for c in ("vr", "vl")}

rows = []
for r in json.load(open(ROOT / "data/pitcher_ratings.json"))["pitchers"]:
    if r.get("actual") is None or r.get("line") is None:
        continue
    hand = HAND.get(r["pitcher_id"])
    club = SPLIT.get(r.get("opponent_id"))
    if not hand or not club:
        continue
    code = "vl" if hand == "L" else "vr"
    if code not in club:
        continue
    rows.append({**r, "hand": hand, "signal": club[code] - MEAN[code]})

print(f"{len(rows)} graded starts carry a usable matchup signal")
print(f"2025 league K%: vs RHP {MEAN['vr']:.2f}  vs LHP {MEAN['vl']:.2f}")
sig = [r["signal"] for r in rows]
print(f"signal spread: {min(sig):+.2f} to {max(sig):+.2f} points, "
      f"sd {statistics.pstdev(sig):.2f}\n")


def corr(a, b):
    n = len(a)
    ma, mb = statistics.mean(a), statistics.mean(b)
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    da = math.sqrt(sum((x - ma) ** 2 for x in a))
    db = math.sqrt(sum((y - mb) ** 2 for y in b))
    return num / (da * db) if da and db else 0.0


def boot_corr(a, b, n=20000):
    random.seed(11)
    idx = range(len(a))
    out = []
    for _ in range(n):
        s = random.choices(list(idx), k=len(a))
        out.append(corr([a[i] for i in s], [b[i] for i in s]))
    out.sort()
    return out[int(.025 * n)], out[int(.975 * n)]


res_model = [r["actual"] - r["projection"] for r in rows]
res_line = [r["actual"] - r["line"] for r in rows]

for label, res in (("A. against our projection", res_model),
                   ("B. against the posted line", res_line)):
    c = corr(sig, res)
    lo, hi = boot_corr(sig, res)
    verdict = ("signal the target is missing" if lo > 0 else
               "no evidence of signal the target is missing")
    print(f"{label}")
    print(f"   correlation of matchup signal with the residual: {c:+.3f}")
    print(f"   95% bootstrap CI: {lo:+.3f} to {hi:+.3f}   -> {verdict}\n")

# Mechanical adjustment, no fitting: BF batters x signal points / 100.
print("C. applying the matchup mechanically (no fitted coefficient)")
base_ours = statistics.mean(abs(r["actual"] - r["projection"]) for r in rows)
base_line = statistics.mean(abs(r["actual"] - r["line"]) for r in rows)
print(f"   our miss {base_ours:.3f} K   the line's {base_line:.3f} K   "
      f"gap {base_ours - base_line:+.3f}")
for bf in (21, 24, 27):
    adj = [abs(r["actual"] - (r["projection"] + bf * r["signal"] / 100.0))
           for r in rows]
    m = statistics.mean(adj)
    print(f"   BF={bf}: adjusted miss {m:.3f} K  "
          f"({m - base_ours:+.3f} vs ours, {m - base_line:+.3f} vs the line)")


# ---------------------------------------------------------------------------
# Result on 2026-09-02, 86 graded starts:
#
#   correlation with our residual   +0.050   95% CI -0.165 to +0.260
#   correlation with the line's     +0.057   95% CI -0.176 to +0.286
#   mechanical adjustment           improves our miss by 0.01 K, which is noise,
#                                   and leaves us 0.19 K worse than the line
#
# Read that as "no evidence", not as "no edge". With 86 rows this test could
# only have found a correlation stronger than about 0.22. Settling it needs
# 194 starts to rule in r=0.20, or 347 to rule in r=0.15 -- roughly 8 and 19
# more days at the current collection rate. Re-run this then; the constants
# above are the only thing that has to be refreshed.
