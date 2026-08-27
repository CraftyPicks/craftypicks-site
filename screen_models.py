"""The shapes that move through the system.

Screens operate on Candidate objects only. That means every rule can be
tested without touching the network — which is the whole point.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class VsRoster:
    """Pitcher's career line against the batters on today's opposing roster."""
    pa: int = 0
    k: int = 0
    ab: int = 0
    h: int = 0
    doubles: int = 0
    triples: int = 0
    hr: int = 0
    bb: int = 0
    hbp: int = 0
    sf: int = 0
    batters_seen: int = 0        # how many of the roster he's actually faced

    @property
    def k_pct(self) -> Optional[float]:
        return self.k / self.pa if self.pa else None

    @property
    def avg(self) -> Optional[float]:
        return self.h / self.ab if self.ab else None

    def woba(self, w) -> Optional[float]:
        """wOBA from components. Denominator is AB+BB+SF+HBP (IBB ignored)."""
        denom = self.ab + self.bb + self.sf + self.hbp
        if not denom:
            return None
        singles = self.h - self.doubles - self.triples - self.hr
        num = (w["bb"] * self.bb + w["hbp"] * self.hbp + w["1b"] * singles
               + w["2b"] * self.doubles + w["3b"] * self.triples + w["hr"] * self.hr)
        return num / denom


@dataclass
class Candidate:
    """One probable starter on one day, with everything a screen needs."""
    pitcher_id: int
    name: str
    team: str
    opponent: str
    game_time: str = ""

    # Season form
    k_pct: Optional[float] = None          # K / batters faced
    k_per_9: Optional[float] = None
    innings: float = 0.0

    # The matchup
    opp_k_per_game: Optional[float] = None
    vs_roster: VsRoster = field(default_factory=VsRoster)

    # The market
    line: Optional[float] = None
    over_odds: Optional[int] = None
    under_odds: Optional[int] = None   # kept: de-vigging an over needs its under
    book: str = ""

    def missing(self) -> list:
        """What data is absent. A candidate with gaps is never bet."""
        gaps = []
        if self.k_pct is None: gaps.append("pitcher K%")
        if self.opp_k_per_game is None: gaps.append("opponent K/game")
        if self.line is None: gaps.append("posted line")
        return gaps


@dataclass
class Play:
    """A bet the system says to make, with its full reasoning."""
    candidate: Candidate
    screen: str                  # "A" or "B"
    side: str                    # always "OVER" — the under screen was removed
    line: float
    odds: int
    reasons: list = field(default_factory=list)

    def __str__(self):
        c = self.candidate
        return (f"[{self.screen}] {c.name} ({c.team}) vs {c.opponent} — "
                f"{self.side} {self.line} @ {self.odds:+d}")
