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

from unittest.mock import patch

from app.agents.reconciliation_agent import run_reconciliation_agent


def test_reconciliation_clean():
    """Verify that a clean draft with no duplicate or party ambiguity routes to clean."""
    draft = {
        "amount": 45.50,
        "raw_amount_string": "$45.50",
        "party": "Starbucks",
        "category": "Meals",
        "date": "2026-06-23",
        "confidence": "high",
        "submitter_role": "employee",
        "submitter_id": "emp_1",
        "clarification_needed": False,
        "clarification_reason": None,
    }

    with (
        patch("app.agents.reconciliation_agent.call_mcp_get_entries", return_value=[]),
        patch(
            "app.agents.reconciliation_agent.call_mcp_find_similar_party",
            return_value=[],
        ),
    ):
        res = run_reconciliation_agent(draft)
        assert res["routing"] == "clean"
        assert res["normalized_amount"] == 45.50
        assert res["normalized_currency"] == "USD"
        assert res["potential_duplicate_id"] is None
        assert res["ambiguity_type"] is None


def test_reconciliation_duplicate_suspected():
    """Verify duplicate checking flags matching entries in the ledger within 2 days."""
    draft = {
        "amount": 45.50,
        "raw_amount_string": "$45.50",
        "party": "Starbucks",
        "category": "Meals",
        "date": "2026-06-23",
        "confidence": "high",
        "submitter_role": "employee",
        "submitter_id": "emp_1",
        "clarification_needed": False,
        "clarification_reason": None,
    }

    # Matches Starbucks, $45.50, and date within 2 days (June 24 is 1 day difference)
    existing_entries = [
        {
            "id": "existing_entry_123",
            "amount": 45.50,
            "currency": "USD",
            "party": "Starbucks",
            "category": "Meals",
            "submitter_role": "employee",
            "submitter_id": "emp_1",
            "status": "approved",
            "owner_only": False,
            "created_at": "2026-06-24",
            "updated_at": "2026-06-24",
        }
    ]

    with (
        patch(
            "app.agents.reconciliation_agent.call_mcp_get_entries",
            return_value=existing_entries,
        ),
        patch(
            "app.agents.reconciliation_agent.call_mcp_find_similar_party",
            return_value=[],
        ),
    ):
        res = run_reconciliation_agent(draft)
        assert res["routing"] == "ambiguous"
        assert res["ambiguity_type"] == "duplicate_suspected"
        assert res["potential_duplicate_id"] == "existing_entry_123"


def test_reconciliation_party_ambiguous():
    """Verify that multiple matching parties triggers a party_ambiguous routing."""
    draft = {
        "amount": 500.0,
        "raw_amount_string": "₹500",
        "party": "Raj",
        "category": "Office",
        "date": "2026-06-23",
        "confidence": "high",
        "submitter_role": "employee",
        "submitter_id": "emp_1",
        "clarification_needed": False,
        "clarification_reason": None,
    }

    # Returns Raj Kumar and Rajesh - ambiguous
    similar_parties = [{"party": "Raj Kumar"}, {"party": "Rajesh"}]

    with (
        patch("app.agents.reconciliation_agent.call_mcp_get_entries", return_value=[]),
        patch(
            "app.agents.reconciliation_agent.call_mcp_find_similar_party",
            return_value=similar_parties,
        ),
    ):
        res = run_reconciliation_agent(draft)
        assert res["routing"] == "ambiguous"
        assert res["ambiguity_type"] == "party_ambiguous"
        assert res["potential_duplicate_id"] is None


def test_reconciliation_currency_unparseable():
    """Verify unparseable raw amounts trigger currency_unparseable routing."""
    draft = {
        "amount": None,
        "raw_amount_string": "some money",
        "party": "Uber",
        "category": "Travel",
        "date": "2026-06-23",
        "confidence": "low",
        "submitter_role": "employee",
        "submitter_id": "emp_1",
        "clarification_needed": False,
        "clarification_reason": None,
    }

    res = run_reconciliation_agent(draft)
    assert res["routing"] == "ambiguous"
    assert res["ambiguity_type"] == "currency_unparseable"
    assert res["normalized_amount"] is None


def test_reconciliation_low_extraction_confidence():
    """Verify clarification_needed from Intake Agent short-circuits to ambiguous."""
    draft = {
        "amount": 45.50,
        "raw_amount_string": "$45.50",
        "party": "Starbucks",
        "category": "Meals",
        "date": "2026-06-23",
        "confidence": "low",
        "submitter_role": "employee",
        "submitter_id": "emp_1",
        "clarification_needed": True,
        "clarification_reason": "Receipt was blurry and hard to read.",
    }

    res = run_reconciliation_agent(draft)
    assert res["routing"] == "ambiguous"
    assert res["ambiguity_type"] == "low_extraction_confidence"
    assert res["normalized_amount"] == 45.50
