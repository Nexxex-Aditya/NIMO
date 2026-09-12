"""The explorer renders what the runner recorded, in one self-contained file."""

import json
from pathlib import Path

from nimo.contracts import RawRow
from nimo.run import RunPaths, Stages, run
from nimo.site import build_site
from tests.run.test_runner import CONFIG_DIR, fixed_clock


def paths_in(root: Path) -> RunPaths:
    return RunPaths(
        artifacts=root / "artifacts",
        trace=root / "trace.jsonl",
        failures=root / "failures.jsonl",
        config_dir=CONFIG_DIR,
    )


def _data(page: str) -> dict[str, object]:
    blob = page.split('<script id="nimo-data" type="application/json">', 1)[1].split(
        "</script>", 1
    )[0]
    return dict(json.loads(blob))


def test_the_page_embeds_every_complete_row_and_is_self_contained(
    dev_rows: list[RawRow], stages: Stages, tmp_path: Path
) -> None:
    paths = paths_in(tmp_path)
    run(dev_rows[:3], stages, paths, "site", fixed_clock)
    out = tmp_path / "site_dev.html"
    report = build_site(
        rows=dev_rows[:3],
        sheet="dev",
        artifacts=paths.artifacts,
        failures_path=paths.failures,
        registry_path=tmp_path / "no-entities.jsonl",
        config_dir=CONFIG_DIR,
        out=out,
        title="t <b>",
        notes=["cold registry: every row is tier2 on a first pass"],
    )
    assert (report.rows_total, report.rows_complete, report.rows_failed) == (3, 3, 0)
    page = out.read_text(encoding="utf-8")
    assert page.startswith("<!doctype html>") and page.rstrip().endswith("</html>")
    assert "<title>t &lt;b&gt;</title>" in page
    # No external assets: nothing loads from the network (`04` §6 for pages too).
    assert "<script src=" not in page and "<link " not in page and "@import" not in page
    data = _data(page)
    rows = data["rows"]
    assert isinstance(rows, list) and [r["row_uid"] for r in rows] == ["dev:0", "dev:1", "dev:2"]
    summary = data["summary"]
    assert isinstance(summary, dict)
    assert summary["rows_complete"] == 3 and summary["tiers"] == {"tier2_retrieval": 3}
    assert data["notes"] == ["cold registry: every row is tier2 on a first pass"]
    # The live UI's renderer, verbatim, so the two pages cannot drift.
    assert "function renderCard(c)" in page


def test_a_closing_script_tag_in_the_data_cannot_end_the_data_block(
    dev_rows: list[RawRow], stages: Stages, tmp_path: Path
) -> None:
    """A page title or body text containing `</script>` would otherwise cut
    the JSON short and the page would render nothing."""
    paths = paths_in(tmp_path)
    run(dev_rows[:1], stages, paths, "site", fixed_clock)
    out = tmp_path / "site_dev.html"
    build_site(
        rows=dev_rows[:1],
        sheet="dev",
        artifacts=paths.artifacts,
        failures_path=paths.failures,
        registry_path=tmp_path / "none.jsonl",
        config_dir=CONFIG_DIR,
        out=out,
        title="x",
        notes=["evil </script><script>alert(1)</script>"],
    )
    page = out.read_text(encoding="utf-8")
    assert page.count("</script>") == 2  # the data block and the page script, nothing injected
    assert _data(page)["notes"] == ["evil </script><script>alert(1)</script>"]


def test_failed_rows_are_listed_not_dropped(
    dev_rows: list[RawRow], stages: Stages, tmp_path: Path
) -> None:
    from dataclasses import replace

    paths = paths_in(tmp_path)

    def broken(query: object) -> object:
        raise ValueError("boom")

    run(dev_rows[:2], replace(stages, classify=broken), paths, "site", fixed_clock)  # type: ignore[arg-type]
    out = tmp_path / "site_dev.html"
    report = build_site(
        rows=dev_rows[:2],
        sheet="dev",
        artifacts=paths.artifacts,
        failures_path=paths.failures,
        registry_path=tmp_path / "none.jsonl",
        config_dir=CONFIG_DIR,
        out=out,
        title="x",
        notes=[],
    )
    assert (report.rows_complete, report.rows_failed) == (0, 2)
    failures = _data(out.read_text(encoding="utf-8"))["failures"]
    assert isinstance(failures, list) and {f["stage"] for f in failures} == {"classify"}

    # A resume that succeeds turns the failure into a success; and another
    # sheet's failures in the same append-only file are not this sheet's.
    run(dev_rows[:2], stages, paths, "site-2", fixed_clock)
    with paths.failures.open("a", encoding="utf-8") as handle:
        handle.write(
            '{"row_uid":"qa:7","stage":"retrieve","error_type":"SearchError","message":"x",'
            '"occurred_at":"2026-09-12T00:00:00Z"}\n'
        )
    again = build_site(
        rows=dev_rows[:2],
        sheet="dev",
        artifacts=paths.artifacts,
        failures_path=paths.failures,
        registry_path=tmp_path / "none.jsonl",
        config_dir=CONFIG_DIR,
        out=out,
        title="x",
        notes=[],
    )
    assert (again.rows_complete, again.rows_failed) == (2, 0)
