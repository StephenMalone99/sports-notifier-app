from dataclasses import asdict, dataclass, field
from datetime import datetime


@dataclass
class Event:
    id: str                 # stable id, used to avoid duplicate alerts
    sport: str              # "cs2" | "darts" | "liverpool"
    title: str
    start: datetime         # timezone-aware (UTC)
    end: datetime | None = None
    competition: str = ""
    detail: str = ""        # e.g. venue, opponent, prize pool
    url: str = ""
    all_day: bool = False   # darts / CS2 tournaments: date matters, not time
    tags: list[str] = field(default_factory=list)

    def to_dict(self):
        d = asdict(self)
        d["start"] = self.start.isoformat()
        d["end"] = self.end.isoformat() if self.end else None
        return d

    @staticmethod
    def from_dict(d):
        d = dict(d)
        d["start"] = datetime.fromisoformat(d["start"])
        d["end"] = datetime.fromisoformat(d["end"]) if d.get("end") else None
        return Event(**d)
