"""Run the AP invoice pipeline from the command line.

Parses input and output options, configures console/file logging, and runs a batch.
It emits live progress through the shared logger and creates a timestamped MIS.
Optional flags select reference files or skip local semantic matching.
"""

import argparse
import logging
from pathlib import Path

from config.logging_config import configure_logging
from config.path_utils import display_path
from config.settings import HISTORIC_INVOICES_PATH, INVOICE_DIR, OUTPUT_DIR, VENDOR_MASTER_PATH
from src.models.schemas import BatchFileOutcome
from src.pipeline import process_batch
from src.reporting.report_generator import build_mis_report_path, write_mis_report
from rich import box
from rich.console import Console
from rich.table import Table


logger = logging.getLogger(__name__)
console = Console()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Process an AP invoice batch.")
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=INVOICE_DIR,
        help="Directory containing invoice files",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=OUTPUT_DIR,
        help="Directory for generated results",
    )
    parser.add_argument(
        "--vendor-master",
        type=Path,
        default=VENDOR_MASTER_PATH,
        help="CSV file containing the approved vendor master",
    )
    parser.add_argument(
        "--historic-invoices",
        type=Path,
        default=HISTORIC_INVOICES_PATH,
        help="CSV file containing processed invoice history",
    )
    parser.add_argument(
        "--disable-semantic-duplicates",
        action="store_true",
        help="Run metadata duplicate checks without loading the local embedding model",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    log_path = configure_logging()
    logger.info("Starting invoice batch run")
    logger.info("Input folder: %s", display_path(args.input_dir))
    logger.info("Vendor master: %s", display_path(args.vendor_master))
    logger.info("Historical invoice source: %s", display_path(args.historic_invoices))
    logger.info("Run log: %s", display_path(log_path))

    try:
        batch = process_batch(
            args.input_dir,
            args.vendor_master,
            args.historic_invoices,
            semantic_duplicates=not args.disable_semantic_duplicates,
        )
        report_path = build_mis_report_path(args.output_dir, batch.generated_at)
        write_mis_report(batch, report_path)
    except Exception:
        logger.exception("Invoice batch run failed")
        raise

    parsed_count = sum(item.invoice is not None for item in batch.files)
    ready_count = sum(item.outcome == BatchFileOutcome.READY_FOR_NEXT_STAGE for item in batch.files)
    review_count = sum(item.outcome == BatchFileOutcome.NEEDS_REVIEW for item in batch.files)
    held_count = sum(item.outcome == BatchFileOutcome.HOLD for item in batch.files)
    dual_approval_count = sum(
        item.validation is not None and item.validation.required_approvers == 2
        for item in batch.files
    )
    additional_approval_count = sum(
        item.validation is not None
        and any(finding.rule_id == "SPEND_THRESHOLD_EXCEEDED" for finding in item.validation.findings)
        for item in batch.files
    )
    duplicate_invoice_count = sum(bool(item.duplicate_candidates) for item in batch.files)
    similar_service_count = sum(bool(item.similar_service_alerts) for item in batch.files)
    summary = Table(title="Invoice Batch Summary", box=box.SIMPLE_HEAVY, show_lines=False)
    summary.add_column("Metric", style="bold cyan")
    summary.add_column("Count", justify="right", style="bold")
    summary.add_row("Files discovered", str(len(batch.files)))
    summary.add_row("Invoices parsed", str(parsed_count))
    summary.add_row("Passed current rules", str(ready_count), style="green")
    summary.add_row("Held", str(held_count), style="red" if held_count else "green")
    summary.add_row("Needs review", str(review_count), style="yellow" if review_count else "green")
    summary.add_row("Additional approval routes", str(additional_approval_count))
    summary.add_row("Dual approval routes", str(dual_approval_count))
    summary.add_row("Duplicate candidates", str(duplicate_invoice_count))
    summary.add_row("Similar-service alerts", str(similar_service_count))
    if batch.duplicate_analysis:
        logger.info("Semantic duplicate scan: %s", batch.duplicate_analysis.semantic_status.value)
        for warning in batch.duplicate_analysis.warnings:
            logger.warning("Semantic duplicate scan warning: %s", warning)
    console.print(summary)
    logger.info("MIS report: %s", display_path(report_path))
    logger.info("Invoice batch run completed successfully")


if __name__ == "__main__":
    main()
