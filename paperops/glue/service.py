"""Size press control.

The sizing roll has to be lifted before the glue pump may be stopped, and the
concentration alarm only latches once the roll is clear and the pump is stopped. A
new concentration carries a generation, so a verdict built on a superseded band is
refused until a fresh value lands.

Each paper grade runs to a size :class:`~paperops.glue.recipe.Recipe` that fixes the
concentration band and the make up factor. Switching grade runs an ordered
changeover -- lift the roll, stop the pump, hold the concentration steady -- and only
then is the new recipe adopted under a fresh generation. A retired recipe can never be
selected again. When the concentration drifts out of band for a full window it is made
up against the active recipe, and every dose is written to the make up ledger.
"""

from typing import Any

from ..clock import LogicalClock
from ..errors import (
    ConcentrationDriftError,
    ConcentrationUnstableError,
    PreGateError,
    RetiredRecipeError,
    UnknownRecipeError,
)
from ..event import Event, EventBus, topics
from ..interlock import Latch, PreGate, StageSequence
from ..store import Journal, keys
from ..verdict import Band, VerdictHistory, Window
from ..version import Confirmations, Generations
from . import calc
from .recipe import IN_BAND, Recipe, validate
from .view import GlueView

CONC_NAME = "glue.concentration"
RECIPE_NAME = "glue.recipe"
GLUE_NAME = "glue"
CONC_BAND = Band(4.0, 14.0)
TOLERANCE = 1.0
STAGES = ("lift_roll", "stop_pump", "steady")
STABILITY_WINDOW = 3
LEDGER_LIMIT = 200


class GlueService:
    """Sizing roll, glue pump, concentration band, recipes and alarm latch."""

    def __init__(
        self,
        journal: Journal,
        bus: EventBus,
        clock: LogicalClock,
        generations: Generations,
        confirmations: Confirmations,
    ) -> None:
        self._journal = journal
        self._bus = bus
        self._clock = clock
        self._generations = generations
        self._confirmations = confirmations
        self._band = CONC_BAND
        self._tolerance = TOLERANCE
        self._roll_gate = PreGate("glue.stop", journal, keys.GLUE_ROLL)
        self._latch = Latch(
            "glue.concentration",
            set_conditions=("roll_lifted", "pump_stopped"),
            clear_conditions=("roll_lifted",),
        )
        self._history = VerdictHistory("glue.concentration")
        self._procedure = StageSequence("glue.changeover", STAGES)
        self._readings = Window(STABILITY_WINDOW)
        self._roll_lifted = False
        self._pump_running = False
        self._conc_cache: dict[float, str] = {}
        self._recipes: dict[str, Recipe] = {}
        self._active_grade = ""
        self._pending_grade = ""

    # ----------------------------------------------------------------- reading

    def roll_lifted(self) -> bool:
        return self._roll_lifted

    def pump_running(self) -> bool:
        return self._pump_running

    def alarm(self) -> bool:
        return self._latch.is_set

    def concentration(self) -> float:
        row = self._journal.read(keys.GLUE_CONC)
        if row is None:
            return 0.0
        return float(row["value"])

    def generation(self) -> int:
        row = self._journal.read(keys.GLUE_CONC)
        if row is None:
            return 0
        return int(row["generation"])

    def history(self) -> VerdictHistory:
        return self._history

    def verdict_of(self, reading: float) -> str:
        result = calc.concentration_verdict(reading, self._band.low, self._band.high)
        self._history.record(
            result,
            self._journal.watermark,
            self._clock.tick,
            f"reading={reading}",
        )
        return result

    def cached_verdict(self, reading: float) -> str:
        """Verdict memoised per reading; the cache is dropped when the band moves."""
        key = float(reading)
        hit = self._conc_cache.get(key)
        if hit is None:
            hit = calc.concentration_verdict(key, self._band.low, self._band.high)
            self._conc_cache[key] = hit
        return hit

    def alarm_required(self, reading: float) -> bool:
        return calc.alarm_required(
            reading, self._band.low, self._band.high, self._tolerance
        )

    # ------------------------------------------------------------ recipe reads

    def recipes(self) -> tuple[dict[str, Any], ...]:
        return tuple(recipe.to_row() for recipe in self._recipes.values())

    def recipe(self, grade: str) -> Recipe:
        recipe = self._recipes.get(str(grade))
        if recipe is None:
            raise UnknownRecipeError(f"no size recipe for grade {grade}")
        return recipe

    def active_recipe(self) -> Recipe | None:
        if not self._active_grade:
            return None
        return self._recipes.get(self._active_grade)

    def active_grade(self) -> str:
        return self._active_grade

    def changeover(self) -> dict[str, Any]:
        state = dict(self._procedure.state())
        state["grade"] = self._pending_grade or self._active_grade
        state["status"] = self._changeover_status()
        return state

    def stable(self) -> bool:
        return calc.is_stable(
            self._readings.values(), self._band.low, self._band.high, STABILITY_WINDOW
        )

    def concentration_state(self, reading: float | None = None) -> dict[str, Any]:
        """Classify the observation window against the band currently in force."""
        values = self._readings.values()
        verdict = calc.stability_verdict(values, self._band.low, self._band.high)
        return {
            "reading": self.concentration() if reading is None else float(reading),
            "verdict": verdict,
            "stable": self.stable(),
            "samples": len(values),
            "required": STABILITY_WINDOW,
            "band": {"low": self._band.low, "high": self._band.high},
        }

    def makeup_history(self) -> tuple[dict[str, Any], ...]:
        rows = self._journal.read(keys.GLUE_MAKEUP)
        return () if rows is None else tuple(rows)

    def makeup_total(self) -> float:
        return round(sum(float(row["amount"]) for row in self.makeup_history()), 6)

    def view(self) -> GlueView:
        changeover = self.changeover()
        return GlueView(
            roll_lifted=self._roll_lifted,
            pump_running=self._pump_running,
            alarm=self.alarm(),
            concentration=self.concentration(),
            verdict=calc.concentration_verdict(
                self.concentration(), self._band.low, self._band.high
            ),
            generation=self.generation(),
            active_grade=self._active_grade,
            changeover=changeover["status"],
            next_stage=changeover["next"] if changeover["status"] == "in_progress" else "",
            recipe_count=len(self._recipes),
            stable=self.stable(),
            makeup_total=self.makeup_total(),
        )

    # ------------------------------------------------------------------ writes

    def lift_roll(self) -> dict[str, Any]:
        tick = self._clock.tick
        with self._journal.transaction("glue-roll") as batch:
            self._journal.append(keys.GLUE_ROLL, {"lifted": True, "tick": tick}, batch)
        self._roll_lifted = True
        self._bus.publish(topics.TOPIC_GLUE_ROLL_LIFTED, tick)
        return {"roll_lifted": True, "tick": tick}

    def lower_roll(self) -> dict[str, Any]:
        tick = self._clock.tick
        with self._journal.transaction("glue-roll") as batch:
            self._journal.append(keys.GLUE_ROLL, {"lifted": False, "tick": tick}, batch)
        self._roll_lifted = False
        return {"roll_lifted": False, "tick": tick}

    def stop_pump(self) -> dict[str, Any]:
        """Stop the glue pump; the sizing roll has to be lifted first."""
        self._roll_gate.require()
        if not self._roll_lifted:
            raise PreGateError("glue: the sizing roll is not lifted")
        tick = self._clock.tick
        with self._journal.transaction("glue-pump") as batch:
            self._journal.append(keys.GLUE_PUMP, {"running": False, "tick": tick}, batch)
        self._pump_running = False
        self._bus.publish(topics.TOPIC_GLUE_PUMP_STOPPED, tick)
        return {"running": False, "tick": tick}

    def start_pump(self) -> dict[str, Any]:
        tick = self._clock.tick
        with self._journal.transaction("glue-pump") as batch:
            self._journal.append(keys.GLUE_PUMP, {"running": True, "tick": tick}, batch)
        self._pump_running = True
        return {"running": True, "tick": tick}

    def set_alarm(self) -> dict[str, Any]:
        """Latch the concentration alarm once the roll is clear and the pump stopped."""
        self._latch.set(
            {
                "roll_lifted": self._roll_lifted,
                "pump_stopped": not self._pump_running,
            }
        )
        tick = self._clock.tick
        with self._journal.transaction("glue-alarm") as batch:
            self._journal.append(keys.GLUE_ALARM, {"alarm": True, "tick": tick}, batch)
        self._bus.publish(topics.TOPIC_GLUE_ALARM, True)
        return {"alarm": True, "tick": tick}

    def clear_alarm(self) -> dict[str, Any]:
        """Clear the concentration alarm; the roll still has to be clear."""
        self._latch.clear({"roll_lifted": self._roll_lifted})
        tick = self._clock.tick
        with self._journal.transaction("glue-alarm") as batch:
            self._journal.append(keys.GLUE_ALARM, {"alarm": False, "tick": tick}, batch)
        self._bus.publish(topics.TOPIC_GLUE_ALARM, False)
        return {"alarm": False, "tick": tick}

    def set_concentration(self, value: float, confirmation_id: str) -> dict[str, Any]:
        """Adopt a new concentration under a confirmation and a new generation."""
        self._band.require(value, "glue concentration")
        self._confirmations.redeem(confirmation_id, CONC_NAME, GLUE_NAME)
        generation = self._generations.advance(CONC_NAME, "glue-conc-generation")
        tick = self._clock.tick
        row = {"value": float(value), "generation": generation, "tick": tick}
        with self._journal.transaction("glue-conc") as batch:
            self._journal.append(keys.GLUE_CONC, row, batch, generation=generation)
        self._bus.publish(topics.TOPIC_GLUE_CONC_SET, generation)
        return dict(row)

    # ------------------------------------------------------------- recipe book

    def define_recipe(
        self,
        grade: str,
        target: float,
        tolerance: float,
        makeup_factor: float,
        confirmation_id: str,
    ) -> dict[str, Any]:
        """Register a size recipe for a grade under a confirmation."""
        recipe = validate(grade, target, tolerance, makeup_factor)
        if recipe.grade in self._recipes:
            raise ValueError(f"grade {recipe.grade} already has a size recipe")
        self._confirmations.redeem(confirmation_id, RECIPE_NAME, GLUE_NAME)
        self._recipes[recipe.grade] = recipe
        self._persist_recipes()
        self._bus.publish(topics.TOPIC_GLUE_RECIPE, recipe.to_row())
        return recipe.to_row()

    def retire_recipe(self, grade: str, confirmation_id: str) -> dict[str, Any]:
        """Retire a recipe so it can never be selected or made up against again."""
        recipe = self.recipe(grade)
        if not recipe.is_active():
            raise RetiredRecipeError(f"recipe for {grade} is already retired")
        if grade == self._active_grade:
            raise RetiredRecipeError(
                f"recipe for {grade} is in force; change over before retiring it"
            )
        self._confirmations.redeem(confirmation_id, RECIPE_NAME, GLUE_NAME)
        recipe = Recipe(
            recipe.grade,
            recipe.target,
            recipe.tolerance,
            recipe.makeup_factor,
            status="retired",
        )
        self._recipes[grade] = recipe
        self._persist_recipes()
        self._bus.publish(topics.TOPIC_GLUE_RECIPE_RETIRED, recipe.to_row())
        return recipe.to_row()

    # ------------------------------------------------------------- changeover

    def begin_changeover(self, grade: str, confirmation_id: str) -> dict[str, Any]:
        """Open an ordered changeover to an active recipe for a grade."""
        recipe = self.recipe(grade)
        if not recipe.is_active():
            raise RetiredRecipeError(f"recipe for {grade} is retired and cannot be used")
        self._confirmations.redeem(confirmation_id, RECIPE_NAME, GLUE_NAME)
        self._procedure.reset()
        self._pending_grade = grade
        self._readings.clear()
        return self._record_changeover("glue-changeover-begin")

    def changeover_lift(self) -> dict[str, Any]:
        """Close the lift stage: raise the sizing roll first."""
        self._procedure.advance("lift_roll")
        self.lift_roll()
        return self._record_changeover("glue-changeover-lift")

    def changeover_stop(self) -> dict[str, Any]:
        """Close the stop stage: the pump only stops once the roll is up."""
        self.stop_pump()
        self._procedure.advance("stop_pump")
        return self._record_changeover("glue-changeover-stop")

    def changeover_steady(self) -> dict[str, Any]:
        """Close the steady stage and adopt the recipe once the band holds."""
        recipe = self.recipe(self._pending_grade)
        band = recipe.band
        if not calc.is_stable(
            self._readings.values(), band.low, band.high, STABILITY_WINDOW
        ):
            raise ConcentrationUnstableError(
                f"glue concentration is not steady within "
                f"[{band.low}, {band.high}] for {STABILITY_WINDOW} readings"
            )
        self._procedure.advance("steady")
        row = self._adopt_recipe(recipe)
        self._pending_grade = ""
        self._readings.clear()
        state = self._record_changeover("glue-changeover-steady")
        return {"recipe": row, "changeover": state}

    def observe_concentration(self, reading: float) -> dict[str, Any]:
        """Feed a concentration observation; a full in-band window is steady."""
        self._readings.push(float(reading))
        state = self.concentration_state(float(reading))
        state["tick"] = self._clock.tick
        return state

    # ----------------------------------------------------------- glue make up

    def makeup(self) -> dict[str, Any]:
        """Make up glue against the active recipe after a sustained drift."""
        if self._changeover_status() == "in_progress":
            raise PreGateError("glue: finish the grade changeover before making up glue")
        recipe = self.active_recipe()
        if recipe is None:
            raise UnknownRecipeError("no size recipe is in force")
        values = self._readings.values()
        verdict = calc.stability_verdict(values, recipe.band.low, recipe.band.high)
        if verdict == IN_BAND:
            raise ConcentrationDriftError(
                "concentration has not drifted out of band for a full window"
            )
        reading = round(sum(values) / len(values), 6)
        amount = calc.makeup_amount(
            verdict, reading, recipe.target, recipe.makeup_factor
        )
        generation = self._generations.current(RECIPE_NAME)
        tick = self._clock.tick
        row = {
            "grade": recipe.grade,
            "generation": generation,
            "verdict": verdict,
            "reading": reading,
            "target": recipe.target,
            "amount": amount,
            "direction": "glue" if verdict == "lean" else "water",
            "tick": tick,
        }
        ledger = list(self.makeup_history())
        ledger.append(row)
        with self._journal.transaction("glue-makeup") as batch:
            self._journal.append(keys.GLUE_MAKEUP, ledger[-LEDGER_LIMIT:], batch)
        self._readings.clear()
        self._bus.publish(topics.TOPIC_GLUE_MAKEUP, row)
        return dict(row)

    def reload(self) -> GlueView:
        roll = self._journal.read(keys.GLUE_ROLL)
        if roll is not None:
            self._roll_lifted = bool(roll["lifted"])
        pump = self._journal.read(keys.GLUE_PUMP)
        if pump is not None:
            self._pump_running = bool(pump["running"])
        alarm = self._journal.read(keys.GLUE_ALARM)
        if alarm is not None:
            self._latch.restore(bool(alarm["alarm"]))
        stored_recipes = self._journal.read(keys.GLUE_RECIPES)
        if stored_recipes is not None:
            self._recipes = {
                str(row["grade"]): Recipe.from_row(row) for row in stored_recipes
            }
        active = self._journal.read(keys.GLUE_ACTIVE_RECIPE)
        if active is not None:
            self._active_grade = str(active["grade"])
            recipe = self._recipes.get(self._active_grade)
            if recipe is not None:
                self._band = recipe.band
                self._tolerance = recipe.tolerance
        changeover = self._journal.read(keys.GLUE_CHANGEOVER)
        if changeover is not None:
            self._procedure.reset()
            for stage in changeover.get("completed", []):
                self._procedure.advance(str(stage))
            self._pending_grade = (
                str(changeover["grade"])
                if changeover.get("status") == "in_progress"
                else ""
            )
        return self.view()

    def wire(self) -> None:
        """Drop the verdict cache whenever the concentration band moves."""
        self._bus.subscribe(topics.TOPIC_GLUE_CONC_SET, self._on_band_change)

    # -------------------------------------------------------------- arithmetic

    def pick_up(self, roll_speed: float, stock_speed: float) -> float:
        return calc.pick_up(roll_speed, stock_speed)

    def dose(self, flow: float, width: float, speed: float) -> float:
        return calc.dose(flow, width, speed)

    def diluted(self, concentration: float, water: float) -> float:
        return calc.diluted(concentration, water)

    # ---------------------------------------------------------------- internals

    def _persist_recipes(self) -> None:
        rows = [recipe.to_row() for recipe in self._recipes.values()]
        with self._journal.transaction("glue-recipe") as batch:
            self._journal.append(keys.GLUE_RECIPES, rows, batch)

    def _adopt_recipe(self, recipe: Recipe) -> dict[str, Any]:
        """Bring a recipe into force under fresh recipe and concentration generations."""
        recipe_generation = self._generations.advance(RECIPE_NAME, "glue-recipe-generation")
        conc_generation = self._generations.advance(CONC_NAME, "glue-conc-generation")
        tick = self._clock.tick
        active_row = {
            "grade": recipe.grade,
            "target": recipe.target,
            "tolerance": recipe.tolerance,
            "generation": recipe_generation,
            "tick": tick,
        }
        conc_row = {
            "value": recipe.target,
            "generation": conc_generation,
            "tick": tick,
        }
        with self._journal.transaction("glue-recipe-adopt") as batch:
            self._journal.append(
                keys.GLUE_ACTIVE_RECIPE, active_row, batch, generation=recipe_generation
            )
            self._journal.append(
                keys.GLUE_CONC, conc_row, batch, generation=conc_generation
            )
        self._active_grade = recipe.grade
        self._band = recipe.band
        self._tolerance = recipe.tolerance
        self._bus.publish(topics.TOPIC_GLUE_RECIPE, active_row)
        self._bus.publish(topics.TOPIC_GLUE_CONC_SET, conc_generation)
        return dict(active_row)

    def _record_changeover(self, prefix: str) -> dict[str, Any]:
        state = self.changeover()
        state["tick"] = self._clock.tick
        with self._journal.transaction(prefix) as batch:
            self._journal.append(keys.GLUE_CHANGEOVER, state, batch)
        self._bus.publish(topics.TOPIC_GLUE_CHANGEOVER, state["next"])
        return state

    def _changeover_status(self) -> str:
        if self._pending_grade:
            return "in_progress"
        if self._procedure.completed() and self._procedure.next_required() is None:
            return "complete"
        return "idle"

    def _on_band_change(self, event: Event) -> None:
        self._conc_cache = {}
