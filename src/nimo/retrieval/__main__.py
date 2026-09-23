"""`uv run python -m nimo.retrieval --ping` — one live Brave Search API call.

Run this first on a new machine or network: it reads BRAVE_API_KEY from
`.env` (never printed), sends one query with no cache, and prints the HTTP
outcome and the first results. Costs one credit. `print` is the CLI's
user-facing output (`04` §10).
"""

import sys

from nimo.retrieval.brave import BraveApiClient, load_brave_config
from nimo.retrieval.client import SearchError
from nimo.retrieval.config import load_retrieval_config
from nimo.retrieval.queries import SearchQuery
from nimo.run.compose import use_system_certificates
from nimo.settings import settings

PING_QUERY = "aquafresh whitening pump toothpaste 100ml"


def main(argv: list[str]) -> int:
    if "--ping" not in argv:
        print(__doc__)
        return 2
    if not settings.brave_api_key:
        print("BRAVE_API_KEY is not set in .env")
        return 1
    use_system_certificates()
    print(f"system certificate store: {'ON' if settings.nimo_system_certs else 'off'}")
    client = BraveApiClient.create(
        settings.brave_api_key, load_retrieval_config(), load_brave_config(), cache=None
    )
    try:
        results = client.search(SearchQuery("S3", PING_QUERY), 5)
    except SearchError as error:
        print(f"FAILED: {error}")
        return 1
    finally:
        client.close()
    print(f"OK: Brave Search API answered {len(results)} results for {PING_QUERY!r}")
    for result in results:
        print(f"  {result.rank}. {result.url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
