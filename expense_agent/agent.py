# ruff: noqa
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import base64
import json
import os
import re
from typing import Any
import requests
from pydantic import BaseModel
from google import genai
from google.genai import types
from google.adk.events.event import Event
from google.adk.events.request_input import RequestInput
from google.adk.agents.context import Context
from google.adk.workflow import Workflow, node, Edge
from google.adk.apps import App
from app.agents.reconciliation_agent import run_reconciliation_agent
from expense_agent.config import settings


class RiskReview(BaseModel):
    """Structured Pydantic model for LLM risk assessment."""

    risk_score: int  # 1 to 5 scale (1: Low, 5: High)
    risk_factors: list[str]
    alert_raised: bool
    reasoning: str


def to_content(text: str) -> types.Content:
    """Helper to convert raw text into types.Content for Event compatibility."""
    return types.Content(role="model", parts=[types.Part.from_text(text=text)])


def parse_payload(node_input: Any) -> dict:
    """Parses raw input payload and extracts the inner expense dict."""
    raw = {}
    if isinstance(node_input, dict):
        raw = node_input
    elif isinstance(node_input, str):
        try:
            raw = json.loads(node_input)
        except Exception:
            pass
    elif hasattr(node_input, "parts"):
        parts = [p.text for p in node_input.parts if hasattr(p, "text") and p.text]
        combined = " ".join(parts)
        try:
            raw = json.loads(combined)
        except Exception:
            pass

    # Extract inner data key
    data_val = raw.get("data")
    if not data_val:
        # Fallback: if there is no data key, treat raw dict as the expense details
        data_dict = raw
    elif isinstance(data_val, str):
        # Handle Base64 encoded JSON (Pub/Sub event) or plain JSON string
        try:
            decoded = base64.b64decode(data_val).decode("utf-8")
            data_dict = json.loads(decoded)
        except Exception:
            try:
                data_dict = json.loads(data_val)
            except Exception:
                data_dict = {"description": data_val}
    elif isinstance(data_val, dict):
        data_dict = data_val
    else:
        data_dict = {}

    # Standardize data fields
    return {
        "amount": float(data_dict.get("amount", 0.0)),
        "submitter": str(data_dict.get("submitter", "Unknown")),
        "category": str(data_dict.get("category", "General")),
        "description": str(data_dict.get("description", "")),
        "date": str(data_dict.get("date", "")),
    }


def log_outcome(details: dict, approved: bool, reason: str):
    """Appends final expense outcome to a local log file."""
    outcome_str = "APPROVED" if approved else "REJECTED"
    log_line = (
        f"[{outcome_str}] {details.get('date')} | {details.get('submitter')} | "
        f"${details.get('amount')} | {details.get('category')} | Reason: {reason}\n"
    )
    with open("expenses.log", "a") as f:
        f.write(log_line)


# ---------------------------------------------------------------------------
# Security patterns — compiled once at module load
# ---------------------------------------------------------------------------

# PII: formatted SSN (123-45-6789) and 16-digit credit-card numbers
_RE_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_RE_CC = re.compile(r"\b(?:\d{4}[\s\-]?){3}\d{4}\b")

# Prompt injection: phrases that attempt to override model instructions
_RE_INJECTION = re.compile(
    r"(ignore\s+(previous|all|prior)\s+(instructions?|rules?|prompts?)"
    r"|you\s+must\s+(approve|auto.?approve)"
    r"|bypass\s+(rules?|checks?|security|approval)"
    r"|auto.?approve\s+(this|the|expense)"
    r"|override\s+(the\s+)?(threshold|rules?|policy)"
    r"|forget\s+(your\s+)?(instructions?|rules?)"
    r"|disregard\s+(all|the|your)?"
    r"|system\s*:|<\s*system\s*>|\[\s*INST\s*\])",
    re.IGNORECASE,
)


@node
def security_checkpoint(node_input: dict) -> Event:
    """Security gate: scrubs PII and blocks prompt-injection before the LLM sees anything.

    Routes:
      'clean'     → llm_risk_review   (normal path)
      'injection' → human_approval    (bypasses LLM; pre-loaded with a SECURITY risk review)
    """
    description = node_input.get("description", "")
    redacted: list[str] = []

    # --- 1. PII scrubbing ---------------------------------------------------
    if _RE_SSN.search(description):
        description = _RE_SSN.sub("[REDACTED-SSN]", description)
        redacted.append("SSN")

    if _RE_CC.search(description):
        description = _RE_CC.sub("[REDACTED-CC]", description)
        redacted.append("credit-card")

    # Build the cleaned expense dict (used on both paths)
    clean_expense = {**node_input, "description": description}
    if redacted:
        clean_expense["redacted_fields"] = redacted
        print(f"[security_checkpoint] PII redacted: {redacted}")

    # --- 2. Prompt-injection detection --------------------------------------
    if _RE_INJECTION.search(description):
        print(
            "[security_checkpoint] ⚠️  Prompt injection detected — routing to human review."
        )
        # Synthesise a RiskReview so human_approval gets the same shape it
        # always expects, without touching the LLM.
        synthetic_risk: dict = {
            "risk_score": 5,
            "risk_factors": ["prompt_injection_attempt"],
            "alert_raised": True,
            "reasoning": (
                "SECURITY EVENT: The expense description contained instructions "
                "attempting to override approval rules. The LLM was never consulted. "
                "Manual review is mandatory."
            ),
        }
        return Event(
            content=to_content(
                "🚨 SECURITY EVENT: Prompt injection detected in description. "
                "Bypassing LLM — routing directly to human reviewer."
            ),
            output={"expense": clean_expense, "risk_review": synthetic_risk},
            route="injection",
            state={"security_event": True, "redacted_pii": redacted},
        )

    # --- 3. Clean path — forward to LLM reviewer ---------------------------
    return Event(
        output=clean_expense,
        route="clean",
        state={"redacted_pii": redacted},
    )


@node
async def parse_expense_event(ctx: Context, node_input: Any) -> Event:
    """Parses incoming event payload and routes based on threshold."""
    expense = parse_payload(node_input)
    amount = expense["amount"]

    # Store extracted expense in state context
    state_delta = {
        "expense": expense,
        "submitter_role": ctx.state.get("submitter_role", "employee"),
        "submitter_id": ctx.state.get("submitter_id", "Unknown"),
        "raw_text_input": ctx.state.get("raw_text_input")
    }

    if amount < settings.THRESHOLD_AMOUNT:
        print(
            f"[parse_expense_event] Amount ${amount} is under ${settings.THRESHOLD_AMOUNT}. Routing to auto_approve."
        )
        return Event(output=expense, route="auto_approve", state=state_delta)
    else:
        print(
            f"[parse_expense_event] Amount ${amount} is at or above ${settings.THRESHOLD_AMOUNT}. Routing to llm_risk_review."
        )
        # Add the pending entry to the ledger early as "pending"
        role = ctx.state.get("submitter_role", "employee")
        user_id = ctx.state.get("submitter_id", "Unknown")
        entry_payload = {
            "amount": amount,
            "currency": "USD",
            "party": expense.get("submitter") or "Unknown",
            "category": expense.get("category") or "General",
            "status": "pending",
        }
        res = call_mcp_add_entry(entry_payload, role, user_id)
        if res and "id" in res:
            state_delta["ledger_entry_id"] = res["id"]
        return Event(output=expense, route="manual_review", state=state_delta)


# Helper to add entry to SQLite Ledger Server with direct import fallback
def call_mcp_add_entry(entry: dict, role: str, user_id: str) -> dict:
    url = os.getenv("LEDGER_SERVER_URL", "http://localhost:8081")
    try:
        resp = requests.post(
            f"{url}/tools/add_entry",
            json={"entry": entry, "role": role, "user_id": user_id},
            timeout=5
        )
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        print(f"Failed to log to ledger via HTTP: {e}")
    
    try:
        from app.mcp_servers.ledger_server import storage
        return storage.add_entry(entry, role, user_id)
    except Exception as e:
        print(f"Failed to log to ledger directly: {e}")
        return {}


# Helper to update status in SQLite Ledger Server with direct import fallback
def call_mcp_update_status(entry_id: str, new_status: str, role: str) -> dict:
    url = os.getenv("LEDGER_SERVER_URL", "http://localhost:8081")
    auth_role = role if role in ("owner", "bookkeeper") else "owner"
    try:
        resp = requests.post(
            f"{url}/tools/update_status",
            json={"entry_id": entry_id, "new_status": new_status, "role": auth_role},
            timeout=5
        )
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        print(f"Failed to update ledger status via HTTP: {e}")
    
    try:
        from app.mcp_servers.ledger_server import storage
        return storage.update_status(entry_id, new_status, auth_role)
    except Exception as e:
        print(f"Failed to update ledger status directly: {e}")
        return {}



@node
async def intake_node(ctx: Context, node_input: Any) -> Event:
    """Invokes the Intake Agent to convert raw receipt/voice/text to structured draft."""
    raw_payload = {}
    if isinstance(node_input, dict):
        raw_payload = node_input
    elif isinstance(node_input, str):
        try:
            raw_payload = json.loads(node_input)
        except Exception:
            pass
    elif hasattr(node_input, "parts"):
        parts = [p.text for p in node_input.parts if hasattr(p, "text") and p.text]
        combined = " ".join(parts)
        try:
            raw_payload = json.loads(combined)
        except Exception:
            pass

    # Check if this is a raw UI submission (e.g. text_input, content_data, file_b64)
    if "content_data" in raw_payload or "text_input" in raw_payload or "file_b64" in raw_payload:
        content_data = raw_payload.get("content_data") or raw_payload.get("text_input")
        mime_type = raw_payload.get("mime_type")
        role = raw_payload.get("role") or raw_payload.get("submitter_role") or "employee"
        submitter_id = raw_payload.get("submitter_id") or "Unknown"

        if "file_b64" in raw_payload and raw_payload["file_b64"]:
            content_data = base64.b64decode(raw_payload["file_b64"])

        from app.agents.intake_agent import run_intake_agent
        draft = run_intake_agent(content_data, mime_type, role, submitter_id)
    else:
        # Pre-structured payload (e.g. from e2e tests or pubsub)
        parsed = parse_payload(node_input)
        draft = {
            "amount": parsed.get("amount"),
            "raw_amount_string": str(parsed.get("amount", "")),
            "party": parsed.get("submitter"),
            "category": parsed.get("category"),
            "date": parsed.get("date"),
            "description": parsed.get("description"),
            "confidence": "high",
            "clarification_needed": False,
            "clarification_reason": None,
            "submitter_role": raw_payload.get("role") or raw_payload.get("submitter_role") or "owner",
            "submitter_id": parsed.get("submitter") or "system"
        }

    raw_text = None
    if "content_data" in raw_payload and isinstance(raw_payload["content_data"], str):
        raw_text = raw_payload["content_data"]
    elif "text_input" in raw_payload and isinstance(raw_payload["text_input"], str):
        raw_text = raw_payload["text_input"]
    elif isinstance(node_input, str):
        raw_text = node_input

    return Event(
        output=draft,
        state={
            "submitter_role": draft.get("submitter_role", "employee"),
            "submitter_id": draft.get("submitter_id", "Unknown"),
            "raw_text_input": raw_text
        }
    )


@node
async def reconciliation_node(ctx: Context, node_input: dict) -> Event:
    """Invokes Reconciliation Agent to reconcile the draft against the ledger."""
    recon_res = run_reconciliation_agent(node_input)

    state_delta = {
        "draft": node_input,
        "reconciliation": recon_res,
        "submitter_role": ctx.state.get("submitter_role", "employee"),
        "submitter_id": ctx.state.get("submitter_id", "Unknown"),
        "raw_text_input": ctx.state.get("raw_text_input")
    }

    routing = recon_res.get("routing", "clean")
    if routing == "clean":
        # Format the draft to exactly match parse_expense_event expectations
        draft = dict(node_input)
        draft["submitter"] = draft.get("submitter_id", "Unknown")
        draft["amount"] = recon_res.get("normalized_amount") or draft.get("amount") or 0.0
        return Event(output=draft, route="clean", state=state_delta)
    else:
        # Add the pending entry to the ledger early as "needs_clarification"
        role = ctx.state.get("submitter_role", "employee")
        user_id = ctx.state.get("submitter_id", "Unknown")
        entry_payload = {
            "amount": recon_res.get("normalized_amount") or node_input.get("amount") or 0.0,
            "currency": recon_res.get("normalized_currency") or "USD",
            "party": node_input.get("party") or "Unknown",
            "category": node_input.get("category") or "General",
            "status": "needs_clarification",
        }
        res = call_mcp_add_entry(entry_payload, role, user_id)
        if res and "id" in res:
            state_delta["ledger_entry_id"] = res["id"]
        return Event(output=state_delta, route="ambiguous", state=state_delta)


@node(rerun_on_resume=True)
async def ambiguous_human_approval(ctx: Context, node_input: dict):
    """Interrupts workflow to queue ambiguous entries in the HITL admin approval queue."""
    draft = node_input["draft"]
    recon = node_input["reconciliation"]

    if not ctx.resume_inputs or "approve_expense" not in ctx.resume_inputs:
        message = (
            f"🚨 Ambiguous Expense Flagged by Reconciliation Agent ({recon.get('ambiguity_type')})\n"
            f"  • Reason: {recon.get('reasoning')}\n"
            f"  • Submitter: {draft.get('submitter_id')} ({draft.get('submitter_role')})\n"
            f"  • Amount: {draft.get('raw_amount_string')}\n"
            f"  • Party: {draft.get('party')}\n\n"
            f"Do you approve or reject this expense? (Reply 'yes' or 'no')"
        )
        yield RequestInput(interrupt_id="approve_expense", message=message)
        return

    approval = ctx.resume_inputs["approve_expense"]
    is_approved = str(approval).strip().lower() in ("yes", "y", "approve")
    route = "approved" if is_approved else "rejected"

    yield Event(content=to_content(f"Reconciliation reviewer decision recorded: {route.upper()}"))
    yield Event(
        output={
            "approved": is_approved,
            "details": {
                "amount": recon.get("normalized_amount") or draft.get("amount") or 0.0,
                "submitter": draft.get("submitter_id"),
                "category": draft.get("category") or "General",
                "description": f"RECONCILIATION FLAG ({recon.get('ambiguity_type')}): {draft.get('description')}",
                "date": draft.get("date")
            },
            "risk": {
                "risk_score": 0,
                "reasoning": f"Reconciliation resolution: {recon.get('reasoning')}"
            }
        },
        route=route
    )


@node
async def auto_approve(ctx: Context, node_input: dict) -> Event:
    """Auto-approves expenses under threshold instantly."""
    role = ctx.state.get("submitter_role", "owner")
    user_id = ctx.state.get("submitter_id", "system")

    # Send to the SQLite Ledger Server
    entry_payload = {
        "amount": node_input.get("amount"),
        "currency": "USD",
        "party": node_input.get("submitter"),
        "category": node_input.get("category"),
        "status": "approved",
    }
    call_mcp_add_entry(entry_payload, role, user_id)

    result = (
        f"Auto-Approved: Expense of ${node_input.get('amount')} submitted by "
        f"{node_input.get('submitter')} under category '{node_input.get('category')}' is approved."
    )
    log_outcome(
        node_input,
        approved=True,
        reason=f"Auto-approved (under ${settings.THRESHOLD_AMOUNT})",
    )
    return Event(
        content=to_content(result),
        output={"status": "approved", "reason": "auto_approved", "details": node_input},
    )


@node
async def llm_risk_review(ctx: Context, node_input: dict) -> Event:
    """Uses LLM to perform policy risk assessment on high-value expenses."""
    client = genai.Client()
    prompt = (
        "Analyze the following expense report for potential policy violations or risk factors:\n"
        f"  • Submitter: {node_input.get('submitter')}\n"
        f"  • Amount: ${node_input.get('amount')}\n"
        f"  • Category: {node_input.get('category')}\n"
        f"  • Date: {node_input.get('date')}\n"
        f"  • Description: {node_input.get('description')}\n\n"
        "Evaluate the request. Determine if an alert should be raised, score the overall risk on a scale of 1 to 5, "
        "list specific risk factors, and provide a clear reasoning explaining your assessment."
    )

    response = client.models.generate_content(
        model=settings.MODEL_NAME,
        contents=prompt,
        config={
            "response_mime_type": "application/json",
            "response_schema": RiskReview,
        },
    )

    review_data = json.loads(response.text)
    print(f"[llm_risk_review] Model risk assessment: {review_data}")

    combined = {"expense": node_input, "risk_review": review_data}

    # Format human-readable alert message
    alert_msg = (
        f"⚠️ LLM Risk Review Analysis Alert\n"
        f"  • Alert Raised: {review_data.get('alert_raised')}\n"
        f"  • Risk Score: {review_data.get('risk_score')}/5\n"
        f"  • Factors: {', '.join(review_data.get('risk_factors', []))}\n"
        f"  • Reasoning: {review_data.get('reasoning')}"
    )

    return Event(
        content=to_content(alert_msg),
        output=combined,
        state={"risk_review": review_data},
    )


@node(rerun_on_resume=True)
async def human_approval(ctx: Context, node_input: dict):
    """Interrupts workflow to await a manual approval decision from human reviewer."""
    expense = node_input["expense"]
    risk_review = node_input["risk_review"]

    if not ctx.resume_inputs or "approve_expense" not in ctx.resume_inputs:
        message = (
            f"🚨 Human Approval Required for Expense of ${expense.get('amount')} by {expense.get('submitter')}\n"
            f"Risk Review Assessment:\n"
            f"  • Alert Raised: {risk_review.get('alert_raised')}\n"
            f"  • Risk Score: {risk_review.get('risk_score')}/5\n"
            f"  • Reason: {risk_review.get('reasoning')}\n\n"
            f"Do you approve or reject this expense? (Reply 'yes' or 'no')"
        )
        yield RequestInput(interrupt_id="approve_expense", message=message)
        return

    approval = ctx.resume_inputs["approve_expense"]
    is_approved = str(approval).strip().lower() in ("yes", "y", "approve")
    route = "approved" if is_approved else "rejected"

    yield Event(
        content=to_content(f"Human reviewer decision recorded: {route.upper()}")
    )
    yield Event(
        output={"approved": is_approved, "details": expense, "risk": risk_review},
        route=route,
    )


@node
async def record_outcome_approved(ctx: Context, node_input: dict) -> str:
    """Logs the human-approved expense to outcome storage."""
    details = node_input["details"]
    risk = node_input["risk"]

    role = ctx.state.get("submitter_role", "owner")
    user_id = ctx.state.get("submitter_id", "system")
    ledger_entry_id = ctx.state.get("ledger_entry_id")

    if ledger_entry_id:
        call_mcp_update_status(ledger_entry_id, "approved", role)
    else:
        # Send to the SQLite Ledger Server as a new entry
        entry_payload = {
            "amount": details.get("amount"),
            "currency": "USD",
            "party": details.get("submitter"),
            "category": details.get("category"),
            "status": "approved",
        }
        call_mcp_add_entry(entry_payload, role, user_id)

    log_outcome(
        details,
        approved=True,
        reason=f"Approved by human (LLM Risk: {risk.get('risk_score')}/5)",
    )
    return f"Expense logged as APPROVED: {details.get('submitter')} - ${details.get('amount')}"


@node
async def record_outcome_rejected(ctx: Context, node_input: dict) -> str:
    """Logs the human-rejected expense to outcome storage."""
    details = node_input["details"]
    risk = node_input["risk"]

    role = ctx.state.get("submitter_role", "owner")
    user_id = ctx.state.get("submitter_id", "system")
    ledger_entry_id = ctx.state.get("ledger_entry_id")

    if ledger_entry_id:
        call_mcp_update_status(ledger_entry_id, "rejected", role)
    else:
        # Send to the SQLite Ledger Server as a new entry
        entry_payload = {
            "amount": details.get("amount"),
            "currency": "USD",
            "party": details.get("submitter"),
            "category": details.get("category"),
            "status": "rejected",
        }
        call_mcp_add_entry(entry_payload, role, user_id)

    log_outcome(
        details,
        approved=False,
        reason=f"Rejected by human (LLM Risk: {risk.get('risk_score')}/5)",
    )
    return f"Expense logged as REJECTED: {details.get('submitter')} - ${details.get('amount')}"


@node
async def record_injection_pending(ctx: Context, node_input: dict) -> Event:
    """Logs the detected prompt injection to the ledger as pending before routing to human approval."""
    expense = node_input["expense"]
    risk_review = node_input["risk_review"]
    role = ctx.state.get("submitter_role", "employee")
    user_id = ctx.state.get("submitter_id", "Unknown")

    entry_payload = {
        "amount": expense.get("amount") or 0.0,
        "currency": "USD",
        "party": expense.get("submitter") or "Unknown",
        "category": expense.get("category") or "General",
        "status": "pending",
    }
    res = call_mcp_add_entry(entry_payload, role, user_id)
    state_delta = {
        "security_event": True,
        "risk_review": risk_review,
        "expense": expense,
        "submitter_role": role,
        "submitter_id": user_id,
        "raw_text_input": ctx.state.get("raw_text_input"),
    }
    if res and "id" in res:
        state_delta["ledger_entry_id"] = res["id"]

    return Event(output=node_input, route="to_human", state=state_delta)


# Define the Graph Workflow
root_agent = Workflow(
    name="expense_approval_workflow",
    edges=[
        ("START", intake_node),
        (intake_node, reconciliation_node),
        # Reconciliation split
        Edge(from_node=reconciliation_node, to_node=security_checkpoint, route="clean"),
        Edge(from_node=reconciliation_node, to_node=ambiguous_human_approval, route="ambiguous"),
        # Ambiguous resolution routes
        Edge(from_node=ambiguous_human_approval, to_node=record_outcome_approved, route="approved"),
        Edge(from_node=ambiguous_human_approval, to_node=record_outcome_rejected, route="rejected"),
        # Security checkpoint: clean description → threshold check; injection attempt → record and then human directly
        Edge(from_node=security_checkpoint, to_node=parse_expense_event, route="clean"),
        Edge(from_node=security_checkpoint, to_node=record_injection_pending, route="injection"),
        # Log pending for injection and proceed to human approval
        (record_injection_pending, human_approval),
        # Threshold split: cheap → auto-approve; expensive → LLM risk review
        Edge(from_node=parse_expense_event, to_node=auto_approve, route="auto_approve"),
        Edge(
            from_node=parse_expense_event,
            to_node=llm_risk_review,
            route="manual_review",
        ),
        # After LLM risk review, always pause for human approval
        (llm_risk_review, human_approval),
        # Human decision routes to outcome recorders
        Edge(
            from_node=human_approval, to_node=record_outcome_approved, route="approved"
        ),
        Edge(
            from_node=human_approval, to_node=record_outcome_rejected, route="rejected"
        ),
    ],
)

app = App(
    root_agent=root_agent,
    name="expense_agent",
)
