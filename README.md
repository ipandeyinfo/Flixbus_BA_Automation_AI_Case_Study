# AP Invoice Processing Pipeline

A local Python pipeline that inventories invoice files, extracts and normalizes PDF data, applies AP controls, identifies duplicate candidates, and creates a reviewer-focused Excel MIS.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the component boundaries, process flow, duplicate criteria, and report mapping.

## Current Capabilities

- Inventories every file under the input directory; PDFs are processed and unsupported formats are reported.
- Classifies PDF pages as text, scanned image, mixed, or empty. It extracts the existing text layer; OCR is not implemented.
- Parses invoice headers, totals, notes, and line items, retaining source evidence and field confidence.
- Validates vendor status, required fields, approved currency, EUR thresholds, and approval routing.
- Compares invoice numbers and near amount/date values against historical metadata; a shared PO alone is not treated as a duplicate.
- Generates informational semantic similar-service alerts using local embeddings. These alerts do not alter invoice routing.
- Writes a timestamped five-sheet Excel MIS and logs progress to the terminal and a rotating log file.

## Project Layout

```text
Problem Statement AP/
├── Data/
│   ├── Input/
│   │   ├── invoices/                 # Incoming PDF batch
│   │   ├── vendor_master.csv         # Approved vendor reference
│   │   ├── historic_invoices.csv     # Processed invoice metadata
│   │   └── data_dictionary.md
│   └── Output/                       # Timestamped Excel MIS workbooks
├── config/                           # Paths and logging setup
├── logs/                             # Rotating runtime log
├── src/
│   ├── ingestion/                    # File inventory and PDF extraction
│   ├── extraction/                   # Invoice field parsing
│   ├── validation/                   # Vendor and AP business rules
│   ├── intelligence/                 # Historical and semantic matching
│   ├── reporting/                    # Excel MIS generation
│   ├── models/                       # Shared data contracts
│   └── pipeline.py                   # Stage orchestration
├── tests/
└── main.py                           # CLI entry point
```

## Setup and Run

Use Python 3.11 or newer. From the project root, create and activate a virtual environment, then install the dependencies:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
```

On macOS/Linux, activate with `source .venv/bin/activate`. The first semantic run downloads `all-MiniLM-L6-v2` into the local Hugging Face cache; later runs use the cached model. To run metadata matching without semantic embeddings:

```powershell
python main.py --disable-semantic-duplicates
```

Use `python main.py --help` to override `--input-dir`, `--output-dir`, `--vendor-master`, or `--historic-invoices`. Default paths are anchored to this project, not the current shell directory.

## Preconditions and Assumptions

- Run from the project root, or provide paths with the CLI options. Defaults expect `Data/Input/invoices/`, `Data/Input/vendor_master.csv`, and `Data/Input/historic_invoices.csv`.
- The vendor master and history CSVs must have the documented headers. Invoice dates in history must use `YYYY-MM-DD`; historical amounts must be numeric EUR values.
- PDFs with a readable text layer can be processed. Image-only scans have no OCR fallback and are reported as `NO_TEXT`; mixed PDFs with scanned pages are sent to review.
- Vendor names are matched to the master using normalized exact names. Unknown or inactive vendors are held; fuzzy vendor-name matching is not enabled.
- Spend thresholds are defined in EUR. No exchange rate is configured, so a non-EUR invoice is sent for review rather than converted using an assumed rate.
- Historical records are read-only and contain no line descriptions. Historical duplicate checks use invoice/vendor/PO/amount/date metadata; semantic line comparison applies only within the current batch.
- Semantic similar-service alerts require at least two line pairs with description cosine similarity of `0.90` or higher, equal quantities, unit prices and line amounts within `1%`, and dates within 30 days. They are informational and do not change routing.
- `READY_FOR_NEXT_STAGE` means the invoice passed the currently implemented checks. It is not approval for payment; duplicate alerts, FX review, OCR, LLM extraction, and final human approval remain separate concerns.

**Input data note:** `Data/Input/invoices/` currently contains 18 PDFs. One is `INV-2025-03701_V001_EuroFuel - Copy.pdf`, a byte-identical copy of the EuroFuel invoice. Remove that copy from the input folder if it is not intended to be part of the batch.

## Duplicate Review Policy

Historical matching uses metadata only because `historic_invoices.csv` has no line descriptions. It checks normalized invoice numbers (with vendor-ID protection when both vendors are known) and near EUR amount/date pairs. A shared PO alone is not treated as a duplicate because one PO may cover multiple legitimate invoices. The historical CSV is read-only and new results are not appended to it.

Semantic matching compares line descriptions only within the current batch and only when both invoices have the same known currency. A `Similar Services` pair requires at least two distinct one-to-one line matches, description cosine similarity of at least `0.90`, equal quantities, unit prices and line amounts within `1%`, and invoice dates within 30 days. These are informational review alerts, not confirmed duplicates, and do not change routing. The report shows the qualifying lines and financial values so reviewers can assess them.

There is no configured FX source, so a non-EUR threshold check is sent for review rather than converted using a guessed rate.

## MIS and Logs

Each run writes `Data/Output/MIS_DD_MMM_YYYY_HH-MM.xlsx`. Same-minute runs get a numeric suffix such as `_02`. The workbook contains:

- `Executive Summary`: run ID, counts, approval routes, historical source path and row count, and semantic scan status.
- `Invoice Register`: one row per PDF with extracted fields, outcome, validation findings, duplicate candidates, similar-service alerts, and evidence.
- `Exceptions`: unsupported files, holds, reviews, and extraction/processing failures.
- `Duplicate Review`: metadata-based duplicate candidates that affect routing.
- `Similar Services`: one row per current-batch semantic pair, with matched lines, quantities, prices, amounts, dates, score, and rationale.

The console uses color-coded timestamped progress and a batch summary table. Detailed plain UTF-8 events are written to `logs/ap_pipeline.log`, rotating at 5 MB with five backups. Logs record file identifiers and decisions, not full extracted PDF text.

## Quality Checks and Limitations

Run the test suite from the project root with `python -m pytest -q`. Tests cover discovery, parsing, vendor/rule decisions, duplicate candidates, and MIS output.

OCR, LLM-assisted field extraction, automatic FX conversion, persistent history updates, and final payment approval are not implemented. “Passed current rules” is not equivalent to approved or paid.
