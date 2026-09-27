"""Size recipes, the ordered grade changeover and glue make up."""

import pytest

from paperops.errors import (
    ConcentrationDriftError,
    ConcentrationUnstableError,
    RetiredRecipeError,
    UnknownRecipeError,
)

from support import build, issue_confirmation, ok, refused


def define(console, grade, target, tolerance=0.5, factor=2.0):
    confirmation = issue_confirmation(console, "glue.recipe", "glue")
    return ok(
        console,
        "POST",
        "/api/glue/recipe",
        {
            "grade": grade,
            "target": target,
            "tolerance": tolerance,
            "makeup_factor": factor,
            "confirmation_id": confirmation,
        },
    )


def begin(console, grade):
    confirmation = issue_confirmation(console, "glue.recipe", "glue")
    return ok(
        console,
        "POST",
        "/api/glue/changeover/begin",
        {"grade": grade, "confirmation_id": confirmation},
    )


def observe(console, *readings):
    for reading in readings:
        ok(console, "POST", "/api/glue/concentration/observe", {"reading": reading})


def changeover(console, grade, readings):
    begin(console, grade)
    ok(console, "POST", "/api/glue/changeover/lift", {})
    ok(console, "POST", "/api/glue/changeover/stop", {})
    observe(console, *readings)
    return ok(console, "POST", "/api/glue/changeover/steady", {})


def test_recipe_definition_and_duplicate_refusal(console, services):
    body = define(console, "A4", 8.0)
    assert body["status"] == "active"
    assert services.glue.active_grade() == ""
    response = refused(
        console,
        "POST",
        "/api/glue/recipe",
        {
            "grade": "A4",
            "target": 9.0,
            "tolerance": 0.5,
            "makeup_factor": 2.0,
            "confirmation_id": issue_confirmation(console, "glue.recipe", "glue"),
        },
    )
    assert response.status == 400


def test_recipe_validation(console):
    for bad in (
        {"grade": "", "target": 8.0},
        {"grade": "A4", "target": 0.0},
        {"grade": "A4", "target": 8.0, "tolerance": -1.0},
        {"grade": "A4", "target": 8.0, "makeup_factor": 0.0},
    ):
        body = {"tolerance": 0.5, "makeup_factor": 2.0, **bad}
        body["confirmation_id"] = issue_confirmation(console, "glue.recipe", "glue")
        response = refused(console, "POST", "/api/glue/recipe", body)
        assert response.status == 400


def test_changeover_to_unknown_grade_is_missing(console):
    response = refused(
        console,
        "POST",
        "/api/glue/changeover/begin",
        {
            "grade": "ZZ",
            "confirmation_id": issue_confirmation(console, "glue.recipe", "glue"),
        },
    )
    assert response.status == 404


def test_changeover_runs_stages_in_order(console, services):
    define(console, "A4", 8.0)
    begin(console, "A4")
    # steady before the roll is up and the pump stopped is refused
    response = refused(console, "POST", "/api/glue/changeover/steady", {})
    assert response.status == 409
    # the pump cannot stop before the roll is lifted
    response = refused(console, "POST", "/api/glue/changeover/stop", {})
    assert response.status == 409
    assert services.glue.roll_lifted() is False
    ok(console, "POST", "/api/glue/changeover/lift", {})
    assert services.glue.roll_lifted() is True
    ok(console, "POST", "/api/glue/changeover/stop", {})
    assert services.glue.pump_running() is False
    observe(console, 7.9, 8.0, 8.1)
    body = ok(console, "POST", "/api/glue/changeover/steady", {})
    assert body["changeover"]["status"] == "complete"
    assert body["recipe"]["grade"] == "A4"
    assert services.glue.active_grade() == "A4"


def test_steady_stage_waits_for_a_stable_window(console, services):
    define(console, "A4", 8.0)
    begin(console, "A4")
    ok(console, "POST", "/api/glue/changeover/lift", {})
    ok(console, "POST", "/api/glue/changeover/stop", {})
    # fewer than a full window of in-band readings is not steady
    observe(console, 8.0, 8.0)
    response = refused(console, "POST", "/api/glue/changeover/steady", {})
    assert response.status == 409
    # a reading outside the band breaks the window
    observe(console, 6.0)
    response = refused(console, "POST", "/api/glue/changeover/steady", {})
    assert response.status == 409
    observe(console, 8.0, 8.1, 7.9)
    body = ok(console, "POST", "/api/glue/changeover/steady", {})
    assert body["changeover"]["status"] == "complete"


def test_makeup_refused_without_a_sustained_drift(console, services):
    define(console, "A4", 8.0)
    changeover(console, "A4", (8.0, 8.0, 8.0))
    # concentration sits in band, so there is nothing to make up
    response = refused(console, "POST", "/api/glue/makeup", {})
    assert response.status == 409
    with pytest.raises(ConcentrationDriftError):
        services.glue.makeup()


def test_makeup_lean_and_rich_are_recorded(console, services):
    define(console, "A4", 8.0, tolerance=0.5, factor=2.0)
    changeover(console, "A4", (8.0, 8.0, 8.0))
    # lean drift: three readings below the band
    observe(console, 6.0, 6.0, 6.0)
    lean = ok(console, "POST", "/api/glue/makeup", {})
    assert lean["verdict"] == "lean"
    assert lean["direction"] == "glue"
    assert lean["amount"] == pytest.approx((8.0 - 6.0) * 2.0)
    # rich drift: three readings above the band
    observe(console, 10.0, 10.0, 10.0)
    rich = ok(console, "POST", "/api/glue/makeup", {})
    assert rich["verdict"] == "rich"
    assert rich["direction"] == "water"
    assert rich["amount"] == pytest.approx((10.0 - 8.0) * 2.0)
    ledger = ok(console, "GET", "/api/glue/makeup")
    assert len(ledger["records"]) == 2
    assert ledger["total"] == pytest.approx(lean["amount"] + rich["amount"])
    assert services.audit.count("glue.makeup.added") == 2


def test_makeup_uses_the_recipe_in_force(console, services):
    define(console, "A4", 8.0, tolerance=0.5, factor=2.0)
    define(console, "B5", 10.0, tolerance=0.4, factor=3.0)
    changeover(console, "A4", (8.0, 8.0, 8.0))
    changeover(console, "B5", (10.0, 10.0, 10.0))
    observe(console, 9.0, 9.0, 9.0)
    body = ok(console, "POST", "/api/glue/makeup", {})
    assert body["grade"] == "B5"
    assert body["target"] == 10.0
    assert body["amount"] == pytest.approx((10.0 - 9.0) * 3.0)


def test_retired_recipe_cannot_be_reused(console, services):
    define(console, "A4", 8.0)
    define(console, "B5", 10.0, tolerance=0.4, factor=3.0)
    changeover(console, "A4", (8.0, 8.0, 8.0))
    changeover(console, "B5", (10.0, 10.0, 10.0))
    # the active recipe cannot be retired while it is in force
    response = refused(
        console,
        "POST",
        "/api/glue/recipe/retire",
        {
            "grade": "B5",
            "confirmation_id": issue_confirmation(console, "glue.recipe", "glue"),
        },
    )
    assert response.status == 409
    retired = ok(
        console,
        "POST",
        "/api/glue/recipe/retire",
        {
            "grade": "A4",
            "confirmation_id": issue_confirmation(console, "glue.recipe", "glue"),
        },
    )
    assert retired["status"] == "retired"
    # a retired recipe can never be selected again
    response = refused(
        console,
        "POST",
        "/api/glue/changeover/begin",
        {
            "grade": "A4",
            "confirmation_id": issue_confirmation(console, "glue.recipe", "glue"),
        },
    )
    assert response.status == 409
    with pytest.raises(RetiredRecipeError):
        services.glue.begin_changeover(
            "A4", issue_confirmation(console, "glue.recipe", "glue")
        )


def test_makeup_refused_mid_changeover(console, services):
    define(console, "A4", 8.0)
    define(console, "B5", 10.0, tolerance=0.4, factor=3.0)
    changeover(console, "A4", (8.0, 8.0, 8.0))
    begin(console, "B5")
    response = refused(console, "POST", "/api/glue/makeup", {})
    assert response.status == 409


def test_recipe_book_and_changeover_survive_a_restart(config):
    first = build(config)
    define(first.console, "A4", 8.0)
    define(first.console, "B5", 10.0, tolerance=0.4, factor=3.0)
    changeover(first.console, "A4", (8.0, 8.0, 8.0))
    observe(first.console, 6.0, 6.0, 6.0)
    ok(first.console, "POST", "/api/glue/makeup", {})

    second = build(config)
    state = ok(second.console, "GET", "/api/glue/state")
    assert state["active_grade"] == "A4"
    assert state["changeover"] == "complete"
    assert state["recipe_count"] == 2
    assert state["makeup_total"] == pytest.approx(4.0)
    recipe = ok(second.console, "GET", "/api/glue/recipes?grade=B5")
    assert recipe["target"] == 10.0
    assert recipe["status"] == "active"


def test_changeover_progress_survives_a_restart(config):
    first = build(config)
    define(first.console, "A4", 8.0)
    begin(first.console, "A4")
    ok(first.console, "POST", "/api/glue/changeover/lift", {})

    second = build(config)
    changeover_state = ok(second.console, "GET", "/api/glue/changeover")
    assert changeover_state["status"] == "in_progress"
    assert changeover_state["completed"] == ["lift_roll"]
    assert changeover_state["next"] == "stop_pump"
    assert changeover_state["grade"] == "A4"
    # the remaining stages still run in order after the restart
    ok(second.console, "POST", "/api/glue/changeover/stop", {})
    observe(second.console, 8.0, 8.0, 8.0)
    body = ok(second.console, "POST", "/api/glue/changeover/steady", {})
    assert body["changeover"]["status"] == "complete"


def test_changeover_adopts_recipe_band_and_generation(console, services):
    define(console, "A4", 8.0, tolerance=0.5)
    before = services.glue.generation()
    body = changeover(console, "A4", (8.0, 8.0, 8.0))
    assert body["recipe"]["generation"] == 1
    assert services.glue.generation() > before
    state = ok(console, "GET", "/api/glue/state")
    assert state["concentration"] == 8.0
    assert state["active_grade"] == "A4"
    # the concentration now answers to the recipe band
    window = ok(console, "GET", "/api/glue/concentration/window")
    assert window["band"] == {"low": 7.5, "high": 8.5}
