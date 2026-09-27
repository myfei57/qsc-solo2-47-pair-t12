"""Read model for the size press."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class GlueView:
    roll_lifted: bool
    pump_running: bool
    alarm: bool
    concentration: float
    verdict: str
    generation: int
    active_grade: str = ""
    changeover: str = "idle"
    next_stage: str = ""
    recipe_count: int = 0
    stable: bool = False
    makeup_total: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "roll_lifted": self.roll_lifted,
            "pump_running": self.pump_running,
            "alarm": self.alarm,
            "concentration": self.concentration,
            "verdict": self.verdict,
            "generation": self.generation,
            "active_grade": self.active_grade,
            "changeover": self.changeover,
            "next_stage": self.next_stage,
            "recipe_count": self.recipe_count,
            "stable": self.stable,
            "makeup_total": self.makeup_total,
        }
