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

# Mock ledger entries for the demo
existing_entries = [
    {
        "id": "dup_entry_id_999",
        "amount": 120.00,
        "currency": "USD",
        "party": "Starbucks",
        "category": "Meals",
        "submitter_role": "employee",
        "submitter_id": "user@test.com",
        "status": "approved",
        "owner_only": False,
        "created_at": "2026-06-23T18:00:00Z",
    }
]

similar_parties = [{"party": "Raj Kumar"}, {"party": "Rajesh"}]

print("--- Reconciliation Agent Standalone Demo ---")

# 1. Clean Case
draft_clean = {
    "party": "Uber",
    "raw_amount_string": "$45.50",
    "date": "2026-06-23",
    "submitter_role": "employee",
    "submitter_id": "user@test.com",
    "clarification_needed": False,
}
with (
    patch("app.agents.reconciliation_agent.call_mcp_get_entries", return_value=[]),
    patch(
        "app.agents.reconciliation_agent.call_mcp_find_similar_party",
        return_value=[],
    ),
):
    print("\nCase 1: Clean Draft")
    print(run_reconciliation_agent(draft_clean))

# 2. Duplicate Suspected
draft_dup = {
    "party": "Starbucks",
    "raw_amount_string": "$120.00",
    "date": "2026-06-23",
    "submitter_role": "employee",
    "submitter_id": "user@test.com",
    "clarification_needed": False,
}
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
    print("\nCase 2: Suspected Duplicate")
    print(run_reconciliation_agent(draft_dup))

# 3. Party Ambiguous
draft_party = {
    "party": "Raj",
    "raw_amount_string": "₹500",
    "date": "2026-06-23",
    "submitter_role": "employee",
    "submitter_id": "user@test.com",
    "clarification_needed": False,
}
with (
    patch("app.agents.reconciliation_agent.call_mcp_get_entries", return_value=[]),
    patch(
        "app.agents.reconciliation_agent.call_mcp_find_similar_party",
        return_value=similar_parties,
    ),
):
    print("\nCase 3: Ambiguous Party Match")
    print(run_reconciliation_agent(draft_party))
