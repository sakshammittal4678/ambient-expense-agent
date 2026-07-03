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

from app.skills.currency_normalization import normalize_currency


def test_currency_normalization_symbols():
    # 1. Symbol prefixed INR
    res = normalize_currency("₹500")
    assert res["amount"] == 500.0
    assert res["currency"] == "INR"
    assert res["error"] is None

    # 2. Symbol prefixed USD
    res = normalize_currency("$45.50")
    assert res["amount"] == 45.50
    assert res["currency"] == "USD"
    assert res["error"] is None


def test_currency_normalization_suffix():
    # 3. Trailing slash-dash suffix
    res = normalize_currency("500/-", locale_hint="INR")
    assert res["amount"] == 500.0
    assert res["currency"] == "INR"
    assert res["error"] is None

    # 4. Rs. prefix with trailing slash-dash suffix
    res = normalize_currency("Rs. 500/-")
    assert res["amount"] == 500.0
    assert res["currency"] == "INR"
    assert res["error"] is None


def test_currency_normalization_spelled_out():
    # 5. Spelled-out English INR
    res = normalize_currency("five hundred rupees")
    assert res["amount"] == 500.0
    assert res["currency"] == "INR"
    assert res["error"] is None

    # 6. Spelled-out English USD
    res = normalize_currency("forty five dollars")
    assert res["amount"] == 45.0
    assert res["currency"] == "USD"
    assert res["error"] is None


def test_currency_normalization_locale_hints():
    # 7. Ambiguous symbol resolved with locale_hint CAD
    res = normalize_currency("$45.50", locale_hint="CAD")
    assert res["amount"] == 45.50
    assert res["currency"] == "CAD"
    assert res["error"] is None

    # 8. Pure number resolved with locale_hint INR
    res = normalize_currency("250", locale_hint="INR")
    assert res["amount"] == 250.0
    assert res["currency"] == "INR"
    assert res["error"] is None


def test_currency_normalization_failures():
    # 9. No amount/currency failure
    res = normalize_currency("some money")
    assert res["amount"] is None
    assert res["currency"] is None
    assert res["error"] is not None

    # 10. Only currency name without number
    res = normalize_currency("rupees")
    assert res["amount"] is None
    assert res["currency"] is None
    assert res["error"] is not None
