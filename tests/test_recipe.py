"""Variety recipes: the ordered switch, drift correction and recipe generations."""

import pytest

from paperops.errors import PreGateError, StaleArtifactError

from support import build, issue_confirmation, ok, refused


def publish(console, variety, concentration, tolerance=1.0):
    return ok(
        console,
        "POST",
        "/api/recipe/publish",
        {
            "variety": variety,
            "concentration": concentration,
            "tolerance": tolerance,
            "confirmation_id": issue_confirmation(console, f"recipe.{variety}", "recipe"),
        },
    )


def begin(console, variety):
    return ok(console, "POST", "/api/recipe/begin", {"variety": variety})


def stabilize(console, reading):
    return ok(
        console,
        "POST",
        "/api/recipe/stabilize",
        {
            "reading": reading,
            "confirmation_id": issue_confirmation(console, "glue.concentration", "glue"),
        },
    )


def run_switch(console, variety, reading):
    begin(console, variety)
    ok(console, "POST", "/api/recipe/lift", {})
    ok(console, "POST", "/api/recipe/stop", {})
    return stabilize(console, reading)


def test_switch_runs_the_stages_in_order(console, services):
    publish(console, "K-200", 8.0)
    assert begin(console, "K-200")["next"] == "lift_roll"
    assert refused(console, "POST", "/api/recipe/stop", {}).status == 409
    out_of_turn = {
        "reading": 8.0,
        "confirmation_id": issue_confirmation(console, "glue.concentration", "glue"),
    }
    assert refused(console, "POST", "/api/recipe/stabilize", out_of_turn).status == 409
    assert ok(console, "POST", "/api/recipe/lift", {})["next"] == "stop_pump"
    assert refused(console, "POST", "/api/recipe/lift", {}).status == 409
    assert ok(console, "POST", "/api/recipe/stop", {})["next"] == "stabilize"
    state = stabilize(console, 8.2)
    assert state["next"] == "complete"
    assert state["variety"] is None
    assert services.glue.roll_lifted() is True
    assert services.glue.pump_running() is False
    assert services.glue.concentration() == 8.0
    active = ok(console, "GET", "/api/recipe/state")["active"]
    assert active["variety"] == "K-200"
    assert active["generation"] == 1


def test_stabilize_needs_the_reading_inside_the_recipe_band(console, services):
    publish(console, "K-200", 8.0)
    begin(console, "K-200")
    ok(console, "POST", "/api/recipe/lift", {})
    ok(console, "POST", "/api/recipe/stop", {})
    response = refused(
        console,
        "POST",
        "/api/recipe/stabilize",
        {
            "reading": 9.5,
            "confirmation_id": issue_confirmation(console, "glue.concentration", "glue"),
        },
    )
    assert response.status == 422
    assert services.recipe.switch_state()["next"] == "stabilize"
    # The pending recipe already serves corrections while the switch is open.
    row = ok(console, "POST", "/api/recipe/correct", {"reading": 9.5, "volume": 1000})
    assert row["kind"] == "dilute"
    assert row["amount"] == 187.5
    assert stabilize(console, 8.1)["next"] == "complete"


def test_correction_is_journaled_with_the_amount(console, services):
    publish(console, "K-200", 8.0)
    run_switch(console, "K-200", 8.2)
    rich = ok(console, "POST", "/api/recipe/correct", {"reading": 9.5, "volume": 1000})
    assert rich["corrected"] is True
    assert rich["kind"] == "dilute"
    assert rich["amount"] == 187.5
    lean = ok(console, "POST", "/api/recipe/correct", {"reading": 6.4, "volume": 1000})
    assert lean["kind"] == "enrich"
    assert round(lean["amount"], 4) == 133.3333
    settled = ok(console, "POST", "/api/recipe/correct", {"reading": 8.4})
    assert settled["corrected"] is False
    state = ok(console, "GET", "/api/recipe/state")
    assert state["corrections"] == 2
    assert [row["amount"] for row in state["corrections_log"]] == [187.5, lean["amount"]]
    audit = ok(console, "GET", "/api/audit?topic=recipe.corrected")
    assert audit["count"] == 2
    # Newest first: the lean correction was journaled after the rich one.
    assert audit["records"][1]["payload"]["amount"] == 187.5
    assert audit["records"][0]["payload"]["amount"] == lean["amount"]


def test_a_superseded_recipe_cannot_be_used(console, services):
    publish(console, "K-200", 8.0)
    run_switch(console, "K-200", 8.2)
    publish(console, "K-200", 9.0)
    # A switch may not be opened on the old generation.
    response = refused(console, "POST", "/api/recipe/begin", {"variety": "K-200", "generation": 1})
    assert response.status == 409
    # The old recipe no longer serves corrections either.
    assert refused(console, "POST", "/api/recipe/correct", {"reading": 9.5}).status == 409
    with pytest.raises(StaleArtifactError):
        services.recipe.correct(9.5)
    # Switching to the current recipe releases corrections again.
    run_switch(console, "K-200", 9.2)
    row = ok(console, "POST", "/api/recipe/correct", {"reading": 9.3})
    assert row["corrected"] is False
    assert services.recipe.active().generation == 2


def test_a_switch_pinned_to_a_superseded_recipe_cannot_close(console, services):
    publish(console, "K-200", 8.0)
    begin(console, "K-200")
    publish(console, "K-200", 9.0)
    ok(console, "POST", "/api/recipe/lift", {})
    ok(console, "POST", "/api/recipe/stop", {})
    response = refused(
        console,
        "POST",
        "/api/recipe/stabilize",
        {
            "reading": 8.2,
            "confirmation_id": issue_confirmation(console, "glue.concentration", "glue"),
        },
    )
    assert response.status == 409
    with pytest.raises(StaleArtifactError):
        services.recipe.switch_stabilize(8.2, "cfm-000001")
    run_switch(console, "K-200", 9.2)
    assert services.recipe.active().concentration == 9.0


def test_unknown_variety_and_missing_switch_are_refused(console, services):
    assert refused(console, "POST", "/api/recipe/begin", {"variety": "X-1"}).status == 404
    assert refused(console, "POST", "/api/recipe/lift", {}).status == 409
    assert refused(console, "POST", "/api/recipe/correct", {"reading": 8.0}).status == 409
    with pytest.raises(PreGateError):
        services.recipe.correct(8.0)


def test_publish_validates_the_recipe(console):
    response = refused(console, "POST", "/api/recipe/publish", {"variety": "K-200", "concentration": 8.0})
    assert response.status == 400
    body = {
        "variety": "K-200",
        "concentration": 8.0,
        "confirmation_id": issue_confirmation(console, "recipe.K-200", "recipe"),
    }
    assert refused(console, "POST", "/api/recipe/publish", {**body, "tolerance": -1}).status == 400
    assert refused(console, "POST", "/api/recipe/publish", {**body, "concentration": 30.0}).status == 422
    assert refused(console, "POST", "/api/recipe/publish", {**body, "confirmation_id": "cfm-999999"}).status == 404


def test_recipe_state_survives_a_restart(config):
    first = build(config)
    publish(first.console, "K-200", 8.0)
    run_switch(first.console, "K-200", 8.2)
    ok(first.console, "POST", "/api/recipe/correct", {"reading": 9.5, "volume": 1000})

    second = build(config)
    assert second.recipe.active().variety == "K-200"
    assert second.recipe.active().generation == 1
    assert second.recipe.switch_state()["next"] == "complete"
    assert len(second.recipe.corrections()) == 1
    assert second.recipe.corrections()[0]["amount"] == 187.5
    assert second.glue.concentration() == 8.0
