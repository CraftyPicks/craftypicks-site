# Calibrated spread pricing (college boards)

Problem: Detroit Mercy +34.5 posted as an 81% Best bet; 47 of 56 NCAAB picks
were underdogs; 13 of 15 Best bets were 18+ point dogs. BPI squeezes
blowouts (market spread ~1.24x BPI margin; ~0.83x FPI margin).

Pricing, in `scripts/ats.py`:
1. Stretch: margin x k, k fitted daily on the slate (min 12 games, clamped
   0.7-1.5; defaults NCAAB 1.24, NCAAF 0.83).
2. Blend: with both clubs at 5+ games, season scoring margin (halved, plus
   home edge) weighted 25% at 5 games up to 50% at 10.
3. Shrink: gap = raw x 0.5; SD = sport SD + 0.15 x |spread|.
4. Check the line: raw >= 15, or raw >= 8 on a 20+ spread. Amber banner,
   reason in words, no cover %.
Tiers on the shrunk gap: Best 4+, Lean 2+, Pass under 2. Tier records count
only picks posted with a stored tier.

Also fixed: ESPN odds parser read an unmatched favourite abbreviation as
"away favoured" (Air Force +12.5 should be -12.5).
