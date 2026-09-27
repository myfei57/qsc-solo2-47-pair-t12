"""A sizing recipe: the concentration setpoint published for one variety."""

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class Recipe:
    """A variety's concentration setpoint pinned to the generation that issued it."""

    variety: str
    concentration: float
    tolerance: float
    generation: int
    tick: int

    @property
    def low(self) -> float:
        return self.concentration - self.tolerance

    @property
    def high(self) -> float:
        return self.concentration + self.tolerance

    def contains(self, reading: float) -> bool:
        return self.low <= reading <= self.high

    def to_row(self) -> dict[str, Any]:
        return {
            "variety": self.variety,
            "concentration": self.concentration,
            "tolerance": self.tolerance,
            "generation": self.generation,
            "tick": self.tick,
        }

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "Recipe":
        return cls(
            variety=str(row["variety"]),
            concentration=float(row["concentration"]),
            tolerance=float(row["tolerance"]),
            generation=int(row["generation"]),
            tick=int(row["tick"]),
        )
