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

import json
import os
from typing import Literal

import dotenv
from google import genai
from google.genai import types
from pydantic import BaseModel, Field

# Load environment variables from .env
dotenv.load_dotenv()


class IntakeExtraction(BaseModel):
    """Pydantic schema for structured output from the Intake Agent."""

    amount: float | None = Field(
        None,
        description="The extracted numeric amount of the expense. MUST be a float or null. Leave null if the amount is missing, ambiguous, or if you have low confidence in the value.",
    )
    raw_amount_string: str = Field(
        ...,
        description="The original unparsed currency/amount text from the input exactly as written (e.g. '₹500', '$10.50', '50 EUR', 'ten dollars'). Do NOT normalize or convert the currency. If no amount is mentioned or visible, return an empty string.",
    )
    party: str | None = Field(
        None,
        description="The party/vendor name (e.g. Starbucks, Uber). Leave null if missing, ambiguous, or if you have low confidence in the value.",
    )
    category: str | None = Field(
        None,
        description="The best guess category for the expense (e.g. Travel, Meals, Office, software). Leave null if completely missing or ambiguous.",
    )
    date: str | None = Field(
        None,
        description="The date of the expense (YYYY-MM-DD format if possible, e.g., '2026-06-06'). Leave null if missing, ambiguous, or if you have low confidence in the value.",
    )
    description: str = Field(
        ...,
        description="A brief description or summary of what was purchased.",
    )
    confidence: Literal["high", "medium", "low"] = Field(
        ...,
        description="Confidence rating of the extraction. Set to 'low' if any key fields (amount, party, date) are missing, ambiguous, or hard to read/hear. Set to 'high' or 'medium' if you are sure about the values.",
    )
    clarification_needed: bool = Field(
        ...,
        description="Set to True if confidence is 'low' or if critical fields (amount, party, date) are ambiguous, missing, or require clarification.",
    )
    clarification_reason: str | None = Field(
        None,
        description="The explanation of why clarification is needed, listing the specific ambiguous or missing fields. Leave null if clarification_needed is False.",
    )


SYSTEM_INSTRUCTION = """
You are an expert expense parsing assistant. Your task is to extract details from an expense submission (which may be a text description, an image of a receipt, or an audio voice note).

You MUST extract the fields according to the response schema.
Remember:
- Be conservative. If you are unsure or if key fields (amount, party, date) are missing, set confidence to 'low', clarification_needed to True, and explain why in clarification_reason.
- Prefer leaving a field null rather than making a wrong guess if confidence is 'low'.
- Do NOT guess dates or amounts if they are not explicitly present or visible.
"""


def run_intake_agent(
    content_data: bytes | str,
    mime_type: str | None,
    submitter_role: str,
    submitter_id: str,
) -> dict:
    """Invokes the Gemini model to parse text, image, or audio input into structured expense schema."""
    # Use gemini-3.1-flash-lite which is multimodal and supports structured JSON outputs
    model_name = os.getenv("INTAKE_MODEL_NAME", "gemini-3.1-flash-lite")
    client = genai.Client()

    contents = []
    if isinstance(content_data, bytes):
        part = types.Part.from_bytes(
            data=content_data, mime_type=mime_type or "application/octet-stream"
        )
        contents.append(part)
        contents.append("Please extract the expense details from this file.")
    else:
        contents.append(content_data)
        contents.append("Please extract the expense details from this text.")

    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_INSTRUCTION,
        response_mime_type="application/json",
        response_schema=IntakeExtraction,
        temperature=0.1,
    )

    try:
        response = client.models.generate_content(
            model=model_name,
            contents=contents,
            config=config,
        )
        # Parse the JSON response
        result = json.loads(response.text)
    except Exception as e:
        # Fallback dictionary in case of API failure
        result = {
            "amount": None,
            "raw_amount_string": "",
            "party": None,
            "category": None,
            "date": None,
            "description": f"Failed to run intake agent: {e}",
            "confidence": "low",
            "clarification_needed": True,
            "clarification_reason": f"API Error: {e}",
        }

    # Add submitter role and ID as requested
    result["submitter_role"] = submitter_role
    result["submitter_id"] = submitter_id

    return result
