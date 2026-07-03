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
import sqlite3
import uuid
from datetime import UTC, datetime

import uvicorn
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel
from starlette.responses import JSONResponse


class Settings(BaseModel):
    """Configuration settings for the ledger server."""

    DB_PATH: str = os.getenv("LEDGER_DB_PATH", "ledger.db")


settings = Settings()


class LedgerStorage:
    """Interface for ledger storage backends."""

    def add_entry(self, entry: dict, role: str, user_id: str) -> dict:
        raise NotImplementedError

    def get_entries(
        self, role: str, user_id: str, filters: dict | None = None
    ) -> list[dict]:
        raise NotImplementedError

    def find_similar_party(
        self, party_name: str, role: str, user_id: str
    ) -> list[dict]:
        raise NotImplementedError

    def flag_for_review(self, entry_id: str, reason: str) -> dict:
        raise NotImplementedError

    def update_status(self, entry_id: str, new_status: str, role: str) -> dict:
        raise NotImplementedError


class SQLiteLedgerStorage(LedgerStorage):
    """SQLite implementation of LedgerStorage."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        # Ensure directories exist
        db_dir = os.path.dirname(self.db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS entries (
                id TEXT PRIMARY KEY,
                amount REAL NOT NULL,
                currency TEXT NOT NULL,
                party TEXT NOT NULL,
                category TEXT NOT NULL,
                submitter_role TEXT NOT NULL,
                submitter_id TEXT NOT NULL,
                status TEXT NOT NULL,
                owner_only INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        conn.commit()
        conn.close()

    def _row_to_dict(self, row: tuple) -> dict:
        return {
            "id": row[0],
            "amount": row[1],
            "currency": row[2],
            "party": row[3],
            "category": row[4],
            "submitter_role": row[5],
            "submitter_id": row[6],
            "status": row[7],
            "owner_only": bool(row[8]),
            "created_at": row[9],
            "updated_at": row[10],
        }

    def add_entry(self, entry: dict, role: str, user_id: str) -> dict:
        if role not in ("owner", "bookkeeper", "employee") or not user_id:
            return {}

        entry_id = str(uuid.uuid4())
        now = datetime.now(UTC).isoformat()

        amount = float(entry.get("amount", 0.0))
        currency = str(entry.get("currency", "USD"))
        party = str(entry.get("party", ""))
        category = str(entry.get("category", ""))
        status = str(entry.get("status", "pending"))
        owner_only = int(bool(entry.get("owner_only", False)))

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO entries (
                id, amount, currency, party, category, submitter_role,
                submitter_id, status, owner_only, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry_id,
                amount,
                currency,
                party,
                category,
                role,
                user_id,
                status,
                owner_only,
                now,
                now,
            ),
        )
        conn.commit()

        cursor.execute("SELECT * FROM entries WHERE id = ?", (entry_id,))
        row = cursor.fetchone()
        conn.close()

        if row:
            return self._row_to_dict(row)
        return {}

    def get_entries(
        self, role: str, user_id: str, filters: dict | None = None
    ) -> list[dict]:
        if role not in ("owner", "bookkeeper", "employee") or not user_id:
            return []

        query = "SELECT * FROM entries WHERE 1=1"
        params = []

        # Apply role-based security filters
        if role == "employee":
            query += " AND submitter_id = ?"
            params.append(user_id)
        elif role == "bookkeeper":
            query += " AND owner_only = 0"
        elif role == "owner":
            pass

        if filters:
            if "status" in filters:
                query += " AND status = ?"
                params.append(filters["status"])
            if "category" in filters:
                query += " AND category = ?"
                params.append(filters["category"])
            if "party" in filters:
                query += " AND party = ?"
                params.append(filters["party"])
            if "submitter_id" in filters:
                if role != "employee":
                    query += " AND submitter_id = ?"
                    params.append(filters["submitter_id"])

        query += " ORDER BY created_at DESC"

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()

        return [self._row_to_dict(r) for r in rows]

    def find_similar_party(
        self, party_name: str, role: str, user_id: str
    ) -> list[dict]:
        if role not in ("owner", "bookkeeper", "employee") or not user_id:
            return []

        query = "SELECT * FROM entries WHERE party LIKE ?"
        params = [f"%{party_name}%"]

        if role == "employee":
            query += " AND submitter_id = ?"
            params.append(user_id)
        elif role == "bookkeeper":
            query += " AND owner_only = 0"
        elif role == "owner":
            pass

        query += " ORDER BY created_at DESC"

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()

        return [self._row_to_dict(r) for r in rows]

    def flag_for_review(self, entry_id: str, reason: str) -> dict:
        now = datetime.now(UTC).isoformat()

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Check if entry exists first
        cursor.execute("SELECT * FROM entries WHERE id = ?", (entry_id,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return {}

        cursor.execute(
            "UPDATE entries SET status = 'needs_clarification', updated_at = ? WHERE id = ?",
            (now, entry_id),
        )
        conn.commit()

        cursor.execute("SELECT * FROM entries WHERE id = ?", (entry_id,))
        row = cursor.fetchone()
        conn.close()

        if row:
            return self._row_to_dict(row)
        return {}

    def update_status(self, entry_id: str, new_status: str, role: str) -> dict:
        if role not in ("owner", "bookkeeper"):
            return {}

        now = datetime.now(UTC).isoformat()

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Check if entry exists and permissions match
        cursor.execute("SELECT * FROM entries WHERE id = ?", (entry_id,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return {}

        owner_only = bool(row[8])
        if owner_only and role != "owner":
            conn.close()
            return {}

        cursor.execute(
            "UPDATE entries SET status = ?, updated_at = ? WHERE id = ?",
            (new_status, now, entry_id),
        )
        conn.commit()

        cursor.execute("SELECT * FROM entries WHERE id = ?", (entry_id,))
        row = cursor.fetchone()
        conn.close()

        if row:
            return self._row_to_dict(row)
        return {}


storage = SQLiteLedgerStorage(settings.DB_PATH)

mcp = FastMCP("LedgerServer")


@mcp.tool()
def add_entry(entry: dict, role: str, user_id: str) -> dict:
    """Add a new entry to the expense ledger.

    Args:
        entry: Dict containing amount, currency, party, category, status, and owner_only.
        role: Submitter role ('owner', 'bookkeeper', or 'employee').
        user_id: Submitter user identifier.
    """
    return storage.add_entry(entry, role, user_id)


@mcp.tool()
def get_entries(role: str, user_id: str, filters: dict | None = None) -> list[dict]:
    """Retrieve filtered entries from the expense ledger based on user role and criteria.

    Args:
        role: Submitter role ('owner', 'bookkeeper', or 'employee').
        user_id: Submitter user identifier.
        filters: Optional dictionary containing filters like status, category, party.
    """
    return storage.get_entries(role, user_id, filters)


@mcp.tool()
def find_similar_party(party_name: str, role: str, user_id: str) -> list[dict]:
    """Find entries associated with similar party names.

    Args:
        party_name: The name or partial name of the party to find.
        role: The role requesting the search.
        user_id: The identifier of the user requesting search.
    """
    return storage.find_similar_party(party_name, role, user_id)


@mcp.tool()
def flag_for_review(entry_id: str, reason: str) -> dict:
    """Flag an entry for review, setting its status to needs_clarification.

    Args:
        entry_id: The unique identifier of the entry.
        reason: The reason for flagging the entry.
    """
    return storage.flag_for_review(entry_id, reason)


@mcp.tool()
def update_status(entry_id: str, new_status: str, role: str) -> dict:
    """Update the status of a specific entry in the ledger.

    Args:
        entry_id: The unique identifier of the entry.
        new_status: The new status ('pending', 'approved', 'rejected', 'needs_clarification').
        role: The role requesting the update.
    """
    return storage.update_status(entry_id, new_status, role)


# Expose Starlette ASGI application for streamable HTTP transport
app = mcp.streamable_http_app()


async def http_add_entry(request):
    body = await request.json()
    result = storage.add_entry(
        body.get("entry", {}), body.get("role", ""), body.get("user_id", "")
    )
    return JSONResponse(result)


async def http_get_entries(request):
    body = await request.json()
    result = storage.get_entries(
        body.get("role", ""), body.get("user_id", ""), body.get("filters")
    )
    return JSONResponse(result)


async def http_find_similar_party(request):
    body = await request.json()
    result = storage.find_similar_party(
        body.get("party_name", ""), body.get("role", ""), body.get("user_id", "")
    )
    return JSONResponse(result)


async def http_flag_for_review(request):
    body = await request.json()
    result = storage.flag_for_review(body.get("entry_id", ""), body.get("reason", ""))
    return JSONResponse(result)


async def http_update_status(request):
    body = await request.json()
    result = storage.update_status(
        body.get("entry_id", ""), body.get("new_status", ""), body.get("role", "")
    )
    return JSONResponse(result)


app.add_route("/tools/add_entry", http_add_entry, methods=["POST"])
app.add_route("/tools/get_entries", http_get_entries, methods=["POST"])
app.add_route("/tools/find_similar_party", http_find_similar_party, methods=["POST"])
app.add_route("/tools/flag_for_review", http_flag_for_review, methods=["POST"])
app.add_route("/tools/update_status", http_update_status, methods=["POST"])


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    uvicorn.run("app.mcp_servers.ledger_server:app", host="0.0.0.0", port=port)
