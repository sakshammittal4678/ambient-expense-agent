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

from app.agents.intake_agent import run_intake_agent


def test_clean_text_extraction():
    """Verify that clean, unambiguous text extracts values successfully with high/medium confidence."""
    text = "Spent $25.50 on lunch at Starbucks on 2026-06-15"
    result = run_intake_agent(text, None, "employee", "user_1")

    assert result["submitter_role"] == "employee"
    assert result["submitter_id"] == "user_1"
    assert result["amount"] == 25.50
    assert result["raw_amount_string"] in ("$25.50", "25.50")
    assert result["party"] == "Starbucks"
    assert result["date"] == "2026-06-15"
    assert result["clarification_needed"] is False
    assert result["confidence"] in ("high", "medium")


def test_ambiguous_text_extraction():
    """Verify that ambiguous text triggers clarification needed and low confidence."""
    text = "I spent some money on food today."
    result = run_intake_agent(text, None, "bookkeeper", "user_2")

    assert result["submitter_role"] == "bookkeeper"
    assert result["submitter_id"] == "user_2"
    assert result["clarification_needed"] is True
    assert result["confidence"] == "low"
    assert result["clarification_reason"] is not None


def test_image_input_extraction():
    """Verify that image inputs are accepted and a blank/empty image triggers clarification needed."""
    # A valid 1x1 pixel black PNG in bytes
    dummy_png_bytes = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4"
        b"\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    result = run_intake_agent(dummy_png_bytes, "image/png", "owner", "user_3")

    assert result["submitter_role"] == "owner"
    assert result["submitter_id"] == "user_3"
    # A blank 1x1 image should result in low confidence and request clarification
    assert result["clarification_needed"] is True
    assert result["confidence"] == "low"
    assert result["clarification_reason"] is not None
