from browser_support import run_records, step_to


def test_every_beat_of_every_turn_renders(page, bundle_url, tmp_path):
    page.goto(bundle_url(run_records(tmp_path, turns=2)))
    for turn in (1, 2):
        for name in ("thinking", "declaring", "resolving", "dispatch"):
            step_to(page, turn, name)
            box = page.locator("#stage").bounding_box()
            assert box["height"] > 200, f"stage collapsed at day {turn}, {name}"


def test_the_map_is_drawn_at_a_real_size(page, bundle_url, tmp_path):
    page.goto(bundle_url(run_records(tmp_path)))
    box = page.locator("#boardmap").bounding_box()
    assert box["width"] > 100 and box["height"] > 60


def test_recorded_resolution_is_not_frozen(page, bundle_url, tmp_path):
    """The mockup merged 'auto' and 'freeze', and a recorded run then froze its
    own resolution animation on the first phase."""
    page.goto(bundle_url(run_records(tmp_path)))
    step_to(page, 1, "resolving")
    page.wait_for_function(
        "() => { const n = document.querySelectorAll('.phase').length;"
        " return n > 0 && document.querySelectorAll('.phase.past').length === n; }",
        timeout=10_000,
    )


def test_space_freezes_the_scene(page, bundle_url, tmp_path):
    page.goto(bundle_url(run_records(tmp_path)))
    step_to(page, 1, "resolving")
    page.keyboard.press(" ")
    page.wait_for_timeout(1500)
    assert page.locator(".phase.past").count() == 0
    assert "frozen" in page.locator("#stage").get_attribute("class")


def test_hover_shows_the_place_card(page, bundle_url, tmp_path):
    page.goto(bundle_url(run_records(tmp_path)))
    page.locator("#boardmap [data-place]").first.hover()
    assert page.locator("#tip").is_visible()
    assert "sealed" in page.locator("#tip").inner_text().lower()


def test_card_refreshes_when_the_map_redraws(page, bundle_url, tmp_path):
    page.goto(bundle_url(run_records(tmp_path)))
    step_to(page, 1, "thinking")
    page.locator("#boardmap [data-place]").first.hover()
    assert "sealed" in page.locator("#tip").inner_text().lower()
    step_to(page, 1, "declaring")  # the board map redraws under the still pointer
    page.wait_for_timeout(200)
    assert page.locator("#tip").is_visible()
    card = page.locator("#tip").inner_text().lower()
    assert "sealed" not in card
    assert "nobody declared anything against this place" in card


def test_viewer_truncated_transcript(page, bundle_url, tmp_path):
    records = run_records(tmp_path, turns=2)
    last_state = max(i for i, r in enumerate(records) if r["kind"] == "state")
    page.goto(bundle_url(records[:last_state]))
    step_to(page, 1, "resolving")
    assert page.locator(".banner").count() == 0, "a complete day shows the incomplete banner"
    step_to(page, 2, "resolving")
    assert page.locator(".banner").is_visible()


def test_viewer_plays_a_scenario_with_an_empty_display_block(page, bundle_url, tmp_path):
    records = run_records(tmp_path, scenario_dir="smoke")
    records[0]["scenario"]["display"] = {}
    for place in records[0]["scenario"]["places"].values():
        place.get("attrs", {}).pop("lat", None)
        place.get("attrs", {}).pop("lon", None)
    page.goto(bundle_url(records))
    for turn in (1, 2):
        for name in ("thinking", "declaring", "resolving", "dispatch"):
            step_to(page, turn, name)
            assert page.locator(".nomap").count() >= 1, f"map panel lost at day {turn}, {name}"


def test_presenter_mode_hides_the_controls(page, bundle_url, tmp_path):
    page.goto(bundle_url(run_records(tmp_path)))
    page.keyboard.press("p")
    assert not page.locator(".controls").is_visible()
    page.keyboard.press("Escape")
    assert page.locator(".controls").is_visible()


def _failed_before_prompts(records: list[dict], turn: int) -> list[dict]:
    """The run as the engine leaves it when a rule raises inside view() on `turn`:
    no prompt for that turn, and an error record in its place."""
    first = next(i for i, r in enumerate(records) if r["kind"] == "prompt" and r["turn"] == turn)
    return [*records[:first], {"kind": "error", "turn": turn, "error": "boom in view"}]


def _chrome(page, key: str) -> str:
    return page.evaluate(f"Casus.i18n.t({key!r})")


def test_a_run_that_fails_before_its_first_prompt_shows_the_failure(page, bundle_url, tmp_path):
    page.goto(bundle_url(_failed_before_prompts(run_records(tmp_path), turn=1)))
    closing = page.locator(".finale")
    assert _chrome(page, "failed") in closing.inner_text()
    assert "boom in view" in closing.inner_text()


def test_a_run_that_fails_before_day_two_ends_on_the_failure(page, bundle_url, tmp_path):
    page.goto(bundle_url(_failed_before_prompts(run_records(tmp_path), turn=2)))
    step_to(page, 1, "dispatch")
    page.keyboard.press("ArrowRight")
    closing = page.locator(".finale").inner_text()
    assert _chrome(page, "failed") in closing and "boom in view" in closing
    assert _chrome(page, "end") not in closing


def test_a_run_cut_short_ends_on_incomplete(page, bundle_url, tmp_path):
    records = run_records(tmp_path, turns=2)
    last_state = max(i for i, r in enumerate(records) if r["kind"] == "state")
    page.goto(bundle_url(records[:last_state]))
    step_to(page, 2, "dispatch")
    page.keyboard.press("ArrowRight")
    closing = page.locator(".finale").inner_text()
    assert _chrome(page, "incomplete") in closing
    assert _chrome(page, "end") not in closing


def test_a_run_cut_before_any_prompt_says_incomplete(page, bundle_url, tmp_path):
    records = run_records(tmp_path, turns=2)
    first_prompt = next(i for i, r in enumerate(records) if r["kind"] == "prompt")
    page.goto(bundle_url(records[:first_prompt]))
    assert _chrome(page, "incomplete") in page.locator(".finale").inner_text()
