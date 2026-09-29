import pytest


def test_the_home_lists_scenarios_and_runs(page, app_url):
    page.goto(app_url)
    page.wait_for_selector("[data-scenario]")
    assert page.locator("[data-scenario]").count() >= 2
    assert page.locator(".runrow").count() == 1


def test_view_opens_the_viewer_on_a_recorded_run(page, app_url):
    page.goto(app_url)
    page.locator(".runrow button").first.click()
    page.wait_for_selector(".visor")
    assert "recorded" in page.locator(".rectag").inner_text().lower()


def test_a_run_cut_mid_line_opens(page, app_url, runs_dir):
    path = runs_dir / "reference-1.jsonl"
    path.write_text(path.read_text() + '{"kind":"sta')
    page.goto(app_url)
    page.locator(".runrow button").first.click()
    page.wait_for_selector(".visor")


@pytest.fixture
def quiet_page(browser):
    """A page that records uncaught errors but not console noise: the browser
    logs every failed fetch to the console, and these tests make one on purpose."""
    ctx = browser.new_context(viewport={"width": 1600, "height": 900})
    pg = ctx.new_page()
    pg.uncaught = []
    pg.on("pageerror", lambda e: pg.uncaught.append(str(e)))
    yield pg
    ctx.close()


@pytest.mark.parametrize("route", ["#/view/no-such-run", "#/view/mangled", "#/view"])
def test_a_run_that_cannot_be_opened_says_so(quiet_page, app_url, runs_dir, route):
    lines = (runs_dir / "reference-1.jsonl").read_text().splitlines()
    (runs_dir / "mangled.jsonl").write_text("\n".join([lines[0], "{", *lines[1:]]) + "\n")
    page = quiet_page
    page.goto(app_url)
    page.wait_for_selector("[data-scenario]")
    page.evaluate(f"location.hash = {route!r}")
    notice = page.locator(".notice")
    notice.wait_for(timeout=5_000)
    assert page.evaluate("Casus.i18n.t('cannot_open')") in notice.inner_text()
    assert page.locator("[data-scenario]").count() == 0
    assert not page.uncaught



HOSTILE = "<img src=x onerror=window.PWNED=1>"


def test_the_home_escapes_every_value_it_is_sent(page, app_url):
    """Scenario YAML and run files are not trusted markup, even when the server
    would have cleaned them: this feeds the shell hostile values directly."""
    card = {"name": "n", "dir": "d", "actors": HOSTILE, "places": HOSTILE, "turns": HOSTILE,
            "description": "", "valid": True, "findings": []}
    run = {"id": "r", "scenario": "n", "seed": 1, "turns_planned": HOSTILE,
           "turns_done": HOSTILE, "status": "complete", "path": ""}
    page.route("**/api/scenarios", lambda route: route.fulfill(json=[card]))
    page.route("**/api/runs", lambda route: route.fulfill(json=[run]))
    page.goto(app_url)
    page.wait_for_selector("[data-scenario]")
    page.wait_for_timeout(200)
    assert page.evaluate("window.PWNED") is None
    assert HOSTILE in page.locator("[data-scenario] .meta").inner_text()
