"""CLI entry point for mm2ledger."""

import sys
from pathlib import Path

import click

from .config import (
    DEFAULT_CONFIG_FILE,
    DEFAULT_PASSWORD_SOURCE,
    AccountConfig,
    Config,
    generate_journal_filename,
    generate_ledger_account,
    load_config,
    merge_accounts,
    save_config,
)
from .database import discover_purpose_column, list_accounts
from .importer import import_account, import_all
from .password import resolve_password


@click.group()
@click.version_option()
def main():
    """Import MoneyMoney transactions into ledger journal files."""


@main.command()
@click.option(
    "--db-path",
    type=click.Path(),
    help="Path to MoneyMoney SQLite database.",
)
@click.option(
    "--password-source",
    help=f"Password source (default: {DEFAULT_PASSWORD_SOURCE}).",
)
@click.option(
    "--config-file",
    "-c",
    default=DEFAULT_CONFIG_FILE,
    show_default=True,
    help="Config file path.",
)
@click.option(
    "--ledger-dir",
    help="Directory for ledger journal files (default: ./ledger).",
)
@click.option(
    "--rules-file",
    help="Ledger rules file name (default: rules.journal).",
)
def config(db_path, password_source, config_file, ledger_dir, rules_file):
    """Discover accounts and create/update configuration.

    On first run, provide --db-path to specify the MoneyMoney database.
    On subsequent runs, the database path is read from the config file.
    New accounts are added as disabled — edit the config to enable them.
    """
    config_path = Path(config_file)
    existing_config = None

    if config_path.exists():
        existing_config = load_config(config_path)
        click.echo(f"Updating existing config: {config_file}")

    # Resolve database path
    effective_db_path = db_path
    if not effective_db_path and existing_config:
        effective_db_path = existing_config.database_path
    if not effective_db_path:
        raise click.UsageError(
            "No database path specified.\n"
            "Run: mm2ledger config --db-path /path/to/MoneyMoney.sqlite"
        )

    # Resolve password source
    effective_pw_source = password_source
    if not effective_pw_source and existing_config:
        effective_pw_source = existing_config.password_source
    if not effective_pw_source:
        effective_pw_source = DEFAULT_PASSWORD_SOURCE

    # Resolve password and connect to database
    try:
        pw = resolve_password(effective_pw_source)
    except (ValueError, RuntimeError) as e:
        raise click.ClickException(str(e))

    # Resolve cipher compatibility
    cipher_compat = existing_config.cipher_compatibility if existing_config else 4

    # Discover accounts
    click.echo("Connecting to database...")
    try:
        db_accounts = list_accounts(effective_db_path, pw, cipher_compat)
    except RuntimeError as e:
        raise click.ClickException(str(e))

    click.echo(f"Found {len(db_accounts)} accounts in MoneyMoney database.\n")

    # Discover purpose column
    purpose_col = discover_purpose_column(effective_db_path, pw, cipher_compat)
    if purpose_col:
        click.echo(f"Discovered purpose column: {purpose_col}")

    # Build account configs from discovered accounts
    discovered = []
    for acc in db_accounts:
        ledger_acct = generate_ledger_account(acc.name)
        discovered.append(
            AccountConfig(
                id=acc.id,
                mm_name=acc.name,
                currency=acc.currency,
                ledger_account=ledger_acct,
                journal_file=generate_journal_filename(ledger_acct),
                iban=acc.iban,
                bic=acc.bic,
            )
        )

    # Merge with existing config
    if existing_config and existing_config.accounts:
        merged, new, removed = merge_accounts(existing_config.accounts, discovered)
        if new:
            click.echo(f"\nNew accounts found ({len(new)}):")
            for acc in new:
                click.echo(f"  [{acc.id}] {acc.mm_name} ({acc.currency})")
        if removed:
            click.echo(f"\nAccounts no longer in database: {removed}")
            click.echo("  (removed from config)")
    else:
        merged = discovered
        new = discovered

    # Build final config
    final_config = Config(
        database_path=effective_db_path,
        password_source=effective_pw_source,
        cipher_compatibility=cipher_compat,
        ledger_dir=ledger_dir or (existing_config.ledger_dir if existing_config else "./ledger"),
        rules_file=rules_file or (existing_config.rules_file if existing_config else "rules.journal"),
        purpose_column=purpose_col or (existing_config.purpose_column if existing_config else None),
        accounts=merged,
    )

    save_config(final_config, config_path)
    click.echo(f"\nConfig written to {config_file}")

    # Print summary
    enabled_count = sum(1 for a in merged if a.enabled)
    click.echo(f"\nAccounts: {len(merged)} total, {enabled_count} enabled")
    click.echo("")
    for acc in merged:
        status = "enabled" if acc.enabled else "disabled"
        click.echo(f"  [{acc.id:>3}] {acc.mm_name:<40} {acc.currency:<5} {status}")

    if not enabled_count:
        click.echo(
            f"\nEdit {config_file} to enable accounts and customize ledger account names."
        )


@main.command("import")
@click.option("--all", "import_all_flag", is_flag=True, help="Import all enabled accounts.")
@click.option("--account", "account_name", help="Import a specific account by ledger name.")
@click.option(
    "--config-file",
    "-c",
    default=DEFAULT_CONFIG_FILE,
    show_default=True,
    help="Config file path.",
)
def import_cmd(import_all_flag, account_name, config_file):
    """Import transactions from MoneyMoney into ledger journals."""
    config_path = Path(config_file)
    if not config_path.exists():
        raise click.ClickException(
            f"Config file not found: {config_file}\n"
            f"Run 'mm2ledger config --db-path /path/to/db.sqlite' first."
        )

    cfg = load_config(config_path)

    if not import_all_flag and not account_name:
        raise click.UsageError(
            "Specify --all to import all enabled accounts, "
            "or --account to import a specific account."
        )

    if import_all_flag:
        results = import_all(cfg)
        total = sum(results.values())
        for acct, count in results.items():
            if count > 0:
                click.echo(f"  {acct}: {count} new transactions")
            else:
                click.echo(f"  {acct}: up to date")
        click.echo(f"\nTotal: {total} new transactions across {len(results)} accounts")

    elif account_name:
        # Find the account
        matching = [a for a in cfg.accounts if a.ledger_account == account_name]
        if not matching:
            available = [a.ledger_account for a in cfg.accounts if a.enabled]
            raise click.ClickException(
                f"Account not found: {account_name}\n"
                f"Available accounts: {', '.join(available) or '(none enabled)'}"
            )

        account = matching[0]
        if not account.enabled:
            raise click.ClickException(
                f"Account {account_name} is disabled. "
                f"Enable it in {config_file} first."
            )

        count = import_account(cfg, account)
        if count > 0:
            click.echo(f"{account.ledger_account}: {count} new transactions")
        else:
            click.echo(f"{account.ledger_account}: up to date")


@main.command("list")
@click.option(
    "--config-file",
    "-c",
    default=DEFAULT_CONFIG_FILE,
    show_default=True,
    help="Config file path.",
)
def list_cmd(config_file):
    """List configured accounts and their status."""
    config_path = Path(config_file)
    if not config_path.exists():
        raise click.ClickException(f"Config file not found: {config_file}")

    cfg = load_config(config_path)

    click.echo(f"Database: {cfg.database_path}")
    click.echo(f"Ledger dir: {cfg.ledger_dir}")
    click.echo(f"Rules file: {cfg.rules_file}")
    click.echo("")

    for acc in cfg.accounts:
        status = click.style("enabled", fg="green") if acc.enabled else click.style("disabled", fg="red")
        click.echo(
            f"  [{acc.id:>3}] {acc.mm_name:<40} → {acc.ledger_account:<40} {status}"
        )
