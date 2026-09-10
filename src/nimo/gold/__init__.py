"""P4 hand-labelled URL gold set — `specs/gold.md`.

The measurement instrument for L3/L4 (`03` §6). There is no URL ground truth
in the dataset (`01` §6), so this file is the only thing stage-1 selection can
ever be scored against.
"""

from nimo.gold.sample import modules_covered, stratify_by_module
from nimo.gold.store import GOLD_PATH, GoldSetError, labelled_correct, load_gold, write_gold

__all__ = [
    "GOLD_PATH",
    "GoldSetError",
    "labelled_correct",
    "load_gold",
    "modules_covered",
    "stratify_by_module",
    "write_gold",
]
