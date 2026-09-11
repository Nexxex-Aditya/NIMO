"""Prompt files — `config/prompts/*.md`, `04` §7, `05` §5.

`04` §7: prompts live in versioned files, never in f-strings buried in logic.
The version is the file's content hash, recorded on every answer it
produces (`05` §5's config/prompt version-skew guardrail: "which prompt
produced this output" must be answerable after the fact).

**Rendering is substitution, not formatting.** Each known placeholder is
replaced by `str.replace`; the inserted text is never re-parsed for
placeholders, so a fetched page containing the literal `{{allowed}}` cannot
splice itself into the instruction (`05` §1). An unfilled placeholder in the
rendered prompt raises rather than shipping as literal braces.
"""

import hashlib
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parents[3] / "config" / "prompts"
_SECTION_BREAK = "\n---\n"
_PLACEHOLDER = re.compile(r"\{\{[a-z_]+\}\}")


class PromptError(Exception):
    """A prompt file is missing, malformed, or was rendered incompletely."""


@dataclass(frozen=True)
class PromptTemplate:
    name: str
    system: str
    user_template: str
    prompt_hash: str  # sha256 of the file bytes — the prompt's version


@lru_cache(maxsize=8)
def load_prompt(name: str, directory: Path = PROMPTS_DIR) -> PromptTemplate:
    """`<directory>/<name>.md`: a system section, a `---` line, a user
    template. A single-section file is a user template with an empty system
    prompt (the JSON-retry suffix is one)."""
    path = directory / f"{name}.md"
    if not path.exists():
        raise PromptError(f"{path} not found — `04` §7 keeps every prompt in config/prompts/")
    raw = path.read_bytes()
    text = raw.decode("utf-8")
    if _SECTION_BREAK in text:
        system, user = text.split(_SECTION_BREAK, 1)
    else:
        system, user = "", text
    if not user.strip():
        raise PromptError(f"{path}: the user template section is empty")
    return PromptTemplate(
        name=name,
        system=system.strip(),
        user_template=user.strip(),
        prompt_hash=hashlib.sha256(raw).hexdigest(),
    )


def render(template: str, **fields: str) -> str:
    """Substitute `{{name}}` placeholders. Inserted values are not re-scanned.

    Checked against the *template*, not the rendered text: a placeholder the
    template has and the caller did not supply raises, and a placeholder
    token that arrives inside a value (untrusted page text) is neither
    substituted nor mistaken for one we forgot.
    """
    wanted = set(_PLACEHOLDER.findall(template))
    supplied = {"{{" + name + "}}" for name in fields}
    missing = sorted(wanted - supplied)
    if missing:
        raise PromptError(f"unfilled placeholder(s) {missing} in the template")
    unknown = sorted(supplied - wanted)
    if unknown:
        raise PromptError(f"placeholder(s) {unknown} are not in the template")
    # ONE pass over the template. Sequential `str.replace` calls would let a
    # token arriving inside an earlier value be substituted by a later pass;
    # a single regex substitution only ever sees the template's own tokens.
    return _PLACEHOLDER.sub(lambda match: fields[match.group(0)[2:-2]], template)
