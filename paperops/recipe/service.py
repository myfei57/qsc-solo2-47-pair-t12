"""Variety recipes for the size press.

Every variety carries its own concentration setpoint as a versioned recipe. A
variety change is an ordered procedure — the sizing roll is lifted, the glue
pump is stopped, and the concentration has to settle inside the recipe band —
and no stage may be skipped. A reading that leaves the band of the recipe in
force is corrected back to the setpoint, and every correction is journaled with
the amount added. Publishing a new recipe advances the variety's generation, so
a superseded recipe can neither be switched to nor serve a correction.
"""

from typing import Any

from ..clock import LogicalClock
from ..errors import PreGateError, UnknownRecipeError
from ..event import EventBus, topics
from ..glue.service import CONC_BAND, CONC_NAME, GLUE_NAME, GlueService
from ..interlock import StageSequence
from ..store import Journal, keys
from ..verdict import Band
from ..version import Confirmations, Generations
from . import calc
from .recipe import Recipe
from .view import RecipeView

RECIPE_SUBJECT = "recipe"
PROCEDURE_NAME = "recipe.switch"
STAGES = ("lift_roll", "stop_pump", "stabilize")
DEFAULT_VOLUME = 1000.0
DEFAULT_STOCK = 20.0


def recipe_name(variety: str) -> str:
    """Generation and confirmation name of one variety's recipe line."""
    return f"recipe.{variety}"


class RecipeService:
    """Versioned variety recipes, the ordered switch and drift correction."""

    def __init__(
        self,
        journal: Journal,
        bus: EventBus,
        clock: LogicalClock,
        generations: Generations,
        confirmations: Confirmations,
        glue: GlueService,
    ) -> None:
        self._journal = journal
        self._bus = bus
        self._clock = clock
        self._generations = generations
        self._confirmations = confirmations
        self._glue = glue
        self._procedure = StageSequence(PROCEDURE_NAME, STAGES)
        self._pending: Recipe | None = None
        self._active: Recipe | None = None

    # ----------------------------------------------------------------- reading

    def recipe(self, variety: str) -> Recipe | None:
        row = self._journal.read(keys.recipe_key(variety))
        if row is None:
            return None
        return Recipe.from_row(row)

    def recipes(self) -> tuple[Recipe, ...]:
        return tuple(
            Recipe.from_row(self._journal.read(key))
            for key in self._journal.keys(keys.RECIPE_PREFIX)
        )

    def active(self) -> Recipe | None:
        return self._active

    def switch_state(self) -> dict[str, Any]:
        state = self._procedure.state()
        state["variety"] = self._pending.variety if self._pending is not None else None
        state["generation"] = self._pending.generation if self._pending is not None else 0
        return state

    def corrections(self) -> tuple[dict[str, Any], ...]:
        """Every correction ever journaled, in the order it was applied."""
        return tuple(
            dict(self._journal.read(key))
            for key in self._journal.keys(keys.RECIPE_CORRECTION_PREFIX)
        )

    def view(self) -> RecipeView:
        return RecipeView(
            active=self._active.to_row() if self._active is not None else None,
            switch=self.switch_state(),
            corrections=len(self._journal.keys(keys.RECIPE_CORRECTION_PREFIX)),
        )

    # ------------------------------------------------------------------ writes

    def publish(
        self,
        variety: str,
        concentration: float,
        tolerance: float,
        confirmation_id: str,
    ) -> dict[str, Any]:
        """Issue the next recipe generation for a variety under a confirmation."""
        if not str(variety).strip():
            raise ValueError("a recipe needs a variety")
        if tolerance < 0:
            raise ValueError("tolerance must not be negative")
        CONC_BAND.require(concentration, "recipe concentration")
        name = recipe_name(variety)
        self._confirmations.redeem(confirmation_id, name, RECIPE_SUBJECT)
        generation = self._generations.advance(name, "recipe-generation")
        recipe = Recipe(
            variety=str(variety),
            concentration=float(concentration),
            tolerance=float(tolerance),
            generation=generation,
            tick=self._clock.tick,
        )
        with self._journal.transaction("recipe-publish") as batch:
            self._journal.append(
                keys.recipe_key(recipe.variety), recipe.to_row(), batch, generation=generation
            )
        self._bus.publish(topics.TOPIC_RECIPE_PUBLISHED, recipe.to_row())
        return recipe.to_row()

    def begin_switch(self, variety: str, generation: int | None = None) -> dict[str, Any]:
        """Open a variety switch pinned to the variety's current recipe."""
        recipe = self.recipe(variety)
        if recipe is None:
            raise UnknownRecipeError(f"no recipe published for variety {variety}")
        if generation is not None:
            self._generations.require_current(
                recipe_name(variety), int(generation), f"recipe {variety}"
            )
        self._procedure.reset()
        self._pending = recipe
        return self._record_switch("recipe-switch-begin")

    def switch_lift(self) -> dict[str, Any]:
        """Lift the sizing roll as the first stage of the open switch."""
        self._require_pending()
        self._procedure.advance("lift_roll")
        self._glue.lift_roll()
        return self._record_switch("recipe-switch-lift")

    def switch_stop(self) -> dict[str, Any]:
        """Stop the glue pump; the roll has to be lifted and the stage open."""
        self._require_pending()
        if not self._glue.roll_lifted():
            raise PreGateError("recipe: the sizing roll is not lifted")
        self._procedure.advance("stop_pump")
        self._glue.stop_pump()
        return self._record_switch("recipe-switch-stop")

    def switch_stabilize(self, reading: float, confirmation_id: str) -> dict[str, Any]:
        """Close the switch once the concentration sits inside the recipe band."""
        recipe = self._require_pending()
        self._generations.require_current(
            recipe_name(recipe.variety), recipe.generation, f"recipe {recipe.variety}"
        )
        # Pure checks only up to this point; the stage closes before anything moves.
        self._confirmations.redeem(confirmation_id, CONC_NAME, GLUE_NAME)
        Band(recipe.low, recipe.high).require(reading, "glue concentration")
        self._procedure.advance("stabilize")
        self._glue.set_concentration(recipe.concentration, confirmation_id)
        self._active = recipe
        self._pending = None
        tick = self._clock.tick
        with self._journal.transaction("recipe-active") as batch:
            self._journal.append(
                keys.RECIPE_ACTIVE, recipe.to_row(), batch, generation=recipe.generation
            )
        return self._record_switch("recipe-switch-stabilize")

    def correct(
        self,
        reading: float,
        volume: float = DEFAULT_VOLUME,
        stock: float = DEFAULT_STOCK,
    ) -> dict[str, Any]:
        """Pull a drifting reading back to the recipe in force and journal the amount."""
        recipe = self._pending if self._pending is not None else self._active
        if recipe is None:
            raise PreGateError("recipe: no variety switch is open and no recipe is in force")
        self._generations.require_current(
            recipe_name(recipe.variety), recipe.generation, f"recipe {recipe.variety}"
        )
        result = calc.correction(
            reading, recipe.concentration, recipe.tolerance, volume, stock
        )
        if result["kind"] == calc.IN_BAND:
            return {
                "corrected": False,
                "kind": calc.IN_BAND,
                "variety": recipe.variety,
                "generation": recipe.generation,
                "reading": float(reading),
                "target": recipe.concentration,
            }
        seq = len(self._journal.keys(keys.RECIPE_CORRECTION_PREFIX)) + 1
        row = {
            "seq": seq,
            "variety": recipe.variety,
            "generation": recipe.generation,
            "reading": float(reading),
            "target": recipe.concentration,
            "kind": result["kind"],
            "amount": result["amount"],
            "volume": float(volume),
            "stock": float(stock),
            "tick": self._clock.tick,
        }
        with self._journal.transaction("recipe-correct") as batch:
            self._journal.append(
                keys.recipe_correction_key(seq), row, batch, generation=recipe.generation
            )
        self._bus.publish(topics.TOPIC_RECIPE_CORRECTED, dict(row))
        return {**row, "corrected": True}

    def reload(self) -> RecipeView:
        """Restore the active recipe and any open switch from the committed stream."""
        active = self._journal.read(keys.RECIPE_ACTIVE)
        self._active = Recipe.from_row(active) if active is not None else None
        switch = self._journal.read(keys.RECIPE_SWITCH)
        self._pending = None
        self._procedure.reset()
        if switch is not None:
            for stage in switch.get("completed", []):
                self._procedure.advance(str(stage))
            pinned = switch.get("recipe")
            if pinned is not None:
                self._pending = Recipe.from_row(pinned)
        return self.view()

    # ---------------------------------------------------------------- internals

    def _require_pending(self) -> Recipe:
        if self._pending is None:
            raise PreGateError("recipe.switch is not open; begin a variety switch first")
        return self._pending

    def _record_switch(self, prefix: str) -> dict[str, Any]:
        state = self.switch_state()
        row = {
            "completed": list(self._procedure.completed()),
            "next": state["next"],
            "recipe": self._pending.to_row() if self._pending is not None else None,
            "tick": self._clock.tick,
        }
        with self._journal.transaction(prefix) as batch:
            self._journal.append(keys.RECIPE_SWITCH, row, batch)
        self._bus.publish(topics.TOPIC_RECIPE_SWITCH, state["next"])
        return state
