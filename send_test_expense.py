"""
send_test_expense.py - sends a $150 test expense to the running ADK playground
and streams back the server-sent events so you can see the workflow steps.
"""

import json
import sys

import requests

# Force UTF-8 output so agent emoji/unicode in responses don't crash Windows terminals
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore

BASE_URL = "http://localhost:8000"
APP_NAME = "expense_agent"
USER_ID = "test_user"

EXPENSE = {
    "amount": 150.0,
    "submitter": "alice@company.com",
    "category": "software",
    "description": "IDE License",
    "date": "2026-06-06",
}


def main():
    # 1. Create session
    r = requests.post(
        f"{BASE_URL}/apps/{APP_NAME}/users/{USER_ID}/sessions",
        json={"state": {}},
        timeout=10,
    )
    r.raise_for_status()
    session_id = r.json()["id"]
    print(f"[OK] Session created: {session_id}\n")

    # 2. Send the expense as a user message and stream the response
    payload = {
        "app_name": APP_NAME,
        "user_id": USER_ID,
        "session_id": session_id,
        "new_message": {
            "role": "user",
            "parts": [{"text": json.dumps(EXPENSE)}],
        },
    }

    print("-> Sending expense payload ...\n")
    with requests.post(
        f"{BASE_URL}/run_sse", json=payload, stream=True, timeout=60
    ) as resp:
        resp.raise_for_status()
        for raw in resp.iter_lines():
            if not raw:
                continue
            line = raw.decode() if isinstance(raw, bytes) else raw
            if not line.startswith("data:"):
                continue
            data_str = line[5:].strip()
            if not data_str or data_str == "[DONE]":
                break
            try:
                ev = json.loads(data_str)
                # Print useful fields only
                author = ev.get("author", "")
                content = ev.get("content", {})
                parts = content.get("parts", []) if isinstance(content, dict) else []
                for p in parts:
                    txt = p.get("text", "")
                    if txt:
                        print(f"[{author}] {txt}\n")
                # Detect HITL pause
                actions = ev.get("actions", {})
                if actions.get("requested_auth_configs") or ev.get("interrupted"):
                    print(
                        "[PAUSE] Workflow paused -- open http://localhost:8000 and reply yes/no in the chat.\n"
                    )
                    break
            except json.JSONDecodeError:
                print(line)

    print(
        f"\nOpen http://localhost:8000, select app 'expense_agent', session {session_id}"
    )
    print("Type  yes  to approve or  no  to reject.")


if __name__ == "__main__":
    main()
