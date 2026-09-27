"""Topic names carried on the control event bus."""

TOPIC_DEWATER_PERSISTED = "press.dewater.persisted"
TOPIC_PRESS_LOAD = "press.load.changed"

TOPIC_DRY_PROCEDURE = "dry.procedure.changed"
TOPIC_DRY_SPEED_SET = "dry.speed.set"
TOPIC_DRY_CURVE_SET = "dry.curve.set"

TOPIC_STEAM_DRAINED = "steam.drained"
TOPIC_STEAM_VALVE = "steam.valve.changed"
TOPIC_STEAM_BASELINE_SET = "steam.baseline.set"
TOPIC_STEAM_BASELINE_INVALIDATED = "steam.baseline.invalidated"

TOPIC_GLUE_ROLL_LIFTED = "glue.roll.lifted"
TOPIC_GLUE_PUMP_STOPPED = "glue.pump.stopped"
TOPIC_GLUE_ALARM = "glue.alarm.changed"
TOPIC_GLUE_CONC_SET = "glue.concentration.set"
TOPIC_GLUE_RECIPE = "glue.recipe.changed"
TOPIC_GLUE_RECIPE_RETIRED = "glue.recipe.retired"
TOPIC_GLUE_CHANGEOVER = "glue.changeover.changed"
TOPIC_GLUE_MAKEUP = "glue.makeup.added"

TOPIC_CAL_NIP = "cal.nip.changed"
TOPIC_CAL_SPEED = "cal.speed.changed"

TOPIC_REEL_PROCEDURE = "reel.procedure.changed"
TOPIC_REEL_SPOOL = "reel.spool.changed"

TOPIC_BROKE_PROCEDURE = "broke.procedure.changed"
TOPIC_BROKE_LATCH = "broke.latch.changed"
TOPIC_BROKE_HANDLED = "broke.handled"

TOPIC_WATER_MAP = "water.map.rebuilt"
TOPIC_WATER_PROFILE = "water.profile.changed"
TOPIC_WATER_SAMPLE = "water.sample.added"

TOPIC_SNAPSHOT = "state.snapshot"

ALL_TOPICS: tuple[str, ...] = (
    TOPIC_DEWATER_PERSISTED,
    TOPIC_PRESS_LOAD,
    TOPIC_DRY_PROCEDURE,
    TOPIC_DRY_SPEED_SET,
    TOPIC_DRY_CURVE_SET,
    TOPIC_STEAM_DRAINED,
    TOPIC_STEAM_VALVE,
    TOPIC_STEAM_BASELINE_SET,
    TOPIC_STEAM_BASELINE_INVALIDATED,
    TOPIC_GLUE_ROLL_LIFTED,
    TOPIC_GLUE_PUMP_STOPPED,
    TOPIC_GLUE_ALARM,
    TOPIC_GLUE_CONC_SET,
    TOPIC_GLUE_RECIPE,
    TOPIC_GLUE_RECIPE_RETIRED,
    TOPIC_GLUE_CHANGEOVER,
    TOPIC_GLUE_MAKEUP,
    TOPIC_CAL_NIP,
    TOPIC_CAL_SPEED,
    TOPIC_REEL_PROCEDURE,
    TOPIC_REEL_SPOOL,
    TOPIC_BROKE_PROCEDURE,
    TOPIC_BROKE_LATCH,
    TOPIC_BROKE_HANDLED,
    TOPIC_WATER_MAP,
    TOPIC_WATER_PROFILE,
    TOPIC_WATER_SAMPLE,
    TOPIC_SNAPSHOT,
)
