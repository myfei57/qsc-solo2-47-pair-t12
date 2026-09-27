"""Read model for sizing recipes and the variety switch."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RecipeView:
    active: dict[str, Any] | None
    switch: dict[str, Any]
    corrections: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "active": self.active,
            "switch": self.switch,
            "corrections": self.corrections,
        }
