from dataclasses import dataclass
from typing import Set

@dataclass
class DictionaryEntry:
    id: int
    written_form: str
    reading: str
    senses: list
    tags: Set[str]
    frequency_tags: Set[str]
    deconjugation_process: tuple
    priority: float = 0.0
    match_len: int = 0
