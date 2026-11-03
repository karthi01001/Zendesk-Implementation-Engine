"""Readers turn Zendesk configuration areas into raw items the engine can store and show."""

from zie.readers.areas import AREAS, AREAS_BY_KEY, SECTIONS, AreaInfo, AreaSpec, read_area
from zie.readers.groups import Group, read_groups

__all__ = [
    "AREAS",
    "AREAS_BY_KEY",
    "SECTIONS",
    "AreaInfo",
    "AreaSpec",
    "Group",
    "read_area",
    "read_groups",
]
