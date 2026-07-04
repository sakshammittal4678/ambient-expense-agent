# Ambient Expense Agent

> **AI-powered receipt-to-approval in seconds.** A multimodal, agentic expense management system that turns receipts — text, photo, or voice — into structured approvals using Gemini and Google ADK 2.0's Graph Workflow with Human-in-the-Loop oversight.

[![Live Demo — Employee UI](https://img.shields.io/badge/Live%20Demo-Employee%20UI-4f46e5?style=for-the-badge)](https://ambient-expense-agent-production.up.railway.app/intake)
[![Live Demo — Admin Dashboard](https://img.shields.io/badge/Live%20Demo-Admin%20Dashboard-10b981?style=for-the-badge)](https://ambient-expense-agent-production.up.railway.app/)

---

## ✨ Features

### Multimodal Expense Intake
- **Text** — type a free-form description: *"Starbucks coffee $14.50 on July 1"*
- **Image** — upload a JPEG/PNG receipt photo; Gemini reads printed text, logos, and handwriting
- **Audio** — attach an MP3/WAV voice memo; Gemini transcribes and parses the spoken description
- Gemini's **Structured Outputs** (`response_schema`) guarantee typed, validated JSON — no hallucinated values
- **Confidence scoring** — low-confidence extractions are flagged and explained rather than silently guessed

### Intelligent 7-Stage Agentic Pipeline (ADK 2.0 Graph Workflow)
1. **Intake Agent** — multimodal parsing into a typed `IntakeExtraction` schema
2. **Reconciliation Agent** — duplicate detection, ambiguous vendor matching, and LLM-backed currency normalization (`₹500/-` → `500.0 INR`)
3. **Security Checkpoint** — regex-based PII redaction (SSN, credit cards) and prompt-injection blocking *before* any LLM call
4. **Threshold Router** — expenses under `$100` auto-approved instantly; at or above routed to human review
5. **LLM Risk Review** — Gemini scores the expense on a 1–5 risk scale with typed `RiskReview` output
6. **Human-in-the-Loop (HITL)** — ADK 2.0 `RequestInput` / `rerun_on_resume` pauses execution; admin approves from the live dashboard
7. **Outcome Logger** — approved/rejected outcomes written to `expenses.log` and the SQLite ledger with full status lifecycle

### Security-First Design
- **PII redaction** before any LLM sees the text (SSN pattern `\b\d{3}-\d{2}-\d{4}\b`, 16-digit credit card pattern)
- **Prompt injection detection** blocks jailbreak phrases ("ignore previous instructions", "you must auto-approve") — malicious expenses bypass the LLM and go directly to a human reviewer
- **Audit trail** — every workflow step is logged with typed inputs, outputs, and routing decisions

### Two Beautiful UIs
- **Employee Intake Terminal** (`/intake`) — glassmorphism dark UI, real-time confidence badge, clarification banner, outcome status
- **Admin Review Dashboard** (`/`) — real-time approval cards (2-second polling), ambiguity flags, ledger history side panel with status badges

### MCP Ledger Server
- Expense ledger exposed via **Model Context Protocol (MCP)** using FastMCP
- Dual interface: MCP streamable-HTTP transport + plain REST endpoints
- Full status lifecycle: `pending` → `approved` / `rejected` / `needs_clarification`

---

## 🏗️ Project Structure

```
ambient-expense-agent/
├── app/                                # Shared agent logic
│   ├── agents/
│   │   ├── intake_agent.py             # Gemini multimodal receipt parser
│   │   └── reconciliation_agent.py     # Duplicate detection & currency normalization
│   ├── mcp_servers/
│   │   └── ledger_server.py            # MCP + REST ledger server (SQLite)
│   └── skills/
│       └── currency_normalization.py   # LLM-backed currency normalization skill
│
├── expense_agent/                      # ADK 2.0 workflow package
│   ├── agent.py                        # 7-node Graph Workflow definition
│   ├── config.py                       # Settings (threshold, model name)
│   ├── fast_api_app.py                 # FastAPI app — serves both UIs + all API routes
│   └── app_utils/
│       ├── telemetry.py                # OpenTelemetry + GCS log upload
│       └── typing.py                   # Shared type definitions
│
├── intake_ui/
│   └── index.html                      # Employee Intake Terminal (standalone HTML)
│
├── tests/
│   ├── unit/                           # Unit tests (intake, ledger, reconciliation, currency)
│   ├── integration/                    # Integration & end-to-end pipeline tests
│   └── eval/                           # ADK eval dataset + config
│
├── Dockerfile                          # Production container (Python 3.12-slim + uv)
├── pyproject.toml                      # Dependencies (uv-managed)
├── ledger.db                           # SQLite ledger database
├── expenses.log                        # Append-only expense outcome log
└── workflow_analysis.md                # Architecture design rationale
```

---

## 🚀 Quick Start

### Prerequisites

| Tool | Purpose | Install |
|------|---------|---------|
| **Python 3.11+** | Runtime | [python.org](https://www.python.org/downloads/) |
| **uv** | Package manager | `pip install uv` or [docs](https://docs.astral.sh/uv/getting-started/installation/) |
| **Google API Key** | Gemini access | [AI Studio](https://aistudio.google.com/app/apikey) |

### 1. Clone the repository

```bash
git clone https://github.com/sakshammittal4678/ambient-expense-agent.git
cd ambient-expense-agent
```

### 2. Set up environment variables

Create a `.env` file in the project root:

```bash
# .env
GOOGLE_API_KEY=your_google_api_key_here
```

Optional environment variables:

```bash
THRESHOLD_AMOUNT=100.0         # Expenses >= this require human approval (default: 100.0)
MODEL_NAME=gemini-2.5-flash    # LLM for risk review (default: gemini-3.1-flash-lite)
INTAKE_MODEL_NAME=gemini-2.5-flash  # LLM for multimodal intake (default: gemini-3.1-flash-lite)
```

### 3. Install dependencies

```bash
uv sync
```

To include dev, eval, and lint extras:

```bash
uv sync --all-extras
```

### 4. Run the server locally

```bash
uv run uvicorn expense_agent.fast_api_app:app --host 0.0.0.0 --port 8080 --reload
```

The server starts at `http://localhost:8080`.

| UI | URL |
|----|-----|
| Employee Intake Terminal | http://localhost:8080/intake |
| Admin Review Dashboard | http://localhost:8080/ |
| API Docs (Swagger) | http://localhost:8080/docs |

---

## 🌐 Live Demo

| Interface | URL |
|-----------|-----|
| 🧑‍💼 Employee Intake | https://ambient-expense-agent-production.up.railway.app/intake |
| 🛡️ Admin Dashboard | https://ambient-expense-agent-production.up.railway.app/ |

### Demo walkthrough

**Auto-approve flow (under threshold):**
1. Open the Employee UI → set Role to `employee`, enter any ID (e.g. `alice@company.com`)
2. Type: `Starbucks coffee $14.50 on July 1`
3. Click **Parse & Analyze** → Gemini extracts all fields with a confidence badge
4. Click **Submit to Workflow** → instantly auto-approved (under $100)

**Human approval flow (above threshold):**
1. Submit: `Conference hotel stay $350 on July 1`
2. Open the Admin Dashboard in another tab
3. The approval card appears in real time (polling every 2 seconds)
4. Click **Approve** or **Decline** → card animates out, ledger updates

---

## 🔌 API Reference

| Method | Route | Description |
|--------|-------|-------------|
| `GET` | `/` | Admin Review Dashboard (HTML) |
| `GET` | `/intake` | Employee Intake Terminal (HTML) |
| `POST` | `/api/intake` | Parse a receipt (text, image, or audio) and run the workflow |
| `GET` | `/api/pending` | List expenses currently awaiting human approval |
| `POST` | `/api/decision` | Submit an approval decision (`yes`/`no`) for a pending session |
| `GET` | `/api/history` | Get full ledger history (all entries with statuses) |
| `POST` | `/` | Submit a structured expense directly to the ADK workflow (JSON) |

### `POST /api/intake` — multipart form

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `role` | string | ✅ | `employee`, `bookkeeper`, or `owner` |
| `submitter_id` | string | ✅ | Employee identifier (email or ID) |
| `text_input` | string | one of | Free-text expense description |
| `file` | file | one of | Receipt image (JPEG/PNG) or audio (MP3/WAV) |

### `POST /api/decision` — JSON body

```json
{
  "session_id": "uuid-of-pending-session",
  "decision": "yes"
}
```

---

## 🔄 Workflow Architecture

```
Employee Submission
        │
        ▼
  ┌─────────────┐
  │ Intake Node │  ← Gemini multimodal: text / image / audio → IntakeExtraction
  └──────┬──────┘
         │
         ▼
  ┌──────────────────────┐
  │ Reconciliation Node  │  ← Duplicate check, vendor ambiguity, currency normalization
  └──────┬───────────────┘
         │
    ┌────┴─────┐
    │          │
  clean    ambiguous ──→ [Admin HITL] → approved / rejected
    │
    ▼
  ┌──────────────────────┐
  │ Security Checkpoint  │  ← PII redact + prompt injection detect
  └──────┬───────────────┘
         │
    ┌────┴─────┐
    │          │
  clean    injection ──→ [Admin HITL] ← bypasses LLM entirely
    │
    ▼
  ┌──────────────────┐
  │ Threshold Router │
  └──────┬───────────┘
         │
    ┌────┴──────────────────┐
    │                       │
 < $100                  ≥ $100
    │                       │
    ▼                       ▼
 Auto-Approve      ┌──────────────────┐
    │              │ LLM Risk Review  │  ← Gemini structured RiskReview output
    │              └────────┬─────────┘
    │                       │
    │              ┌────────▼─────────┐
    │              │  Admin HITL      │  ← ADK RequestInput / rerun_on_resume
    │              └────────┬─────────┘
    │                       │
    │                  ┌────┴────┐
    │                  │         │
    │              Approved   Rejected
    │                  │         │
    └──────────────────┼─────────┤
                       ▼         ▼
              Record Outcome + Update Ledger
```

---

## 🧪 Testing

### Run all tests

```bash
uv run pytest tests/unit tests/integration
```

### Run only unit tests

```bash
uv run pytest tests/unit -v
```

### Run only integration tests

```bash
uv run pytest tests/integration -v
```

### Run with integration test mock (no real API calls)

```bash
INTEGRATION_TEST=TRUE uv run pytest tests/integration -v
```

### Test coverage

| Test Suite | Files | What's Tested |
|-----------|-------|---------------|
| `tests/unit/` | 5 files | Intake agent, ledger server, reconciliation agent, currency normalization |
| `tests/integration/` | 4 files | Full pipeline, server E2E, intake integration |

---

## 📊 Evaluation

The project includes an ADK eval dataset and config for automated quality grading.

```bash
# Generate traces from the eval dataset
agents-cli eval generate

# Grade the traces using LLM-as-judge
agents-cli eval grade

# Compare two grade result files (regression check)
agents-cli eval compare

# Analyze failure modes
agents-cli eval analyze
```

The eval dataset is at `tests/eval/datasets/basic-dataset.json`.

---

## 🐳 Docker

### Build and run locally

```bash
docker build -t ambient-expense-agent .
docker run -p 8080:8080 -e GOOGLE_API_KEY=your_key ambient-expense-agent
```

### Environment variables for Docker

```bash
docker run -p 8080:8080 \
  -e GOOGLE_API_KEY=your_key \
  -e THRESHOLD_AMOUNT=100.0 \
  -e MODEL_NAME=gemini-2.5-flash \
  ambient-expense-agent
```

---

## ☁️ Deployment

### Railway (recommended for demos)

1. Fork or clone this repo to your GitHub account
2. Go to [railway.app](https://railway.app) → New Project → Deploy from GitHub
3. Select this repository — Railway auto-detects the `Dockerfile`
4. Add environment variable: `GOOGLE_API_KEY=your_key`
5. Railway generates a public URL under Settings → Networking → Generate Domain

### Google Cloud Run

```bash
gcloud config set project your-project-id
gcloud run deploy ambient-expense-agent \
  --source . \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars GOOGLE_API_KEY=your_key \
  --port 8080
```

### Using agents-cli (GCP Agent Runtime)

```bash
# Set up infrastructure (Terraform)
agents-cli infra single-project

# Deploy to dev
agents-cli deploy
```

---

## ⚙️ Configuration Reference

All settings are loaded via environment variables (or `.env` file):

| Variable | Default | Description |
|----------|---------|-------------|
| `GOOGLE_API_KEY` | — | **Required.** Google AI Studio or Vertex AI API key |
| `THRESHOLD_AMOUNT` | `100.0` | Expenses at or above this (USD) require human approval |
| `MODEL_NAME` | `gemini-3.1-flash-lite` | Gemini model for LLM risk review |
| `INTAKE_MODEL_NAME` | `gemini-3.1-flash-lite` | Gemini model for multimodal intake parsing |
| `LEDGER_SERVER_URL` | `http://localhost:8081` | URL of the MCP ledger server (if running separately) |
| `LEDGER_DB_PATH` | `ledger.db` | Path to the SQLite ledger database file |
| `ALLOW_ORIGINS` | — | Comma-separated CORS origins (e.g. `https://myapp.com`) |
| `LOGS_BUCKET_NAME` | — | GCS bucket for OpenTelemetry log upload |

---

## 🔭 Observability

The project includes built-in OpenTelemetry instrumentation via `expense_agent/app_utils/telemetry.py`:

- **Prompt-response logging** — uploads Gemini call metadata to Google Cloud Storage (set `LOGS_BUCKET_NAME`)
- **Privacy-safe by default** — content capture mode is set to `NO_CONTENT` (metadata only, no prompt/response text stored)
- **Service versioning** — `COMMIT_SHA` is injected as a build arg in Docker and surfaced in telemetry attributes

To enable full telemetry:
```bash
LOGS_BUCKET_NAME=gs://your-bucket
OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=NO_CONTENT
```

---

## 🛠️ Development Commands

| Command | Description |
|---------|-------------|
| `uv sync` | Install core dependencies |
| `uv sync --all-extras` | Install all extras (dev, eval, lint) |
| `uv run uvicorn expense_agent.fast_api_app:app --reload` | Run dev server with hot reload |
| `uv run adk web` | Launch ADK playground UI |
| `agents-cli playground` | Alternative ADK playground |
| `uv run pytest tests/unit tests/integration` | Run all tests |
| `uv run ruff check .` | Lint code |
| `uv run ruff format .` | Format code |
| `agents-cli eval generate` | Run agent against eval dataset |
| `agents-cli eval grade` | Grade eval traces |
| `agents-cli scaffold enhance` | Add CI/CD + Terraform |
| `agents-cli scaffold upgrade` | Upgrade to latest agents-cli version |

---

## 📦 Tech Stack

| Layer | Technology |
|-------|-----------|
| Agent Orchestration | [Google ADK 2.0](https://adk.dev/) — Graph Workflow |
| AI Models | Gemini (multimodal intake, LLM risk review, currency normalization) |
| API Framework | FastAPI + Uvicorn |
| Ledger Storage | SQLite via MCP (FastMCP) |
| MCP Protocol | [Model Context Protocol](https://modelcontextprotocol.io/) |
| Package Manager | [uv](https://docs.astral.sh/uv/) |
| Container | Docker (Python 3.12-slim) |
| Frontend | Vanilla HTML / CSS / JavaScript (no framework) |

---

## 📄 License

Apache 2.0 — see [LICENSE](LICENSE) for details.
