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

test_cases = [
    ("₹500", "USD"),
    ("Rs. 500/-", "USD"),
    ("five hundred rupees", "USD"),
    ("$45.50", "USD"),
    ("$45.50", "CAD"),
    ("forty five dollars", "USD"),
    ("some money", "USD"),
]

print("--- Running Currency Normalization Skill Demo ---")
for raw, hint in test_cases:
    res = normalize_currency(raw, locale_hint=hint)
    print(f"Input: {raw!r:<22} | Locale: {hint:<3} | Output: {res}")
