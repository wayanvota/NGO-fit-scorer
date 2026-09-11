from __future__ import annotations

from pathlib import Path

from playwright.sync_api import expect


ROOT = Path(__file__).parents[1]


def opportunity_text(title: str = "Community health opportunity") -> str:
    return (
        f"{title}\n"
        "The funder offers $125,000 in unrestricted support for community health, "
        "equitable access, local partnerships, and measurable nonprofit outcomes."
    )


def login(page, email: str = "admin@example.org"):
    page.goto("/")
    page.get_by_label("Work email (allowed domain)").fill(email)
    page.get_by_role("button", name="Sign in").click()
    expect(page.get_by_role("heading", name="Score an opportunity")).to_be_visible()


def score(page, title: str = "Community health opportunity"):
    page.get_by_label("Opportunity text (RFP, grant call, or funder email)").fill(opportunity_text(title))
    page.get_by_role("button", name="Score it").click()
    expect(page.get_by_role("heading", name="Go / no-go memo")).to_be_visible()


def test_u01_first_use_explains_sign_in_and_local_boundary(page):
    page.goto("/")
    expect(page.get_by_role("heading", name="Funding Fit Scorer")).to_be_visible()
    expect(page.get_by_label("Work email (allowed domain)")).to_be_visible()
    expect(page.get_by_text("Dev sign-in is for local use only.")).to_be_visible()


def test_u02_core_login_score_and_result_workflow(page):
    login(page)
    score(page, "U02 community health grant")
    expect(page.get_by_text("Mock mode: no Claude API key set")).to_be_visible()
    score_value = int(page.locator(".score-num").inner_text())
    assert 0 <= score_value <= 100
    expect(page.locator(".memo")).to_contain_text("U02 community health grant")


def test_u03_invalid_domain_then_corrected_login(page):
    page.goto("/")
    page.get_by_label("Work email (allowed domain)").fill("person@attacker.invalid")
    page.get_by_role("button", name="Sign in").click()
    expect(page.locator(".err")).to_contain_text("not on an allowed domain")
    page.get_by_label("Work email (allowed domain)").fill("staff@example.org")
    page.get_by_role("button", name="Sign in").click()
    expect(page.get_by_role("heading", name="Score an opportunity")).to_be_visible()


def test_u04_unicode_and_relationship_boundary_survive_scoring(page):
    login(page)
    title = "Niñas' $0 access initiative 🌍"
    page.get_by_label("Opportunity text (RFP, grant call, or funder email)").fill(opportunity_text(title))
    page.get_by_label("Relationship with this funder (optional)").select_option("existing")
    page.get_by_role("button", name="Score it").click()
    expect(page.locator(".memo")).to_contain_text(title)


def test_u05_history_detail_and_reload_preserve_saved_result(page):
    login(page)
    title = "U05 durable opportunity"
    score(page, title)
    page.get_by_role("button", name="History").click()
    page.get_by_role("cell", name=title).click()
    expect(page.get_by_role("heading", name=title)).to_be_visible()
    page.reload()
    page.get_by_role("button", name="History").click()
    page.get_by_role("cell", name=title).click()
    expect(page.get_by_role("heading", name=title)).to_be_visible()


def test_u06_decision_can_be_reversed(page):
    login(page)
    title = "U06 reversible decision"
    score(page, title)
    page.get_by_role("button", name="History").click()
    page.get_by_role("cell", name=title).click()
    page.get_by_role("button", name="pursue", exact=True).click()
    expect(page.get_by_role("button", name="pursue", exact=True)).not_to_have_class("secondary")
    page.get_by_role("button", name="pass", exact=True).click()
    expect(page.get_by_role("button", name="pass", exact=True)).not_to_have_class("secondary")


def test_u07_interrupted_score_is_visible_and_retry_succeeds(page):
    login(page)
    page.route("**/api/opportunities", lambda route: route.fulfill(status=503, json={"detail": "Scoring is temporarily unavailable."}))
    page.get_by_label("Opportunity text (RFP, grant call, or funder email)").fill(opportunity_text("U07 retry"))
    page.get_by_role("button", name="Score it").click()
    expect(page.locator(".err")).to_contain_text("temporarily unavailable")
    page.unroute("**/api/opportunities")
    page.get_by_role("button", name="Score it").click()
    expect(page.get_by_role("heading", name="Go / no-go memo")).to_be_visible()


def test_u08_identity_controls_admin_navigation(page):
    login(page, "staff@example.org")
    expect(page.get_by_role("button", name="Admin")).to_have_count(0)
    page.get_by_role("button", name="Sign out").click()
    login(page, "admin@example.org")
    expect(page.get_by_role("button", name="Admin")).to_be_visible()
    expect(page.get_by_role("button", name="Setup")).to_be_visible()


def test_u09_keyboard_and_mobile_viewport_keep_core_flow_usable(page):
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto("/")
    page.get_by_label("Work email (allowed domain)").fill("admin@example.org")
    button = page.get_by_role("button", name="Sign in")
    button.focus()
    page.keyboard.press("Enter")
    expect(page.get_by_role("button", name="Score it")).to_be_visible()
    assert page.locator("body").evaluate("body => body.scrollWidth <= window.innerWidth")


def test_u10_repeated_score_action_creates_one_request(page):
    login(page)
    page.get_by_label("Opportunity text (RFP, grant call, or funder email)").fill(opportunity_text("U10 single request"))
    requests = []
    page.on("request", lambda request: requests.append(request) if request.url.endswith("/api/opportunities") and request.method == "POST" else None)
    page.get_by_role("button", name="Score it").dblclick()
    expect(page.get_by_role("heading", name="Go / no-go memo")).to_be_visible()
    assert len(requests) == 1


def test_a01_unknown_opportunity_is_rejected(page):
    login(page)
    response = page.context.request.get("/api/opportunities/not-a-real-id")
    assert response.status == 404
    decision = page.context.request.post(
        "/api/opportunities/not-a-real-id/decision", data={"decision": "pursue"}
    )
    assert decision.status == 404


def test_a02_type_confused_submission_is_rejected(page):
    login(page)
    response = page.context.request.post(
        "/api/opportunities",
        data={"source_type": [], "text": opportunity_text("A02")},
    )
    assert response.status == 422


def test_a03_stored_markup_cannot_execute(page):
    login(page)
    marker = '<img src=x onerror="window.__fitXss=1">'
    score(page, marker)
    assert page.evaluate("window.__fitXss") is None
    expect(page.locator(".memo img[src=x]")).to_have_count(0)


def test_a04_interpreter_shaped_text_remains_data(page):
    login(page)
    title = "'; DROP TABLE opportunities; --"
    score(page, title)
    page.get_by_role("button", name="History").click()
    expect(page.get_by_role("cell", name=title)).to_be_visible()


def test_a05_cross_origin_request_gets_no_browser_permission(page):
    response = page.context.request.get(
        "/api/config",
        headers={"Origin": "https://attacker.invalid"},
    )
    assert "access-control-allow-origin" not in response.headers
    assert "access-control-allow-credentials" not in response.headers


def test_a06_traversal_upload_name_cannot_escape_filesystem(page):
    login(page)
    outside = ROOT.parent / "owned-by-e2e.txt"
    outside.unlink(missing_ok=True)
    response = page.context.request.post(
        "/api/opportunities/upload",
        multipart={
            "file": {
                "name": "../../owned-by-e2e.txt",
                "mimeType": "text/plain",
                "buffer": opportunity_text("A06 upload").encode(),
            }
        },
    )
    assert response.ok
    assert not outside.exists()


def test_a07_generated_javascript_link_is_not_clickable(page):
    login(page)
    score(page, "[unsafe](javascript:window.__fitLink=1)")
    expect(page.locator('.memo a[href^="javascript:"]')).to_have_count(0)
    assert page.evaluate("window.__fitLink") is None


def test_a08_unauthenticated_admin_write_is_rejected(page):
    response = page.context.request.post(
        "/api/profile",
        data={"name": "forged", "profile_doc": {}, "dimensions": [], "hard_filters": [], "thresholds": {}, "tiers": {}},
    )
    assert response.status == 401


def test_a09_oversized_upload_is_bounded(page):
    login(page)
    response = page.context.request.post(
        "/api/opportunities/upload",
        multipart={
            "file": {
                "name": "large.txt",
                "mimeType": "text/plain",
                "buffer": b"x" * (15 * 1024 * 1024 + 1),
            }
        },
    )
    assert response.status == 413


def test_a10_malformed_json_does_not_expose_internals(page):
    response = page.context.request.post(
        "/api/dev-login",
        headers={"Content-Type": "application/json"},
        data="{not-json",
    )
    assert response.status == 422
    body = response.text()
    assert "Traceback" not in body
    assert "SECRET_KEY" not in body
    assert str(ROOT) not in body
    login(page)
    upload = page.context.request.post(
        "/api/opportunities/upload",
        multipart={
            "file": {
                "name": "broken.pdf",
                "mimeType": "application/pdf",
                "buffer": b"not a valid PDF",
            }
        },
    )
    assert upload.status == 400
    assert upload.json()["detail"] == "Could not read that PDF. Paste the text instead."
