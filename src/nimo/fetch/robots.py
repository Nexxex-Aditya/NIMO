"""robots.txt handling — `03` §4 stage 3, `specs/fetch.md` §3.

`03` §4 stage 3 lists "honor `robots.txt`" among the politeness requirements,
and `04` §6 repeats it. Q6 (is scraping permitted?) is still unresolved with
the organizers, which makes honouring robots the conservative default rather
than an optional courtesy.

Fetching robots.txt is injected rather than done here, so this module stays
pure and testable with zero network (`04` §6).
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser


@dataclass
class RobotsCache:
    """One `robots.txt` decision cache, keyed by scheme+host.

    Fetched once per host, never per URL: a crawl of twenty pages on one
    retailer must not fetch robots.txt twenty times, which would itself be the
    impolite behaviour robots.txt exists to prevent.

    **A host whose robots.txt cannot be fetched is treated as ALLOWED.** That
    is what RFC 9309 specifies for an unreachable robots file, and it is the
    interpretation every mainstream crawler uses — treating it as a blanket
    disallow would silently drop every site with a transient error, which is
    the "plausible wrong answer" shape `05` §5 is about. A 4xx on robots.txt
    means "no rules published", not "no crawling".
    """

    fetch: Callable[[str], str | None]
    user_agent: str
    _parsers: dict[str, RobotFileParser | None] = field(default_factory=dict)

    def _parser_for(self, url: str) -> RobotFileParser | None:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin in self._parsers:
            return self._parsers[origin]

        parser: RobotFileParser | None = None
        body = self.fetch(f"{origin}/robots.txt")
        if body is not None:
            parser = RobotFileParser()
            parser.parse(body.splitlines())
        self._parsers[origin] = parser
        return parser

    def allowed(self, url: str) -> bool:
        """Whether `user_agent` may fetch `url`."""
        parser = self._parser_for(url)
        if parser is None:
            return True
        return parser.can_fetch(self.user_agent, url)

    def crawl_delay(self, url: str) -> float | None:
        """Any `Crawl-delay` the host asks for.

        Honoured when it is *longer* than our configured interval — a site
        asking for more space gets it. A site asking for less does not speed
        us up; `min_interval_s` is our own politeness floor, not a target.
        """
        parser = self._parser_for(url)
        if parser is None:
            return None
        delay = parser.crawl_delay(self.user_agent)
        return float(delay) if delay is not None else None

    @property
    def hosts_checked(self) -> int:
        return len(self._parsers)
