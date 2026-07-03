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
import re

import dotenv
from google import genai
from google.adk.tools import FunctionTool
from google.genai import types
from pydantic import BaseModel, Field

# Load environment variables from .env
dotenv.load_dotenv()


class CurrencyNormalizationResult(BaseModel):
    """Pydantic model for structured output from currency normalization."""

    amount: float | None = Field(
        None, description="The normalized numeric amount as a float."
    )
    currency: str | None = Field(
        None, description="The ISO 4217 currency code (e.g. USD, INR)."
    )
    error: str | None = Field(
        None, description="Error description if parsing fails or is ambiguous."
    )


def get_currency_from_symbol(symbol: str, locale_hint: str) -> str:
    """Map currency symbols and keywords to ISO 4217 currency codes."""
    s = symbol.strip().upper()
    if s == "$":
        # Dollar symbol depends on locale hint
        return locale_hint.upper()
    if s in ("₹", "RS.", "RS", "INR", "RUPEES", "RUPEE"):
        return "INR"
    if s in ("USD", "DOLLARS", "DOLLAR", "BUCKS"):
        return "USD"
    if s in ("CAD", "AUD", "EUR", "GBP", "JPY"):
        return s
    return locale_hint.upper()


def normalize_currency(raw_amount_string: str, locale_hint: str = "USD") -> dict:
    """Normalizes raw amount text into float amount and ISO 4217 currency code.

    Args:
        raw_amount_string: The original raw string representing amount (e.g., "$45.50", "₹500/-").
        locale_hint: Optional currency locale context if the symbol is ambiguous (default: "USD").

    Returns:
        dict: A dictionary containing amount (float | None), currency (str | None), and error (str | None).
    """
    s = raw_amount_string.strip()
    if not s:
        return {
            "amount": None,
            "currency": None,
            "error": "Input amount string is empty.",
        }

    # Clean up trailing /-
    if s.endswith("/-"):
        s = s[:-2].strip()

    # Regex 1: Just a pure numeric string (e.g. 500, 45.50)
    number_pattern = r"^[+-]?\d+(?:\.\d+)?$"
    if re.match(number_pattern, s):
        try:
            return {
                "amount": float(s),
                "currency": locale_hint.upper(),
                "error": None,
            }
        except ValueError:
            pass

    # Regex 2: Prefix symbol (e.g. $45.50, ₹500, Rs. 100)
    prefix_pattern = r"(?i)^(\$|₹|Rs\.?|INR|USD|CAD|AUD)\s*([+-]?\d+(?:\.\d+)?)$"
    m = re.match(prefix_pattern, s)
    if m:
        symbol = m.group(1)
        try:
            amount = float(m.group(2))
            currency = get_currency_from_symbol(symbol, locale_hint)
            return {"amount": amount, "currency": currency, "error": None}
        except ValueError:
            pass

    # Regex 3: Suffix symbol/code (e.g. 500 INR, 45.50 dollars)
    suffix_pattern = r"(?i)^([+-]?\d+(?:\.\d+)?)\s*(\$|₹|Rs\.?|INR|USD|CAD|AUD|dollars?|rupees?|bucks)?$"
    m = re.match(suffix_pattern, s)
    if m:
        try:
            amount = float(m.group(1))
            symbol = m.group(2)
            currency = (
                get_currency_from_symbol(symbol, locale_hint)
                if symbol
                else locale_hint.upper()
            )
            return {"amount": amount, "currency": currency, "error": None}
        except ValueError:
            pass

    # If simple regex parsing fails, delegate to Gemini model for text representation/spelled-out values
    model_name = os.getenv("MODEL_NAME", "gemini-3.1-flash-lite")
    client = genai.Client()

    prompt = (
        "You are an expert currency normalization assistant.\n"
        "Your task is to parse a raw string representing a currency amount and extract the numeric value and the ISO 4217 currency code.\n"
        "Format the response as a JSON object matching this schema:\n"
        '{ "amount": float | null, "currency": str | null, "error": str | null }\n\n'
        "Rules:\n"
        "1. Extract the numeric value of the amount. Convert spelled out text (e.g., 'five hundred', 'ten point five') to a float.\n"
        "2. Resolve the currency code (e.g. 'rupees' -> 'INR', 'dollars' -> 'USD').\n"
        f"3. Use the locale hint '{locale_hint}' to resolve ambiguous symbols like '$' (e.g., if locale hint is 'CAD', then '$' is 'CAD'; if 'USD', '$' is 'USD'). If no currency is mentioned, default to '{locale_hint}'.\n"
        "4. If the input does not specify any number/amount or is too ambiguous (e.g. 'some money', 'rupees'), set amount to null, currency to null, and explain the failure in the 'error' field.\n"
        "5. Do NOT guess if you are not confident. Set error accordingly.\n\n"
        f'Input raw string: "{raw_amount_string}"\n'
        f'Locale hint: "{locale_hint}"\n'
    )

    config = types.GenerateContentConfig(
        system_instruction="Normalize the currency string to structured JSON.",
        response_mime_type="application/json",
        response_schema=CurrencyNormalizationResult,
        temperature=0.0,
    )

    try:
        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
            config=config,
        )
        result = json.loads(response.text)
        return result
    except Exception as e:
        return {
            "amount": None,
            "currency": None,
            "error": f"Failed to normalize with model: {e}",
        }


# Register this function as a reusable ADK tool
normalize_currency_tool = FunctionTool(func=normalize_currency)
