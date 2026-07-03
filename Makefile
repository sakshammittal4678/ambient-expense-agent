# Makefile for ambient-expense-agent (ADK 2.0)
# Requires: uv  →  https://docs.astral.sh/uv/getting-started/installation/
# On Windows run these targets inside Git Bash, WSL, or a uv-aware shell.

.DEFAULT_GOAL := help
SHELL         := /bin/bash

# ── colour helpers ─────────────────────────────────────────────────────────
BOLD  := $(shell tput bold  2>/dev/null || echo "")
RESET := $(shell tput sgr0  2>/dev/null || echo "")
GREEN := $(shell tput setaf 2 2>/dev/null || echo "")
CYAN  := $(shell tput setaf 6 2>/dev/null || echo "")

# ── settings ───────────────────────────────────────────────────────────────
APP_NAME  := expense_agent
PORT      := 8080
BASE_URL  := http://localhost:$(PORT)

# ───────────────────────────────────────────────────────────────────────────
.PHONY: help
help:           ## Show this help message
	@echo ""
	@echo "$(BOLD)ambient-expense-agent — ADK 2.0$(RESET)"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  $(CYAN)%-18s$(RESET) %s\n", $$1, $$2}'
	@echo ""

# ───────────────────────────────────────────────────────────────────────────
.PHONY: install
install:        ## Install all dependencies (core + dev + eval + lint extras)
	uv sync --all-extras
	@echo "$(GREEN)✓ Dependencies installed into .venv$(RESET)"

# ───────────────────────────────────────────────────────────────────────────
.PHONY: playground
playground:     ## Launch the ADK web UI at http://localhost:8000
	@echo "$(BOLD)Starting ADK playground → $(BASE_URL)$(RESET)"
	uv run adk web

# ───────────────────────────────────────────────────────────────────────────
.PHONY: lint
lint:           ## Run ruff + ty + codespell (read-only)
	uv run ruff check .
	uv run ruff format . --check
	uv run codespell
	uv run ty check .

.PHONY: lint-fix
lint-fix:       ## Auto-fix formatting and import order
	uv run ruff check . --fix
	uv run ruff format .

# ───────────────────────────────────────────────────────────────────────────
.PHONY: test
test:           ## Run the unit + integration test suite
	uv run pytest

# ───────────────────────────────────────────────────────────────────────────
# Sends a single expense payload through the REST API.
# The server must already be running (make playground in another terminal).
# Amount $150 → manual_review → security_checkpoint (clean) → LLM → HITL
TEST_PAYLOAD := {"amount": 150.0, "submitter": "alice@company.com", \
                  "category": "software", "description": "IDE License", \
                  "date": "2026-06-06"}

.PHONY: test-expense
test-expense:   ## Send a $150 test expense to the running playground
	@echo "$(BOLD)Creating session for user test_user …$(RESET)"
	$(eval SESSION_ID := $(shell \
	  curl -sf -X POST "$(BASE_URL)/apps/$(APP_NAME)/users/test_user/sessions" \
	       -H "Content-Type: application/json" \
	       -d '{"state":{}}' | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])"))
	@echo "  session_id = $(SESSION_ID)"
	@echo "$(BOLD)Sending expense payload …$(RESET)"
	curl -s -X POST "$(BASE_URL)/run_sse" \
	     -H "Content-Type: application/json" \
	     -d '{ \
	           "app_name":   "$(APP_NAME)", \
	           "user_id":    "test_user", \
	           "session_id": "$(SESSION_ID)", \
	           "new_message": { \
	             "role":  "user", \
	             "parts": [{"text": "$(TEST_PAYLOAD)"}] \
	           } \
	         }' | python3 -c "
import sys
for line in sys.stdin:
    line = line.strip()
    if line.startswith('data:'):
        print(line[5:].strip())
"
	@echo ""
	@echo "$(GREEN)Workflow paused for human approval — open $(BASE_URL) and reply yes/no$(RESET)"

# ───────────────────────────────────────────────────────────────────────────
.PHONY: clean
clean:          ## Remove .venv, __pycache__, and .pytest_cache
	rm -rf .venv __pycache__ .pytest_cache expense_agent/__pycache__
	find . -name "*.pyc" -delete
	@echo "$(GREEN)✓ Clean$(RESET)"
