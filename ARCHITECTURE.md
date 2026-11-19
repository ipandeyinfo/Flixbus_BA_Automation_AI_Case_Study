# Component Architecture

The pipeline is divided into small components that communicate through typed data models. Each component should be testable with fixtures and should not read another component's private implementation details.

## End-to-end flow

```text
Input folder
    -> 1. File discovery
    -> 2. PDF text extraction
    -> 3. Invoice field extraction
    -> 4. Validation and duplicate analysis
    -> 5. Routing and MIS reporting
```

`src/pipeline.py` coordinates the stages. It should contain orchestration only, not PDF parsing, business rules, or report formatting.

## Components

### 1. Batch intake and file discovery

**Location:** `src/ingestion/file_discovery.py`

**Responsibility:** Enumerate every file under the configured `Data/Input/invoices/` folder and classify it by extension. Do not move or modify source files. PDFs continue to processing; non-PDF files are recorded as unsupported. An unreadable PDF is a processing failure, not a non-PDF.

**Output contract:** A `DiscoveredFile` record containing the relative path, filename, extension, and intake status. The complete inventory is retained for the final MIS so no input silently disappears.

**Independent checks:** Mixed extensions, nested folders, empty folders, case-insensitive `.pdf`, and deterministic ordering.

### 2. PDF text extraction

**Location:** `src/ingestion/pdf_loader.py`

**Responsibility:** Extract text from each PDF page with PyMuPDF. Preserve the source file and raw page text. The current implementation does not run OCR: a PDF with no extractable text is returned as `NO_TEXT`, and unreadable files are returned as `EXTRACTION_FAILED`. OCR can be added as a later fallback.

**Input:** One discovered PDF.

**Output contract:** An `ExtractedDocument` record with source file, page text, extraction method, status, warnings, and an error message when extraction fails.

**Independent checks:** Normal text PDFs, line breaks in totals, empty/image-only PDFs, and corrupt PDFs.

### 3. Invoice extraction and normalization

**Location:** `src/extraction/invoice_parser.py` and `src/extraction/llm_extractor.py`

**Responsibility:** The current deterministic parser handles the invoice labels and layouts observed in the supplied batch, normalizes dates and amounts, and records source evidence. It does not infer missing values. A local LLM adapter is planned for layouts that the parser cannot interpret; any AI-proposed value must be validated against the document and remain reviewable.

**Input:** `ExtractedDocument`.

**Output contract:** An `ExtractedInvoice` record with invoice number, vendor identity, date, PO number, currency, totals, line items, field evidence, and extraction warnings.

**Independent checks:** Standard and alternate labels, missing PO, split totals, currency symbols, and LLM output that is malformed or unsupported by evidence.

### 4. Reference data and deterministic validation

**Location:** `src/validation/rules_engine.py`

**Responsibility:** Load `vendor_master.csv` and match normalized vendor names, then evaluate vendor status, approved currency, required fields, EUR spend threshold, and dual approval. Historical invoice matching belongs to the duplicate-detection component. Business decisions are deterministic; the LLM does not approve or reject invoices.

**Input:** `ExtractedInvoice` plus vendor reference data.

**Output contract:** An `InvoiceValidationResult` with the matched vendor, batch outcome, required approver count where known, and `RuleFinding` records with rule identifier, severity, and explanation.

**Independent checks:** One focused test per rule, including unknown and inactive vendors. Do not invent FX rates: a non-EUR threshold comparison requires a configured, traceable rate source and effective date.

### 5. Duplicate and semantic review

**Location:** `src/intelligence/duplicate_detector.py`

**Responsibility:** Compare invoice identifiers and near EUR amount/date pairs against history and the current batch; a shared PO alone is not treated as a duplicate because one PO may cover multiple invoices. Invoice-number matches are duplicate candidates only when both known vendor IDs match; if either vendor is unresolved, an exact invoice-number match remains a review candidate. Use local `all-MiniLM-L6-v2` embeddings to find semantically similar line items within the current batch. A semantic alert requires both invoices to have the same known currency, at least two distinct line pairs whose descriptions score at least 0.90, quantities that match exactly, unit prices and line amounts within 1%, and invoice dates within 30 days. Historical data has no line descriptions, so historical matching is metadata-only. Semantic-only similarity is informational and does not change routing.

**Input:** Extracted invoices and historical invoices.

**Output contract:** `DuplicateAnalysisResult` with the historical source path and row count, explicit semantic scan status/warnings, and `DuplicateCandidate` records containing source/matched file paths, source type (`Historical CSV` or `Current batch`), match method, confidence, optional score, and evidence-based rationale.

**Independent checks:** Exact duplicates, close amount/date candidates, similar descriptions across vendors, and unrelated descriptions with similar wording.

### 6. Routing and MIS/reporting

**Location:** `src/reporting/report_generator.py`

**Responsibility:** The current implementation produces a validation- and duplicate-aware MIS and includes every discovered file, including unsupported formats and PDF extraction failures. Duplicate matches remain human-review candidates; LLM field extraction is not yet included.

**Current output:** one `Data/Output/MIS_DD_MMM_YYYY_HH-MM.xlsx` per run. The workbook displays its generation time as `DD MMM YYYY HH:MM`; repeated runs within a minute receive a numeric filename and Run ID suffix, with:

- `Executive Summary`: total files, extraction counts, passed-current-rules, holds, reviews, approval-routing counts, and the historical source path/row count.
- `Invoice Register`: source filename, extracted invoice details, confidence-bearing evidence, matched vendor ID, approver count, validation findings, and outcome.
- `Exceptions`: unsupported files, extraction failures, holds, reviews, and routing outcomes with reasons.
- `Duplicate Review`: exact/metadata candidates from historical data and current-batch invoice-number, PO, or amount/date matches, with source, matched invoice/file and path, confidence, and rationale.
- `Similar Services`: one row per semantic current-batch pair, with qualifying matched lines, both invoices' descriptions, quantities, unit prices, amounts, dates, similarity score, and the threshold/rationale. These alerts do not imply duplicate billing or alter routing.

Outcome cells use green for passed-current-rules, yellow for needs-review, red for holds/errors, orange for additional approval, blue for dual approval, and gray for unsupported files. The Summary includes a matching legend. Existing reports are not overwritten; a numeric suffix distinguishes runs in the same minute.

“Passed current rules” means the invoice passed the implemented vendor, mandatory-field, currency, threshold, approval-routing, and enabled duplicate checks. The Summary also states whether the semantic model ran successfully. It is not a final approval or payment decision. Non-PDF files are reported separately and are not counted as invoices.

**Independent checks:** Counts reconcile with the full file inventory; each PDF appears once; unsupported files are not dropped; workbook can be opened and contains the expected sheets.

## Shared contracts

Define shared records in `src/models/schemas.py`. Components should accept and return these records rather than importing one another's internal helpers. At minimum, the contracts are:

- `DiscoveredFile`
- `ExtractedDocument`
- `ExtractedInvoice`
- `RuleFinding`
- `DuplicateCandidate`
- `ProcessedInvoice`
- `BatchReport`

Keep raw source values and normalized values distinct where they differ. Attach evidence and warnings to findings so a reviewer can trace why a value or decision was produced.

## Suggested implementation order

1. Define shared schemas and fixtures.
2. Build file discovery and test that every input is accounted for.
3. Build PDF extraction and structured invoice extraction.
4. Add reference loading and deterministic rules.
5. Add duplicate candidate detection.
6. Add routing and MIS generation using synthetic results.
7. Connect the components in `src/pipeline.py` and run the complete batch.

Components 2 through 6 can be developed in parallel once the shared schemas are agreed. Integration belongs last, after each component passes its own focused tests.
