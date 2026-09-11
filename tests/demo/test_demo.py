"""P15 tests — the demo renders what the runner recorded, and nothing else."""

from pathlib import Path

from nimo.contracts import RawRow
from nimo.demo import load_card, load_failures, render_failure, render_html, render_text
from nimo.run import RunPaths, Stages, run
from tests.run.test_runner import WORKBOOK, fixed_clock


def paths_in(root: Path) -> RunPaths:
    return RunPaths(
        artifacts=root / "artifacts",
        trace=root / "trace.jsonl",
        failures=root / "failures.jsonl",
        config_dir=WORKBOOK.parent.parent.parent / "config",
    )


def test_a_card_is_built_from_the_runners_own_artifacts(
    dev_rows: list[RawRow], stages: Stages, tmp_path: Path
) -> None:
    paths = paths_in(tmp_path)
    run(dev_rows[:2], stages, paths, "demo", fixed_clock)
    card = load_card(paths.artifacts, "dev:0")
    assert card is not None and card.row_uid == "dev:0"
    text = render_text(card)
    assert text.startswith("=== dev:0  AQUAFRESH")
    for stage in ("[normalize]", "[registry]", "[retrieve]", "[fetch]", "[match]", "[classify]"):
        assert stage in text
    assert "[characteristics]" in text and "[reason]" in text
    assert card.module.module in text and card.reasoning.text in text


def test_an_incomplete_row_has_no_card(tmp_path: Path) -> None:
    assert load_card(tmp_path, "dev:99") is None
    assert load_failures(tmp_path / "none.jsonl") == {}


def test_html_is_self_contained_and_escapes(
    dev_rows: list[RawRow], stages: Stages, tmp_path: Path
) -> None:
    paths = paths_in(tmp_path)
    run(dev_rows[:1], stages, paths, "demo", fixed_clock)
    card = load_card(paths.artifacts, "dev:0")
    assert card is not None
    page = render_html("t <b>", [card], [], ["summary <line>"])
    assert page.startswith("<!doctype html>") and "</html>" in page
    assert "t &lt;b&gt;" in page and "summary &lt;line&gt;" in page
    assert "http://" not in page.split("<style>")[1].split("</style>")[0]  # no external assets
    assert card.reasoning.text[:40] in page


def test_failure_line_names_the_stage(tmp_path: Path) -> None:
    from datetime import UTC, datetime

    from nimo.contracts import RowFailure

    failure = RowFailure(
        row_uid="qa:3",
        stage="retrieve",
        error_type="SearchError",
        message="every engine is circuit-broken",
        occurred_at=datetime(2026, 9, 11, tzinfo=UTC),
    )
    assert render_failure(failure).startswith("=== qa:3  FAILED at retrieve: SearchError")
