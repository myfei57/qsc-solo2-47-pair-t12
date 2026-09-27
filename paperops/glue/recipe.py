"""Size recipes, one per paper grade.

A recipe fixes the concentration band a grade runs at and the factor that turns a
concentration shortfall into a glue make up. Recipes are immutable once defined;
changing a grade means retiring the old recipe and defining a new one, and a retired
recipe can never be selected again.
"""

from dataclasses import dataclass
from typing import Any, Mapping

from ..verdict import Band

ACTIVE = "active"
RETIRED = "retired"

LEAN = "lean"
RICH = "rich"
IN_BAND = "in_band"


@dataclass(frozen=True)
class Recipe:
    """The size recipe for one grade."""

    grade: str
    target: float
    tolerance: float
    makeup_factor: float
    status: str = ACTIVE

    @property
    def band(self) -> Band:
        return Band(self.target - self.tolerance, self.target + self.tolerance)

    def is_active(self) -> bool:
        return self.status == ACTIVE

    def to_row(self) -> dict[str, Any]:
        return {
            "grade": self.grade,
            "target": float(self.target),
            "tolerance": float(self.tolerance),
            "makeup_factor": float(self.makeup_factor),
            "status": self.status,
        }

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "Recipe":
        return cls(
            grade=str(row["grade"]),
            target=float(row["target"]),
            tolerance=float(row["tolerance"]),
            makeup_factor=float(row["makeup_factor"]),
            status=str(row.get("status", ACTIVE)),
        )


def validate(grade: str, target: float, tolerance: float, makeup_factor: float) -> Recipe:
    """Build a recipe, refusing blank grades and nonsensical control parameters."""
    text = str(grade).strip()
    if not text:
        raise ValueError("a recipe needs a grade name")
    if target <= 0:
        raise ValueError("recipe target concentration must be positive")
    if tolerance < 0:
        raise ValueError("recipe tolerance must not be negative")
    if makeup_factor <= 0:
        raise ValueError("recipe make up factor must be positive")
    return Recipe(text, float(target), float(tolerance), float(makeup_factor))
