"""Delimiting untrusted content for prompts — `05` §1.

`05` §1: anything that originated from a webpage is untrusted data. It is
never concatenated into a prompt as if it were part of the instruction; it
goes in a clearly delimited, labelled block, preceded by an instruction that
imperative language inside it is not a command.

This module does the delimiting. The instruction itself is prompt text and
lives in `config/prompts/*.md` with the rest of the prompt (`04` §7) — a test
asserts the system prompt names the tag and precedes any evidence.
"""

TAG = "untrusted_evidence"

# A lookalike bracket. Content that tries to close its own block — or open a
# new one — has its `<` swapped for this so the tag structure cannot be forged
# from inside. `‹` is visibly a bracket to the model and to a human reading
# the trace, and it is never what the delimiter itself uses.
_NEUTRAL_OPEN = "‹"


def delimit(text: str, *, candidate: int, field: str) -> str:
    """Wrap one untrusted value in its labelled block.

    `candidate` and `field` are ours — the index into the pack and the name of
    the evidence field — so they are trusted and appear on the tag. `text` is
    the page's, and cannot close or reopen the block.
    """
    return f'<{TAG} candidate="{candidate}" field="{field}">\n{neutralise(text)}\n</{TAG}>'


def neutralise(text: str) -> str:
    """Make `text` unable to forge or close a delimiter block.

    Case-insensitive on the tag name, and applied to both the opening and the
    closing form: `</UNTRUSTED_EVIDENCE>` and `<untrusted_evidence ...>` are
    both attempts to step outside the block.
    """
    out: list[str] = []
    lowered = text.lower()
    open_marker = f"<{TAG}"
    close_marker = f"</{TAG}"
    index = 0
    while index < len(text):
        if lowered.startswith(close_marker, index) or lowered.startswith(open_marker, index):
            out.append(_NEUTRAL_OPEN)
            index += 1
            continue
        out.append(text[index])
        index += 1
    return "".join(out)
