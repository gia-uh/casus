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
    page.wait_for_timeout(3200)
    assert page.locator(".phase.past").count() == 5


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
    assert "sealed" not in page.locator("#tip").inner_text().lower()


def test_viewer_truncated_transcript(page, bundle_url, tmp_path):
    records = run_records(tmp_path, turns=2)
    last_state = max(i for i, r in enumerate(records) if r["kind"] == "state")
    page.goto(bundle_url(records[:last_state]))
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
