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

from pydantic import BaseModel


class Settings(BaseModel):
    """Configuration settings for the ambient expense agent."""

    # Under this amount, expenses are auto-approved instantly.
    # At or above this amount, an LLM review and human approval are required.
    THRESHOLD_AMOUNT: float = float(os.getenv("THRESHOLD_AMOUNT", "100.0"))

    # The Gemini model to use for the risk review process.
    MODEL_NAME: str = os.getenv("MODEL_NAME", "gemini-3.1-flash-lite")


settings = Settings()
