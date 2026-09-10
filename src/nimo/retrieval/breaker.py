"""Per-engine circuit breaker — `04` §6, `specs/retrieval.md` §5a.

`04` §6 requires a circuit breaker: "N consecutive failures on a domain → stop
hitting it, record the fact, continue with other domains." The unit that gets
blocked here is the **engine**, not the domain.

Measured, and this is why the module exists rather than a retry loop being
enough: no single free engine survives a 400-row run. Google, DuckDuckGo and
Qwant CAPTCHA within a few dozen queries; Brave — the best-scoring engine
tested — began blocking after about six. What kept that run producing
candidates was Startpage and Bing continuing while Brave was down. A portfolio
without a breaker just keeps hammering a blocked engine, which both wastes the
request and extends the block.

A CAPTCHA is not a transient error. It means "you are rate limited, come back
later", so the cooldown here is minutes — unrelated to the sub-second retry
backoff in `client.py`, which handles a flaky response rather than a refusal.
"""

from dataclasses import dataclass, field


@dataclass
class EngineBreaker:
    """Tracks consecutive failures per engine and opens the circuit on N.

    Time is injected rather than read from the clock, so the cooldown is
    testable without sleeping and the class stays free of the wall-clock reads
    `04` §5 keeps out of logic.
    """

    failure_threshold: int
    cooldown_s: float
    _consecutive: dict[str, int] = field(default_factory=dict)
    _opened_at: dict[str, float] = field(default_factory=dict)
    _blocks: dict[str, int] = field(default_factory=dict)

    def available(self, engines: tuple[str, ...], now: float) -> list[str]:
        """The engines worth querying right now, in configured order.

        Returns an empty list when every engine is cooling down — the caller
        must treat that as a hard failure rather than an empty result set,
        because "no engine answered" and "no results exist" are different
        facts and only one of them is about the product.
        """
        return [engine for engine in engines if not self.is_open(engine, now)]

    def is_open(self, engine: str, now: float) -> bool:
        opened = self._opened_at.get(engine)
        if opened is None:
            return False
        if now - opened >= self.cooldown_s:
            # Cooldown elapsed: half-open. The counter resets so one failure
            # after recovery does not immediately re-open the circuit.
            del self._opened_at[engine]
            self._consecutive[engine] = 0
            return False
        return True

    def record_success(self, engine: str) -> None:
        """A responsive engine clears its failure streak — the threshold is
        consecutive failures, not lifetime ones."""
        self._consecutive[engine] = 0

    def record_failure(self, engine: str, now: float) -> None:
        count = self._consecutive.get(engine, 0) + 1
        self._consecutive[engine] = count
        if count >= self.failure_threshold and engine not in self._opened_at:
            self._opened_at[engine] = now
            self._blocks[engine] = self._blocks.get(engine, 0) + 1

    @property
    def blocked_engines(self) -> dict[str, int]:
        """How many times each engine has been circuit-broken this run.

        `05` §5 wants the systemic pattern visible rather than only per-request
        logging: "Boots recall just dropped to 0%" is invisible row by row. The
        engine equivalent is a run that quietly finished on one engine.
        """
        return dict(self._blocks)
