"""Data models for project snapshots."""
from dataclasses import dataclass, field, asdict
from typing import Optional
from datetime import datetime


@dataclass
class Project:
    developer: str
    id: str
    name: str
    url: str
    location: str
    municipality: str = ""
    county: str = ""
    status: str = "unknown"         # planning | selling | sold_out | completed
    housing_types: list = field(default_factory=list)  # apartment | townhouse | villa
    total_units: Optional[int] = None
    available_units: Optional[int] = None
    sold_units: Optional[int] = None
    price_from: Optional[int] = None   # SEK
    price_to: Optional[int] = None     # SEK
    monthly_fee_from: Optional[int] = None   # SEK/month (bostadsrätt avgift)
    monthly_fee_to: Optional[int] = None
    move_in_date: Optional[str] = None
    scraped_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class DeveloperSnapshot:
    developer: str
    developer_url: str
    scraped_at: str
    projects: list  # list of Project dicts
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "developer": self.developer,
            "developer_url": self.developer_url,
            "scraped_at": self.scraped_at,
            "project_count": len(self.projects),
            "error": self.error,
            "projects": self.projects,
        }
