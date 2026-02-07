"""Core import pipeline: MoneyMoney DB → CSV → ledger convert → journal."""

import csv
import json
import re
import subprocess
import tempfile
from pathlib import Path

from .config import AccountConfig, Config
from .database import get_transactions
from .password import resolve_password


def import_account(config: Config, account: AccountConfig) -> int:
    """Import transactions for a single account.

    Returns the number of new transactions imported.
    """
    password = resolve_password(config.password_source)

    transactions = get_transactions(
        config.database_path,
        password,
        account.id,
        account.start_date,
        config.purpose_column,
        config.cipher_compatibility,
    )

    if not transactions:
        return 0

    ledger_dir = Path(config.ledger_dir)
    journal_path = ledger_dir / account.journal_file
    rules_path = ledger_dir / config.rules_file

    # Create journal file if it doesn't exist
    if not journal_path.exists():
        journal_path.touch()

    # Write transactions to temporary CSV
    csv_path = _write_csv(transactions)

    try:
        output = _run_ledger_convert(
            csv_path, rules_path, journal_path, account.ledger_account
        )
    finally:
        Path(csv_path).unlink(missing_ok=True)

    if not output.strip():
        return 0

    output = _postprocess(output)

    # Append to journal
    with open(journal_path, "a") as f:
        f.write("\n")
        f.write(output)

    # Count imported transactions (lines starting with a date)
    count = len(re.findall(r"^\d{4}-\d{2}-\d{2}", output, re.MULTILINE))
    return count


def _write_csv(transactions: list[dict]) -> str:
    """Write transactions to a temporary CSV file for ledger convert."""
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, newline=""
    )
    writer = csv.writer(tmp)
    writer.writerow(["UUID", "date", "payee", "amount", "note", "account"])
    for txn in transactions:
        writer.writerow(
            [
                f"M-{txn['transaction_id']}",
                txn["value_date"],
                txn["name"],
                f"{txn['currency']} {txn['amount']}",
                f" {json.dumps(txn)}",
                "",
            ]
        )
    tmp.close()
    return tmp.name


def _run_ledger_convert(
    csv_path: str,
    rules_path: Path,
    journal_path: Path,
    account_name: str,
) -> str:
    """Run ledger convert on the CSV file."""
    cmd = [
        "ledger",
        "convert",
        csv_path,
        "--no-pager",
        "--invert",
        "--file", str(rules_path),
        "--file", str(journal_path),
        "--date-format=%Y-%m-%d",
        "--account", account_name,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    except FileNotFoundError:
        raise RuntimeError(
            "ledger is not installed.\n"
            "Install it with: brew install ledger (macOS) or apt install ledger (Debian)"
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"ledger convert failed: {e.stderr.strip()}")
    return result.stdout


def _postprocess(output: str) -> str:
    """Apply post-processing fixes to ledger convert output."""
    # Fix JSON comment formatting
    output = output.replace(";{", "; {")
    # Rename unknown expenses
    output = output.replace("Expenses:Unknown", "Unmatched")
    # Remove slashes from UUIDs to prevent false duplicate detection
    output = re.sub(r"UUID: ([A-Za-z0-9-]*)/([0-9]*)", r"UUID: \1\2", output)
    return output


def import_all(config: Config) -> dict[str, int]:
    """Import all enabled accounts.

    Returns a dict of {ledger_account: transaction_count}.
    """
    results = {}
    enabled = [acc for acc in config.accounts if acc.enabled]
    if not enabled:
        return results

    for account in enabled:
        count = import_account(config, account)
        results[account.ledger_account] = count

    return results
