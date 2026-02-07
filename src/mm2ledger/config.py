"""Configuration file management (TOML)."""

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import tomli_w


DEFAULT_CONFIG_FILE = "mm2ledger.toml"
DEFAULT_PASSWORD_SOURCE = "env:MM_DB_PASSWORD"
DEFAULT_CIPHER_COMPAT = 4
DEFAULT_START_DATE = "2024-01-01"


@dataclass
class AccountConfig:
    """Configuration for a single account to import."""

    id: int
    mm_name: str
    currency: str
    ledger_account: str
    journal_file: str
    start_date: str = DEFAULT_START_DATE
    enabled: bool = False
    iban: str | None = None
    bic: str | None = None


@dataclass
class Config:
    """Top-level mm2ledger configuration."""

    database_path: str
    password_source: str = DEFAULT_PASSWORD_SOURCE
    cipher_compatibility: int = DEFAULT_CIPHER_COMPAT
    ledger_dir: str = "./ledger"
    rules_file: str = "rules.journal"
    purpose_column: str | None = None
    accounts: list[AccountConfig] = field(default_factory=list)


def load_config(path: Path) -> Config:
    """Load configuration from a TOML file."""
    with open(path, "rb") as f:
        data = tomllib.load(f)

    db = data.get("database", {})
    ledger = data.get("ledger", {})
    schema = data.get("schema", {})

    accounts = []
    for acc in data.get("accounts", []):
        accounts.append(
            AccountConfig(
                id=acc["id"],
                mm_name=acc.get("mm_name", ""),
                currency=acc.get("currency", ""),
                ledger_account=acc["ledger_account"],
                journal_file=acc["journal_file"],
                start_date=acc.get("start_date", DEFAULT_START_DATE),
                enabled=acc.get("enabled", False),
                iban=acc.get("iban"),
                bic=acc.get("bic"),
            )
        )

    return Config(
        database_path=db.get("path", ""),
        password_source=db.get("password_source", DEFAULT_PASSWORD_SOURCE),
        cipher_compatibility=db.get("cipher_compatibility", DEFAULT_CIPHER_COMPAT),
        ledger_dir=ledger.get("dir", "./ledger"),
        rules_file=ledger.get("rules_file", "rules.journal"),
        purpose_column=schema.get("purpose_column"),
        accounts=accounts,
    )


def save_config(config: Config, path: Path) -> None:
    """Write configuration to a TOML file."""
    data: dict = {
        "database": {
            "path": config.database_path,
            "password_source": config.password_source,
            "cipher_compatibility": config.cipher_compatibility,
        },
        "ledger": {
            "dir": config.ledger_dir,
            "rules_file": config.rules_file,
        },
    }

    if config.purpose_column:
        data["schema"] = {"purpose_column": config.purpose_column}

    accounts_list = []
    for acc in config.accounts:
        acc_dict: dict = {
            "id": acc.id,
            "mm_name": acc.mm_name,
            "currency": acc.currency,
            "ledger_account": acc.ledger_account,
            "journal_file": acc.journal_file,
            "start_date": acc.start_date,
            "enabled": acc.enabled,
        }
        if acc.iban:
            acc_dict["iban"] = acc.iban
        if acc.bic:
            acc_dict["bic"] = acc.bic
        accounts_list.append(acc_dict)

    data["accounts"] = accounts_list

    with open(path, "wb") as f:
        tomli_w.dump(data, f)


def generate_ledger_account(mm_name: str) -> str:
    """Generate a default ledger account name from a MoneyMoney account name."""
    return f"Assets:{mm_name}"


def generate_journal_filename(ledger_account: str) -> str:
    """Generate a journal filename from a ledger account name."""
    name = ledger_account.replace(":", "_").replace(" ", "_")
    return f"{name}.journal"


def merge_accounts(
    existing: list[AccountConfig],
    discovered: list[AccountConfig],
) -> tuple[list[AccountConfig], list[AccountConfig], list[int]]:
    """Merge discovered accounts into existing configuration.

    Returns (merged_list, new_accounts, removed_ids).
    Existing account settings are preserved. New accounts are added as disabled.
    """
    existing_by_id = {acc.id: acc for acc in existing}
    discovered_by_id = {acc.id: acc for acc in discovered}

    merged = []
    new_accounts = []
    removed_ids = []

    # Preserve existing accounts that still exist in DB
    for acc in existing:
        if acc.id in discovered_by_id:
            # Update mm_name and currency from DB (may have changed)
            db_acc = discovered_by_id[acc.id]
            acc.mm_name = db_acc.mm_name
            acc.currency = db_acc.currency
            acc.iban = db_acc.iban
            acc.bic = db_acc.bic
            merged.append(acc)
        else:
            removed_ids.append(acc.id)

    # Add new accounts not in existing config
    for acc in discovered:
        if acc.id not in existing_by_id:
            new_accounts.append(acc)
            merged.append(acc)

    # Sort by id
    merged.sort(key=lambda a: a.id)

    return merged, new_accounts, removed_ids
