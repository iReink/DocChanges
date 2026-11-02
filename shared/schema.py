from dataclasses import dataclass, field, asdict
from typing import Any

@dataclass
class Location:
    page: int
    bbox: list[float]
    start: int = 0
    end: int = 0
    precision: str = 'character'

@dataclass
class Block:
    id: str
    kind: str
    text: str
    paragraph: int = 0
    locations: list[Location] = field(default_factory=list)
    rows: list[list['Block']] = field(default_factory=list)
    spans: list[list[int]] = field(default_factory=list)
    area: str = 'body'
    dynamic_fields: list[str] = field(default_factory=list)

@dataclass
class Document:
    name: str
    format: str
    sha256: str
    blocks: list[Block]
    pages: int
    warnings: list[str]
    preview: str
    coverage: dict[str, str]

@dataclass
class Change:
    id: str
    operation: str
    categories: list[str]
    before: str
    after: str
    old_locations: list[Location]
    new_locations: list[Location]
    old_paragraph: int = 0
    new_paragraph: int = 0
    source: str = 'rules'
    confidence: str = 'exact'
    details: dict[str, Any] = field(default_factory=dict)

def serialise(value):
    return asdict(value)
