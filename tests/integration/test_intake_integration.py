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

from fastapi.testclient import TestClient

from expense_agent.fast_api_app import app

client = TestClient(app)


def test_api_intake_text_integration():
    """Test the /api/intake endpoint end-to-end with raw text input."""
    response = client.post(
        "/api/intake",
        data={
            "role": "employee",
            "submitter_id": "integration_user_text",
            "text_input": "Spent $12.99 at McDonald's on 2026-06-20 for lunch",
        },
    )
    assert response.status_code == 200
    data = response.json()

    assert data["submitter_role"] == "employee"
    assert data["submitter_id"] == "integration_user_text"
    assert data["amount"] == 12.99
    assert data["party"] == "McDonald's"
    assert data["date"] == "2026-06-20"
    assert data["clarification_needed"] is False
    assert data["confidence"] in ("high", "medium")


def test_api_intake_image_integration():
    """Test the /api/intake endpoint end-to-end with an uploaded receipt image."""
    dummy_png_bytes = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4"
        b"\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )

    response = client.post(
        "/api/intake",
        data={
            "role": "bookkeeper",
            "submitter_id": "integration_user_image",
        },
        files={
            "file": ("receipt.png", dummy_png_bytes, "image/png"),
        },
    )
    assert response.status_code == 200
    data = response.json()

    assert data["submitter_role"] == "bookkeeper"
    assert data["submitter_id"] == "integration_user_image"
    assert data["clarification_needed"] is True
    assert data["confidence"] == "low"
    assert data["clarification_reason"] is not None
