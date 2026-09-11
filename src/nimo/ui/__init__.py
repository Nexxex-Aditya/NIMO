"""P16 interactive interface — `specs/ui.md`."""

from nimo.ui.app import create_app
from nimo.ui.service import AdhocRecord, UiError, UiService, card_to_dict

__all__ = ["AdhocRecord", "UiError", "UiService", "card_to_dict", "create_app"]
