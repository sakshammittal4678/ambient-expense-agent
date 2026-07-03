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

import pytest

from app.mcp_servers.ledger_server import SQLiteLedgerStorage


@pytest.fixture
def temp_db(tmp_path) -> SQLiteLedgerStorage:
    """Fixture to provide a clean, temporary SQLiteLedgerStorage instance."""
    db_file = tmp_path / "test_ledger.db"
    return SQLiteLedgerStorage(str(db_file))


def test_invalid_role_or_user_id(temp_db):
    """Assert invalid role or user_id combo returns an empty list."""
    storage = temp_db

    # Add a valid entry first
    entry_data = {
        "amount": 100.0,
        "currency": "USD",
        "party": "Vendor A",
        "category": "Meals",
    }
    storage.add_entry(entry_data, "owner", "owner_1")

    # Invalid role
    assert storage.get_entries("invalid_role", "owner_1") == []

    # Missing user_id
    assert storage.get_entries("owner", "") == []
    assert storage.get_entries("owner", None) == []


def test_role_filtering_employee(temp_db):
    """Employee must only see their own submitted entries."""
    storage = temp_db

    emp1_id = "emp_1"
    emp2_id = "emp_2"

    entry_emp1 = {
        "amount": 50.0,
        "currency": "USD",
        "party": "Vendor A",
        "category": "Office",
    }
    entry_emp2 = {
        "amount": 75.0,
        "currency": "USD",
        "party": "Vendor B",
        "category": "Travel",
    }
    entry_owner = {
        "amount": 500.0,
        "currency": "USD",
        "party": "Vendor C",
        "category": "Bonus",
        "owner_only": True,
    }

    storage.add_entry(entry_emp1, "employee", emp1_id)
    storage.add_entry(entry_emp2, "employee", emp2_id)
    storage.add_entry(entry_owner, "owner", "owner_1")

    # emp_1 query
    entries_emp1 = storage.get_entries("employee", emp1_id)
    assert len(entries_emp1) == 1
    assert entries_emp1[0]["submitter_id"] == emp1_id
    assert entries_emp1[0]["party"] == "Vendor A"

    # emp_2 query
    entries_emp2 = storage.get_entries("employee", emp2_id)
    assert len(entries_emp2) == 1
    assert entries_emp2[0]["submitter_id"] == emp2_id
    assert entries_emp2[0]["party"] == "Vendor B"


def test_role_filtering_bookkeeper(temp_db):
    """Bookkeeper can see everything except owner_only=true."""
    storage = temp_db

    entry_normal_1 = {
        "amount": 120.0,
        "currency": "USD",
        "party": "Uber",
        "category": "Travel",
    }
    entry_normal_2 = {
        "amount": 40.0,
        "currency": "USD",
        "party": "Starbucks",
        "category": "Meals",
    }
    entry_owner_only = {
        "amount": 1500.0,
        "currency": "USD",
        "party": "Secret Vendor",
        "category": "Consulting",
        "owner_only": True,
    }

    storage.add_entry(entry_normal_1, "employee", "emp_1")
    storage.add_entry(entry_normal_2, "bookkeeper", "bk_1")
    storage.add_entry(entry_owner_only, "owner", "owner_1")

    entries = storage.get_entries("bookkeeper", "bk_1")
    assert len(entries) == 2
    # Verify owner_only is not in the list
    for entry in entries:
        assert not entry["owner_only"]
        assert entry["party"] in ("Uber", "Starbucks")


def test_role_filtering_owner(temp_db):
    """Owner can see all entries including owner_only."""
    storage = temp_db

    entry_normal = {
        "amount": 120.0,
        "currency": "USD",
        "party": "Uber",
        "category": "Travel",
    }
    entry_owner_only = {
        "amount": 1500.0,
        "currency": "USD",
        "party": "Secret Vendor",
        "category": "Consulting",
        "owner_only": True,
    }

    storage.add_entry(entry_normal, "employee", "emp_1")
    storage.add_entry(entry_owner_only, "owner", "owner_1")

    entries = storage.get_entries("owner", "owner_1")
    assert len(entries) == 2
    parties = [e["party"] for e in entries]
    assert "Uber" in parties
    assert "Secret Vendor" in parties


def test_find_similar_party(temp_db):
    """Verify role filtering on find_similar_party."""
    storage = temp_db

    entry_normal_emp1 = {
        "amount": 10.0,
        "currency": "USD",
        "party": "Office Depot",
        "category": "Office",
    }
    entry_normal_emp2 = {
        "amount": 20.0,
        "currency": "USD",
        "party": "OfficeMax",
        "category": "Office",
    }
    entry_owner_only = {
        "amount": 1000.0,
        "currency": "USD",
        "party": "Office Suite Special",
        "category": "Legal",
        "owner_only": True,
    }

    storage.add_entry(entry_normal_emp1, "employee", "emp_1")
    storage.add_entry(entry_normal_emp2, "employee", "emp_2")
    storage.add_entry(entry_owner_only, "owner", "owner_1")

    # emp_1 query: should only see Office Depot (their own), NOT OfficeMax (emp_2) or Office Suite Special (owner)
    emp1_results = storage.find_similar_party("Office", "employee", "emp_1")
    assert len(emp1_results) == 1
    assert emp1_results[0]["party"] == "Office Depot"
    assert emp1_results[0]["submitter_id"] == "emp_1"

    # emp_2 query: should only see OfficeMax, NOT Office Depot (emp_1)
    emp2_results = storage.find_similar_party("Office", "employee", "emp_2")
    assert len(emp2_results) == 1
    assert emp2_results[0]["party"] == "OfficeMax"
    assert emp2_results[0]["submitter_id"] == "emp_2"

    # Bookkeeper query: should see both non-owner_only entries (Office Depot and OfficeMax), NOT the owner_only entry
    bk_results = storage.find_similar_party("Office", "bookkeeper", "bk_1")
    assert len(bk_results) == 2
    parties = [e["party"] for e in bk_results]
    assert "Office Depot" in parties
    assert "OfficeMax" in parties
    assert "Office Suite Special" not in parties

    # Owner query: should see all three entries
    owner_results = storage.find_similar_party("Office", "owner", "owner_1")
    assert len(owner_results) == 3
    parties = [e["party"] for e in owner_results]
    assert "Office Depot" in parties
    assert "OfficeMax" in parties
    assert "Office Suite Special" in parties


def test_update_status(temp_db):
    """Verify role checks on status updates."""
    storage = temp_db

    # Standard entry
    e1 = storage.add_entry(
        {"amount": 10.0, "currency": "USD", "party": "Coffee", "category": "Meals"},
        "employee",
        "emp_1",
    )
    # Owner-only entry
    e2 = storage.add_entry(
        {
            "amount": 5000.0,
            "currency": "USD",
            "party": "Private Jet",
            "category": "Travel",
            "owner_only": True,
        },
        "owner",
        "owner_1",
    )

    # 1. Employee cannot update status
    res = storage.update_status(e1["id"], "approved", "employee")
    assert res == {}

    # 2. Bookkeeper can update standard entry
    res = storage.update_status(e1["id"], "approved", "bookkeeper")
    assert res != {}
    assert res["status"] == "approved"

    # 3. Bookkeeper CANNOT update owner-only entry
    res = storage.update_status(e2["id"], "approved", "bookkeeper")
    assert res == {}

    # 4. Owner can update owner-only entry
    res = storage.update_status(e2["id"], "approved", "owner")
    assert res != {}
    assert res["status"] == "approved"


def test_flag_for_review(temp_db):
    """Verify flag_for_review updates status to needs_clarification."""
    storage = temp_db

    entry = storage.add_entry(
        {"amount": 25.0, "currency": "USD", "party": "Gas", "category": "Travel"},
        "employee",
        "emp_1",
    )

    # Initially pending
    assert entry["status"] == "pending"

    # Flag for review
    res = storage.flag_for_review(entry["id"], "Missing receipt")
    assert res != {}
    assert res["status"] == "needs_clarification"
