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

import os
from datetime import datetime

import requests

from app.skills.currency_normalization import normalize_currency


def call_mcp_find_similar_party(party_name: str, role: str, user_id: str) -> list[dict]:
    """Call the MCP ledger server's find_similar_party tool via HTTP or direct SQLite fallback."""
    url = os.getenv("LEDGER_SERVER_URL", "http://localhost:8081")
    try:
        resp = requests.post(
            f"{url}/tools/find_similar_party",
            json={"party_name": party_name, "role": role, "user_id": user_id},
            timeout=2,
        )
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass

    # Fallback to importing storage directly for unit tests/local execution
    try:
        from app.mcp_servers.ledger_server import storage

        return storage.find_similar_party(party_name, role, user_id)
    except Exception:
        return []


def call_mcp_get_entries(
    role: str, user_id: str, filters: dict | None = None
) -> list[dict]:
    """Call the MCP ledger server's get_entries tool via HTTP or direct SQLite fallback."""
    url = os.getenv("LEDGER_SERVER_URL", "http://localhost:8081")
    try:
        resp = requests.post(
            f"{url}/tools/get_entries",
            json={"role": role, "user_id": user_id, "filters": filters},
            timeout=2,
        )
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass

    try:
        from app.mcp_servers.ledger_server import storage

        return storage.get_entries(role, user_id, filters)
    except Exception:
        return []


def parse_date(date_str: str | None) -> datetime | None:
    """Helper to parse a date string in YYYY-MM-DD or ISO formats."""
    if not date_str:
        return None
    # Extract prefix YYYY-MM-DD
    clean_str = date_str.strip()
    if len(clean_str) >= 10:
        ymd_part = clean_str[:10]
        try:
            return datetime.strptime(ymd_part, "%Y-%m-%d")
        except Exception:
            pass
    try:
        return datetime.fromisoformat(clean_str)
    except Exception:
        pass
    return None


def run_reconciliation_agent(draft: dict) -> dict:
    """Reconciles an intake draft against the ledger to determine if it is clean or ambiguous.

    Args:
        draft: The structured expense draft dictionary produced by the Intake Agent.

    Returns:
        dict: A dictionary containing routing, reasoning, normalized_amount,
              normalized_currency, potential_duplicate_id, and ambiguity_type.
    """
    submitter_role = draft.get("submitter_role", "employee")
    submitter_id = draft.get("submitter_id", "Unknown")

    # Step 1: Normalize currency
    raw_amount = draft.get("raw_amount_string", "")
    norm_res = normalize_currency(raw_amount, locale_hint="USD")

    if norm_res.get("error") is not None:
        return {
            "routing": "ambiguous",
            "reasoning": f"Currency normalization failed: {norm_res['error']}",
            "normalized_amount": None,
            "normalized_currency": None,
            "potential_duplicate_id": None,
            "ambiguity_type": "currency_unparseable",
        }

    norm_amount = norm_res.get("amount")
    norm_currency = norm_res.get("currency")

    # Step 2: Short-circuit if Intake Agent already flagged clarification_needed
    if draft.get("clarification_needed") is True:
        return {
            "routing": "ambiguous",
            "reasoning": f"Intake agent flagged clarification needed: {draft.get('clarification_reason')}",
            "normalized_amount": norm_amount,
            "normalized_currency": norm_currency,
            "potential_duplicate_id": None,
            "ambiguity_type": "low_extraction_confidence",
        }

    party_name = draft.get("party")
    draft_date = draft.get("date")

    # Step 3: Check for suspected duplicate
    # Criteria: same party (case-insensitive), same amount, date within 2 days.
    if party_name and norm_amount is not None:
        entries = call_mcp_get_entries(submitter_role, submitter_id)
        draft_dt = parse_date(draft_date)

        for entry in entries:
            # Check party match (case-insensitive)
            entry_party = entry.get("party", "")
            if entry_party.lower() == party_name.lower():
                # Check amount match
                if entry.get("amount") == norm_amount:
                    # Check date match within 2 days
                    entry_dt = parse_date(entry.get("created_at"))
                    if draft_dt and entry_dt:
                        day_diff = abs((draft_dt - entry_dt).days)
                        if day_diff <= 2:
                            return {
                                "routing": "ambiguous",
                                "reasoning": f"Potential duplicate detected in ledger with entry ID: {entry.get('id')}",
                                "normalized_amount": norm_amount,
                                "normalized_currency": norm_currency,
                                "potential_duplicate_id": entry.get("id"),
                                "ambiguity_type": "duplicate_suspected",
                            }

    # Step 4: Check for ambiguous party match
    # Criteria: find_similar_party returns multiple unique party names
    if party_name:
        similar_parties = call_mcp_find_similar_party(
            party_name, submitter_role, submitter_id
        )
        unique_parties = sorted(
            {item.get("party") for item in similar_parties if item.get("party")}
        )

        if len(unique_parties) > 1:
            return {
                "routing": "ambiguous",
                "reasoning": f"Ambiguous party match found. Search returned multiple parties: {', '.join(unique_parties)}",
                "normalized_amount": norm_amount,
                "normalized_currency": norm_currency,
                "potential_duplicate_id": None,
                "ambiguity_type": "party_ambiguous",
            }

    # Step 5: Clean routing
    return {
        "routing": "clean",
        "reasoning": "Expense draft is clean and ready to proceed.",
        "normalized_amount": norm_amount,
        "normalized_currency": norm_currency,
        "potential_duplicate_id": None,
        "ambiguity_type": None,
    }
