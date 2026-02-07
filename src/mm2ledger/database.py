"""SQLCipher database access for MoneyMoney."""

import json
import re
import subprocess
from dataclasses import dataclass


@dataclass
class Account:
    """A MoneyMoney account as stored in the database."""

    id: int
    name: str
    currency: str
    iban: str | None = None
    bic: str | None = None


def _run_sqlcipher(
    db_path: str,
    password: str,
    sql: str,
    cipher_compatibility: int = 4,
) -> str:
    """Execute a SQL query against an encrypted MoneyMoney database.

    Returns the raw stdout output (JSON).
    """
    cmd = [
        "sqlcipher",
        db_path,
        "-cmd", ".output /dev/null",
        "-cmd", f"PRAGMA key='{password}'",
        "-cmd", f"PRAGMA cipher_compatibility={cipher_compatibility}",
        "-cmd", ".mode json",
        "-cmd", ".output",
    ]
    try:
        result = subprocess.run(
            cmd, input=sql, capture_output=True, text=True, check=True
        )
    except FileNotFoundError:
        raise RuntimeError(
            "sqlcipher is not installed.\n"
            "Install it with: brew install sqlcipher (macOS)"
        )
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.strip()
        if "file is not a database" in stderr or "not a db" in stderr:
            raise RuntimeError(
                "Failed to open database. Check that the password is correct "
                "and the database path is valid."
            )
        raise RuntimeError(f"sqlcipher error: {stderr}")
    return result.stdout


def query(
    db_path: str,
    password: str,
    sql: str,
    cipher_compatibility: int = 4,
) -> list[dict]:
    """Execute a SQL query and return parsed JSON rows."""
    output = _run_sqlcipher(db_path, password, sql, cipher_compatibility)
    output = output.strip()
    if not output:
        return []
    return json.loads(output)


def list_accounts(
    db_path: str,
    password: str,
    cipher_compatibility: int = 4,
) -> list[Account]:
    """List all accounts in the MoneyMoney database."""
    rows = query(
        db_path,
        password,
        "SELECT rowid, name, currency, iban, bic FROM accounts;",
        cipher_compatibility,
    )
    return [
        Account(
            id=row["rowid"],
            name=row["name"],
            currency=row.get("currency", ""),
            iban=row.get("iban"),
            bic=row.get("bic"),
        )
        for row in rows
    ]


def discover_purpose_column(
    db_path: str,
    password: str,
    cipher_compatibility: int = 4,
) -> str | None:
    """Discover the dynamically-named purpose column in the transactions table.

    MoneyMoney uses columns named like 'a1717838516' (a + timestamp) for
    user-defined fields. This function finds such columns.
    """
    rows = query(
        db_path,
        password,
        "PRAGMA table_info(transactions);",
        cipher_compatibility,
    )
    # Look for columns matching the pattern a<digits> (dynamic columns)
    dynamic_cols = [
        row["name"]
        for row in rows
        if re.match(r"^a\d+$", row["name"])
    ]
    if len(dynamic_cols) == 1:
        return dynamic_cols[0]
    elif len(dynamic_cols) > 1:
        # Return all found — the config command will let the user pick
        return dynamic_cols[0]  # default to first one
    return None


def get_transactions(
    db_path: str,
    password: str,
    account_id: int,
    start_date: str,
    purpose_column: str | None = None,
    cipher_compatibility: int = 4,
) -> list[dict]:
    """Get transactions for a specific account since start_date."""
    purpose_select = f", t.{purpose_column} as purpose" if purpose_column else ""

    sql = f"""\
SELECT
    t.rowid as transaction_id,
    date(timestamp, 'unixepoch') as booking_date,
    date(value_timestamp, 'unixepoch') as value_date,
    t.amount,
    t.currency,
    t.eref,
    t.mref,
    t.kref,
    t.cred,
    t.unformatted_type as type,
    t.name as name{purpose_select},
    a.rowid as account_id,
    a.bic,
    a.iban,
    a.name as account_name
FROM
    transactions t, accounts a
WHERE
    t.local_account_key = a.rowid
    AND booked = 1
    AND a.rowid = {int(account_id)}
    AND date(value_timestamp, 'unixepoch') >= '{start_date}'
ORDER BY
    transaction_id ASC;"""

    return query(db_path, password, sql, cipher_compatibility)
