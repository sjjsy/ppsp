"""Session state for interactive variant discovery — persisted as ppsp_session.json."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

_SESSION_FILE = "ppsp_session.json"


@dataclass
class ChainStat:
    wins: int = 0
    seen: int = 0
    discarded: bool = False


@dataclass
class RoundRecord:
    stack: str
    generated: List[str]
    selected: List[str]


@dataclass
class SessionState:
    chain_stats: Dict[str, ChainStat] = field(default_factory=dict)
    rounds: List[RoundRecord] = field(default_factory=list)

    def record_round(self, stack: str, generated: List[str], selected: List[str]) -> None:
        """Update per-chain stats and append round record."""
        for chain in generated:
            self.chain_stats.setdefault(chain, ChainStat()).seen += 1
        for chain in selected:
            self.chain_stats.setdefault(chain, ChainStat()).wins += 1
        self.rounds.append(RoundRecord(stack=stack, generated=generated, selected=selected))

    def active_chains(self) -> List[str]:
        """Chains with ≥1 win and not discarded, ordered by win count descending."""
        active = [
            (c, s) for c, s in self.chain_stats.items()
            if s.wins >= 1 and not s.discarded
        ]
        return [c for c, _ in sorted(active, key=lambda x: (-x[1].wins, x[0]))]

    def all_seen_chains(self) -> List[str]:
        """All chains seen at least once, ordered by wins descending then name."""
        return [
            c for c, _ in sorted(self.chain_stats.items(), key=lambda x: (-x[1].wins, x[0]))
        ]

    def discard(self, chain: str) -> None:
        self.chain_stats.setdefault(chain, ChainStat()).discarded = True

    def reactivate(self, chain: str) -> None:
        if chain in self.chain_stats:
            self.chain_stats[chain].discarded = False

    def convergence_streak(self) -> int:
        """Number of trailing consecutive rounds selecting the same chain set."""
        if len(self.rounds) < 2:
            return 0
        last = set(self.rounds[-1].selected)
        count = 1
        for r in reversed(self.rounds[:-1]):
            if set(r.selected) == last:
                count += 1
            else:
                break
        return count

    def win_summary(self, n: int = 5) -> str:
        """Human-readable summary of top active chains."""
        active = [(c, self.chain_stats[c].wins) for c in self.active_chains()[:n]]
        if not active:
            return "(no wins yet)"
        return ", ".join(f"{c}×{w}" for c, w in active)

    def stacks_processed(self) -> List[str]:
        """Ordered list of stack names with at least one recorded round."""
        seen: Dict[str, None] = {}
        for r in self.rounds:
            seen[r.stack] = None
        return list(seen.keys())


def load_session(source: Path) -> SessionState:
    """Load session from ppsp_session.json; return empty SessionState if missing or corrupt."""
    path = source / _SESSION_FILE
    if not path.exists():
        return SessionState()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        stats = {k: ChainStat(**v) for k, v in data.get("chain_stats", {}).items()}
        rounds = [RoundRecord(**r) for r in data.get("rounds", [])]
        return SessionState(chain_stats=stats, rounds=rounds)
    except Exception as exc:
        logging.warning("Could not load %s: %s — starting fresh session", path.name, exc)
        return SessionState()


def save_session(state: SessionState, source: Path) -> None:
    """Write session to ppsp_session.json."""
    path = source / _SESSION_FILE
    data = {
        "chain_stats": {
            k: {"wins": v.wins, "seen": v.seen, "discarded": v.discarded}
            for k, v in state.chain_stats.items()
        },
        "rounds": [
            {"stack": r.stack, "generated": r.generated, "selected": r.selected}
            for r in state.rounds
        ],
    }
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
