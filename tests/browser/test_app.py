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
