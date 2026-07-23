# IsThisBS? — developer entrypoints.
# `make` with no target prints help. Everything is phony (no file targets).

.DEFAULT_GOAL := help

.PHONY: smoke-live help install build smoke serve test lint fmt deploy clean distclean

help:  ## Show this help
	@echo "IsThisBS? — make targets:"
	@echo "  install    Install the package with dev + search extras (editable)"
	@echo "  build      Full static build into dist/ (keyless)"
	@echo "  smoke      Fast 2-page build to sanity-check the pipeline"
	@echo "  serve      Serve dist/ locally at http://localhost:8080"
	@echo "  test       Run the offline pytest suite"
	@echo "  lint       ruff check + format check"
	@echo "  fmt        Auto-format with ruff"
	@echo "  deploy     Build and deploy to Firebase Hosting (deploy/deploy.sh)"
	@echo "  clean      Remove dist/"
	@echo "  distclean  Remove dist/ and the incremental .cache/"

install:  ## Install with dev + search extras (editable)
	pip install -e ".[dev,search]"

build:  ## Full static build into dist/ (keyless)
	python build.py

smoke:  ## Fast 2-page build to sanity-check the pipeline
	python build.py --max-pages 2

serve:  ## Serve dist/ locally at http://localhost:8080
	python3 scripts/serve.py 8080 dist

test:  ## Run the offline pytest suite
	pytest -q

test-layout:  ## Layout invariants over dist/ in Chromium + WebKit (build first)
	cd e2e && npm install && npx playwright install chromium webkit && npx playwright test

lint:  ## ruff check + format check
	ruff check . && ruff format --check .

fmt:  ## Auto-format with ruff
	ruff format .

deploy:  ## Build and deploy to Firebase Hosting
	bash deploy/deploy.sh

clean:  ## Remove dist/
	rm -rf dist

distclean: clean  ## Remove dist/ and the incremental .cache/
	rm -rf .cache

smoke-live:  ## Verify the LIVE site (redirects, catalog, function, SEO assets)
	bash scripts/smoke.sh
