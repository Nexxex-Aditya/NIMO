"""Labelled pairs from the runner's fetch artifacts — `specs/calibrate.md` §1.

Offline and reproducible: reads the `normalize` and `fetch` artifacts a live
run wrote, recomputes the weighted score for every candidate, and labels each
one by the GTIN hard rule. No network, no clock.

The GTIN rule is the oracle, the text score is the thing being calibrated, and
they are kept apart on purpose: the score fed to the fit is the weighted sum
**before** hard rules, so a GTIN accept does not leak into the number it is
labelling.
"""

import json
from dataclasses import dataclass
from pathlib import Path

from nimo.contracts import CandidateEvidence, ProductQuery
from nimo.match import MatchConfig, compute_features, weighted_score
from nimo.run.artifacts import artifact_path


@dataclass(frozen=True)
class LabelledPair:
    row_uid: str
    url: str
    score: float  # weighted score BEFORE hard rules
    correct: bool  # page GTIN == query barcode

    def to_json(self) -> str:
        return json.dumps(
            {
                "row_uid": self.row_uid,
                "url": self.url,
                "score": self.score,
                "correct": self.correct,
            },
            sort_keys=True,
        )


def harvest_pairs(
    artifacts_root: Path, row_uids: list[str], config: MatchConfig
) -> list[LabelledPair]:
    """Every candidate whose page publishes a comparable GTIN, labelled.

    Candidates with `barcode_exact is None` — no page GTIN, or an unusable
    query barcode — are **excluded**, not treated as negatives. "Cannot
    evaluate" is not "wrong", and on `dev` it is 394 of 412 rows.
    """
    pairs: list[LabelledPair] = []
    for row_uid in row_uids:
        normalize_path = artifact_path(artifacts_root, "normalize", row_uid)
        fetch_path = artifact_path(artifacts_root, "fetch", row_uid)
        if not normalize_path.exists() or not fetch_path.exists():
            continue  # an incomplete row was never persisted; nothing to harvest
        query = ProductQuery.model_validate_json(normalize_path.read_text(encoding="utf-8"))
        evidence = [
            CandidateEvidence.model_validate(item)
            for item in json.loads(fetch_path.read_text(encoding="utf-8"))
        ]
        for item in evidence:
            features = compute_features(query, item, config)
            if features.barcode_exact is None:
                continue
            pairs.append(
                LabelledPair(
                    row_uid=row_uid,
                    url=item.url,
                    score=weighted_score(features, config),
                    correct=features.barcode_exact,
                )
            )
    return pairs


def write_pairs(path: Path, pairs: list[LabelledPair]) -> None:
    """Committed alongside the curve so the fit is reproducible from the repo."""
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(pairs, key=lambda pair: (pair.row_uid, pair.url))
    path.write_text(
        "\n".join(pair.to_json() for pair in ordered) + ("\n" if ordered else ""), encoding="utf-8"
    )


def read_pairs(path: Path) -> list[LabelledPair]:
    if not path.exists():
        return []
    pairs: list[LabelledPair] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        pairs.append(
            LabelledPair(
                row_uid=str(record["row_uid"]),
                url=str(record["url"]),
                score=float(record["score"]),
                correct=bool(record["correct"]),
            )
        )
    return pairs
