# 00 — Problem Brief

Source: NielsenIQ Innovation Portal, "The Product Truth Agent", proposed
2026-08-04 by Revathy Gajendran (R&D). Status: Shortlisted. Complexity: Medium.

## The problem in one paragraph

The same retail product appears across ecommerce sites, retailer catalogs,
marketplaces and manufacturer pages under different names, pack sizes,
languages and promotional contexts. A search engine returns many candidate
URLs; deciding which one is *the* product requires weighing text, attributes
and images, and pages are often incomplete or mutually contradictory. Doing this
by hand is slow and error-prone.

## What must be built

An agent that evaluates multiple candidate webpages and selects the most likely
digital representation of a given product.

Required capabilities, verbatim from the brief:

1. Analyze evidence across candidate webpages.
2. Compare product descriptions, attributes, and images.
3. Identify and eliminate false matches.
4. Resolve incomplete or conflicting information.
5. Select the most likely product URL.
6. Explain the reasoning behind the selection.
7. Demonstrate on sample products and candidate webpages.

## Success criteria

- Accurately identify the most likely product URL.
- Distinguish the correct product from similar or misleading matches.
- Provide clear and transparent reasoning.
- Go beyond keyword matching by effectively using available evidence.

## The task is two-stage, not one

The dataset's own guide states the objective more precisely than the PDF does.
The chain is:

    find the most likely product URL
      -> identify the MODULE
        -> determine which characteristics apply to that module
          -> use webpage/image evidence + business guidelines to predict values

So URL selection is stage 1 and **structured characteristic extraction is stage
2**, and stage 2 is where most of the scored surface area lives (13
characteristic columns vs 1 URL column). An architecture that only does URL
matching solves less than half the problem.

Stage 2 has a hard rule from the guide: characteristics are module-specific. If
a characteristic does not apply to the product's module, it must be left
**empty** — not guessed. Predicting a plausible value for a non-applicable
characteristic is a wrong answer, not a partial credit answer.

## Constraints and allowances

- LLMs, multimodal models, ML/NLP, or hybrid approaches are all permitted.
- An LLM will be provided by the organizers where applicable.
- Deliverable must be a demonstrable working prototype.

## Gap between the brief and the delivered data

The brief promises the dataset will include *"a set of candidate webpages with
extracted content and metadata."* **It does not.** See
`01-dataset-contract.md` §4. Candidate retrieval is therefore in scope for us to
build, not given. This is the single largest scope difference between the PDF
and reality, and it is why a meta-search layer (SearxNG) is part of the design.
