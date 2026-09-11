"""Shared LLM client — `specs/adjudicate.md` §6, `04` §7, `05` §1/§3.

Used by P11 (adjudication), P12 (characteristics) and P13 (reasoning). The
Azure adapter is deliberately NOT re-exported here: importing it pulls in the
SDK, and the one place that needs it (`run/__main__.py`) imports it directly.
"""

from nimo.llm.client import (
    CompleteFn,
    LlmBudgetExceeded,
    LlmCall,
    LlmClient,
    LlmCounter,
    LlmError,
    LlmImage,
    LlmResponse,
    LlmTruncated,
    LlmValidationError,
    cache_key,
)
from nimo.llm.config import CONFIG_PATH, LlmConfig, LlmConfigError, load_llm_config
from nimo.llm.prompts import PROMPTS_DIR, PromptError, PromptTemplate, load_prompt, render
from nimo.llm.untrusted import TAG, delimit, neutralise

__all__ = [
    "CONFIG_PATH",
    "PROMPTS_DIR",
    "TAG",
    "CompleteFn",
    "LlmBudgetExceeded",
    "LlmCall",
    "LlmClient",
    "LlmConfig",
    "LlmConfigError",
    "LlmCounter",
    "LlmError",
    "LlmImage",
    "LlmResponse",
    "LlmTruncated",
    "LlmValidationError",
    "PromptError",
    "PromptTemplate",
    "cache_key",
    "delimit",
    "load_llm_config",
    "load_prompt",
    "neutralise",
    "render",
]
