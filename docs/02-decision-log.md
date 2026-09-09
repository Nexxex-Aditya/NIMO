# 02 — Decision Log

Append-only. Newest at the bottom. One entry per architectural decision.
This is the sync channel between build sessions and the design side — if a decision isn't here, the other side doesn't know about it.

Format:

    ## YYYY-MM-DD — <short title>
    **Decision:** one or two sentences.
    **Why:** the reason, including what was rejected.
    **Affects:** modules/files.
    **Status:** standing | superseded by <entry>

---

## 2026-09-09 — Candidate retrieval is in scope
**Decision:** Build a candidate-URL retrieval subsystem. SearxNG as the
meta-search layer.
**Why:** The brief promised candidate webpages in the dataset; the dataset has
none, and `PRODUCT_URL` is 100% null in both `dev` and `qa`.
**Affects:** new `retrieval/` subsystem; changes the whole pipeline shape from
"rank given candidates" to "generate then rank".
**Status:** standing

---

# Open questions — resolve with organizers

| # | Question | Blocking? | Status |
|---|---|---|---|
| Q1 | `dev.EXTERNAL_CODE` is rounded to 3 sig figs in 377/412 rows. Can a corrected sheet be provided? | High — kills barcode matching on dev | open |
| Q2 | Is the expected `PRODUCT_URL` submission value a real URL, or the page title? `sample_output` contains titles. | High — wrong format = zero score | open |
| Q3 | No URL ground truth exists in `dev`. How is stage-1 URL selection scored? | High — cannot optimize what we cannot measure | open |
| Q4 | `sample_output` shows an Amazon.in page as the answer for a `FR,GB` item. Is cross-market resolution acceptable? | Medium — determines whether market is a filter or a feature | open |
| Q5 | `sample_output` carries `GLOBAL_FLAVOUR_FRAGRANCE_INGREDIENT`, absent from `dev`/`qa`. Required in submission? | Medium | open |
| Q6 | Is scraping retailer sites permitted, and are there rate/robots constraints for the demo? | Medium | open |
| Q7 | Which LLM is provided, with what context window and rate limit? Multimodal available for image evidence? | High — image comparison is an explicit requirement | open |
