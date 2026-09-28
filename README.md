# NIMO — The Product Truth Agent

NIMO is a deterministic product intelligence pipeline that takes a retail product record and identifies, verifies, classifies, and explains the product using web evidence.

Given information such as a product description, barcode, brand, country, and retailer, NIMO:

1. Normalizes the input product record
2. Checks a persistent product registry
3. Retrieves relevant web pages
4. Fetches and caches page content
5. Identifies the page that best represents the product
6. Classifies the product into a predefined module
7. Extracts structured product characteristics
8. Produces evidence-grounded reasoning
9. Stores the complete execution record for reproducibility

The system is designed as a **deterministic pipeline with bounded model usage**, rather than an autonomous agent loop.

Each stage produces a typed artifact, execution can be resumed, and cached runs can be reproduced without unnecessarily repeating expensive operations.

---

## Architecture

```text
Product Record
      │
      ▼
┌──────────────┐
│  Normalize   │
└──────┬───────┘
       ▼
┌──────────────┐
│   Registry   │
└──────┬───────┘
       │
       ├── Registry Hit ───────────────────────────────┐
       │                                               │
       ▼                                               │
┌──────────────┐                                       │
│  Retrieve    │                                       │
└──────┬───────┘                                       │
       ▼                                               │
┌──────────────┐                                       │
│    Fetch     │                                       │
└──────┬───────┘                                       │
       ▼                                               │
┌──────────────┐                                       │
│    Match     │                                       │
└──────┬───────┘                                       │
       ▼                                               │
┌──────────────┐                                       │
│  Classify    │                                       │
└──────┬───────┘                                       │
       ▼                                               │
┌──────────────┐                                       │
│Characteristics│                                      │
└──────┬───────┘                                       │
       ▼                                               │
┌──────────────┐                                       │
│   Reason     │                                       │
└──────┬───────┘                                       │
       │                                               │
       └──────────────────────┬────────────────────────┘
                              ▼
                     ┌────────────────┐
                     │     Assemble   │
                     └───────┬────────┘
                             ▼
                    Structured Output
```

---

## Core Components

### 1. Product Registry

The registry stores previously resolved products under:

```text
data/registry/
```

When a product has already been resolved, NIMO can reuse the stored result instead of repeating retrieval, page fetching, matching, classification, and extraction.

This creates a warm-start workflow where repeated processing becomes progressively cheaper and faster.

---

### 2. Web Retrieval

NIMO uses a self-hosted [SearXNG](https://docs.searxng.org/) instance for web retrieval.

The retrieval layer is designed around:

* Multiple search engines
* Controlled query execution
* Per-engine failure handling
* Circuit breakers
* Fetch budgets
* Cooldown handling
* Content-addressed caching
* Deterministic execution

Search results are treated as **candidates**, not as ground truth.

---

### 3. Product Matching

Candidate pages are evaluated using a multi-stage matching process.

The system applies hard constraints before softer similarity methods.

Examples include:

* Exact GTIN/barcode matches
* Conflicting GTIN rejection
* Product size validation
* Product count validation
* Refill/listing detection
* Text similarity
* Candidate ranking

A calibrated scoring layer can then estimate the reliability of the resulting match.

When candidates remain sufficiently close, a bounded LLM-based adjudication step can be used as a final tiebreaker.

The model is therefore not responsible for the entire matching process.

---

### 4. Product Classification

Once a product page has been identified, NIMO classifies the product into a predefined module.

Classification can use structured product information and textual evidence extracted from the matched page.

The classification stage is independently testable and can be evaluated against labelled examples.

---

### 5. Characteristics Extraction

After classification, NIMO extracts the characteristics applicable to that product's module.

The extraction process uses:

* Module-specific applicability rules
* Controlled vocabularies
* Structured output validation
* Evidence from the matched webpage
* Bounded model interaction

Closed vocabulary values are validated before they become part of the final result.

The model receives only the guidelines relevant to the predicted module rather than the entire rule set.

---

### 6. Evidence-Grounded Reasoning

NIMO does not ask the model to freely generate an explanation.

Instead, reasoning is assembled from recorded fields and evidence produced by earlier stages.

Conceptually:

```text
Recorded Evidence
       │
       ├── Product identity
       ├── Matched webpage
       ├── Classification
       ├── Characteristics
       └── Supporting fields
                │
                ▼
        Structured Reasoning
```

This makes the final explanation traceable to the information recorded during execution.

---

## Design Principles

### Deterministic by Default

The pipeline is structured as explicit stages rather than an open-ended agent loop.

Each stage has defined inputs, outputs, and validation rules.

### Bounded Model Usage

LLMs are used only where they provide value, such as difficult candidate adjudication or structured extraction.

Critical decisions are protected by deterministic rules and validation.

### Evidence First

A product claim should be supported by recorded evidence.

NIMO separates:

```text
Evidence → Decision → Output
```

rather than allowing unsupported model-generated claims to flow directly into the final result.

### Resumable Execution

Intermediate artifacts are persisted so that interrupted runs can continue without restarting the entire pipeline.

### Cache First

Previously fetched pages and resolved products are reused whenever possible.

This reduces unnecessary network requests and improves reproducibility.

### Reproducibility

Configuration, intermediate artifacts, cached content, and outputs are separated from application logic.

This allows individual stages to be tested independently.

---

## Requirements

* Python 3.12+
* [uv](https://docs.astral.sh/uv/)
* Docker
* Docker Compose
* Internet access for live web retrieval

Optional:

* An LLM endpoint/API for model-assisted adjudication and characteristic extraction

---

## Installation

Clone the repository:

```bash
git clone <repository-url>
cd nimo
```

Install Python dependencies:

```bash
uv sync
```

Create the environment configuration:

```bash
cp .env.example .env
```

Configure the required environment variables in `.env`.

Start SearXNG:

```bash
docker compose up -d searxng
```

---

## Verify the Installation

Run the project's quality checks:

```bash
make check
```

Or run the checks individually:

```bash
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy --strict src tests
uv run pytest
```

The test suite is designed to run without requiring live network access.

---

# Running NIMO

## Process a Dataset

Run the main pipeline:

```bash
uv run python -m nimo.run --sheet qa --live
```

This executes the main processing stages:

```text
retrieve
   ↓
fetch
   ↓
match
   ↓
classify
   ↓
characteristics
   ↓
reason
```

---

## Calibration

Re-fit the matching calibration using the available labelled data:

```bash
uv run python -m nimo.calibrate
```

---

## Generate Final Output

Assemble the processed results:

```bash
uv run python -m nimo.assemble --sheet qa
```

The resulting files are written to:

```text
data/out/
```

---

## Run the Interactive Interface

Start the local interface:

```bash
uv run python -m nimo.ui --live
```

The interface is available at:

```text
http://127.0.0.1:8765
```

It can be used to:

* Process individual products
* Inspect pipeline results
* Re-run products
* Observe registry reuse
* Test products manually

---

## Generate the Results Explorer

Generate a self-contained HTML results page:

```bash
uv run python -m nimo.site --sheet qa --out-dir data/out/results
```

The generated file will be similar to:

```text
data/out/results/site_qa.html
```

The HTML output can be opened directly in a browser without running a server.

---

## Run a Small Batch

To process a limited number of products:

```bash
uv run python -m nimo.demo --sheet qa --rows 10 --live --html
```

This is useful for quickly inspecting the complete pipeline.

---

# Using Your Own Dataset

NIMO can process an external `.xlsx` or `.csv` product file.

The minimum required fields are:

```text
RETAILER_DESC
BRAND
```

The following fields are optional:

```text
BARCODE
RETAILER
COUNTRY
```

Example:

```bash
uv run python -m nimo.run \
    --input my_products.xlsx \
    --live \
    --characteristics \
    --out-dir data/out/mine
```

Generate the structured output:

```bash
uv run python -m nimo.assemble \
    --input my_products.xlsx \
    --out-dir data/out/mine
```

Generate the HTML results explorer:

```bash
uv run python -m nimo.site \
    --input my_products.xlsx \
    --out-dir data/out/mine
```

The output directory will contain the corresponding processed results.

---

# Project Structure

```text
nimo/
│
├── config/
│   ├── thresholds
│   ├── weights
│   ├── prompts
│   ├── retrieval settings
│   └── fetch settings
│
├── data/
│   ├── raw/
│   ├── registry/
│   ├── gold/
│   ├── calibration/
│   └── out/
│
├── docs/
│   ├── architecture
│   ├── decision records
│   ├── dataset documentation
│   └── engineering documentation
│
├── specs/
│   └── pipeline specifications
│
├── src/
│   └── nimo/
│       ├── contracts.py
│       ├── retrieval/
│       ├── fetch/
│       ├── matching/
│       ├── classification/
│       ├── characteristics/
│       ├── reasoning/
│       └── ...
│
├── tests/
│   └── pipeline tests
│
├── docker-compose.yml
├── pyproject.toml
└── README.md
```

---

# Testing

The project separates deterministic tests from live web operations.

Run the complete test suite:

```bash
uv run pytest
```

Run static analysis:

```bash
uv run mypy --strict src tests
```

Run linting:

```bash
uv run ruff check src tests
```

Check formatting:

```bash
uv run ruff format --check src tests
```

Run everything:

```bash
make check
```

---

# Reproducibility

NIMO separates:

```text
Configuration
      │
      ▼
Pipeline Stages
      │
      ▼
Intermediate Artifacts
      │
      ▼
Cached Evidence
      │
      ▼
Final Output
```

This allows individual stages to be inspected and re-run without rebuilding the entire pipeline.

A second run over previously resolved products can use the registry and cache rather than repeating the complete retrieval process.

---

# Data and Evidence Flow

For each product, the system maintains a chain similar to:

```text
Input Product
     │
     ▼
Normalized Product
     │
     ▼
Search Queries
     │
     ▼
Candidate Pages
     │
     ▼
Fetched Evidence
     │
     ▼
Selected Product Page
     │
     ▼
Product Classification
     │
     ▼
Characteristics
     │
     ▼
Evidence-Grounded Reasoning
     │
     ▼
Final Structured Record
```

This structure makes it possible to inspect how an output was produced rather than treating the final prediction as a black box.

---

# Development

Install the development environment:

```bash
uv sync
```

Run tests during development:

```bash
uv run pytest
```

Run the complete validation gate before committing:

```bash
make check
```

When modifying a pipeline stage, the corresponding tests under `tests/` should be updated alongside the implementation.

---

# Configuration

Runtime configuration is kept under:

```text
config/
```

This includes:

* Matching thresholds
* Candidate weights
* Retrieval configuration
* Fetch limits
* Model prompts
* Classification settings
* Characteristic extraction rules

Keeping these values outside the implementation makes the pipeline easier to experiment with and evaluate.

---

# License

Add the project's license information here.

---

# Status

NIMO is an experimental research and engineering project exploring **evidence-grounded product intelligence, deterministic pipelines, web retrieval, entity matching, structured extraction, and bounded LLM integration**.
