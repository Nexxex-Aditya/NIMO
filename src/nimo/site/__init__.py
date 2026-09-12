"""The static results explorer — one self-contained HTML file over a run's
artifacts, for evaluators who will not run the pipeline (`specs/site.md`)."""

from nimo.site.build import SiteReport, build_site

__all__ = ["SiteReport", "build_site"]
