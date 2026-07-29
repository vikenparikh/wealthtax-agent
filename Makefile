# Local runners for the 4 test tiers. GitHub Actions is billing-blocked in this
# environment, so these let vps-ci or a human run each tier locally; they mirror
# exactly what the CI workflows run.
#
#   tier 1 unit       -> make test-unit        (CI: tests.yml)
#   tier 2 backend    -> make test-backend     (CI: test-tiers.yml `backend`)
#   tier 3 e2e        -> make test-e2e         (CI: test-tiers.yml `e2e`)
#   tier 4 playwright -> make test-playwright  (CI: playwright-e2e.yml, real browser)
#
# The Python tiers run fully offline (mocked LLM, SQLite). PYTHONPATH=src supports a
# fresh checkout without `pip install -e .`; it's harmless when the package IS installed.

PYTEST := PYTHONPATH=src python -m pytest -p no:cacheprovider -q -o addopts=""

# The streamlit AppTest UI suites = tier 3 (E2E); excluded from the backend tier.
E2E_FILES := \
	tests/integration/test_streamlit_smoke.py \
	tests/integration/test_streamlit_nav_smoke.py \
	tests/integration/test_e2e_wizard_flow.py \
	tests/integration/test_wizard_ui.py

.PHONY: test test-unit test-backend test-e2e test-playwright test-python

## tier 1 — fast, isolated unit tests
test-unit:
	$(PYTEST) tests/unit

## tier 2 — backend: integration + engines/DB/pipeline, no browser
test-backend:
	$(PYTEST) tests --ignore=tests/unit $(addprefix --ignore=,$(E2E_FILES))

## tier 3 — E2E: streamlit AppTest UI suites
test-e2e:
	$(PYTEST) $(E2E_FILES)

## tier 4 — Playwright real-browser smoke vs the deployed surface
## (BASE_URL overridable; set E2E_ACCESS_BYPASS_COOKIE to reach the app behind the gate)
test-playwright:
	cd e2e && npm install && npx playwright install --with-deps chromium && npx playwright test

## all three Python tiers (tiers 1-3)
test-python: test-unit test-backend test-e2e

## alias
test: test-python
