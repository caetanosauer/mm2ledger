"""CLI entry point for mm2ledger."""

from pathlib import Path

import click
import questionary

from .config import (
    DEFAULT_CONFIG_FILE,
    DEFAULT_PASSWORD_SOURCE,
    DEFAULT_START_DATE,
    AccountConfig,
    Config,
    generate_journal_filename,
    generate_ledger_account,
    load_config,
    merge_accounts,
    save_config,
)
from .database import discover_purpose_column, find_database, list_accounts
from .importer import import_account, import_all
from .password import resolve_password


@click.group()
@click.version_option()
def main():
    """Import MoneyMoney transactions into ledger journal files."""


def _prompt_database_path(default: str | None = None) -> str:
    """Prompt for database path, auto-discovering if possible."""
    discovered = find_database()
    effective_default = default or discovered

    if effective_default:
        path = questionary.text(
            "MoneyMoney database path:",
            default=effective_default,
        ).ask()
    else:
        path = questionary.text(
            "MoneyMoney database path (not auto-detected):",
        ).ask()

    if not path:
        raise click.Abort()
    return path


def _prompt_password_source(default: str = DEFAULT_PASSWORD_SOURCE) -> str:
    """Prompt for password source type, then details."""
    # Determine default selection from existing source
    if default.startswith("op://"):
        default_type = "1password"
        default_value = default
    else:
        default_type = "env"
        default_value = default.removeprefix("env:")

    source_type = questionary.select(
        "Password source:",
        choices=[
            questionary.Choice("Environment variable", value="env"),
            questionary.Choice("1Password CLI", value="1password"),
        ],
        default="env" if default_type == "env" else "1password",
    ).ask()
    if not source_type:
        raise click.Abort()

    if source_type == "env":
        var_name = questionary.text(
            "Environment variable name:",
            default=default_value if default_type == "env" else "MM_DB_PASSWORD",
        ).ask()
        if not var_name:
            raise click.Abort()
        return f"env:{var_name}"
    else:
        op_ref = questionary.text(
            "1Password reference (op://vault/item/field):",
            default=default_value if default_type == "1password" else "op://",
        ).ask()
        if not op_ref:
            raise click.Abort()
        return op_ref


def _test_connection(db_path: str, pw_source: str, cipher_compat: int = 4):
    """Test database connection. Returns (password, accounts, purpose_col) or raises."""
    pw = resolve_password(pw_source)
    accounts = list_accounts(db_path, pw, cipher_compat)
    purpose_col = discover_purpose_column(db_path, pw, cipher_compat)
    return pw, accounts, purpose_col


def _prompt_account_selection(
    discovered: list[AccountConfig],
    existing_enabled_ids: set[int] | None = None,
) -> list[AccountConfig]:
    """Show checkbox list of accounts, return selected ones."""
    choices = []
    for acc in discovered:
        label = f"[{acc.id:>3}] {acc.mm_name} ({acc.currency})"
        checked = acc.id in existing_enabled_ids if existing_enabled_ids else False
        choices.append(questionary.Choice(title=label, value=acc.id, checked=checked))

    selected_ids = questionary.checkbox(
        "Select accounts to enable:",
        choices=choices,
    ).ask()

    if selected_ids is None:
        raise click.Abort()

    selected_set = set(selected_ids)
    for acc in discovered:
        acc.enabled = acc.id in selected_set

    return [acc for acc in discovered if acc.enabled]


def _prompt_account_details(
    account: AccountConfig,
    existing: AccountConfig | None = None,
) -> None:
    """Prompt for per-account ledger name and start date."""
    default_ledger = existing.ledger_account if existing else account.ledger_account
    default_start = existing.start_date if existing else DEFAULT_START_DATE

    click.echo(f"\n  [{account.id}] {account.mm_name} ({account.currency})")

    ledger_name = questionary.text(
        "    Ledger account:",
        default=default_ledger,
    ).ask()
    if not ledger_name:
        raise click.Abort()
    account.ledger_account = ledger_name
    account.journal_file = generate_journal_filename(ledger_name)

    start_date = questionary.text(
        "    Start date:",
        default=default_start,
    ).ask()
    if not start_date:
        raise click.Abort()
    account.start_date = start_date


def _write_index_journal(cfg: Config) -> None:
    """Write index.journal with include directives for all enabled accounts."""
    ledger_dir = Path(cfg.ledger_dir)
    ledger_dir.mkdir(parents=True, exist_ok=True)
    index_path = ledger_dir / "index.journal"

    lines = []
    if cfg.rules_file:
        rules_path = ledger_dir / cfg.rules_file
        if rules_path.exists():
            lines.append(f"include {cfg.rules_file}")

    for acc in cfg.accounts:
        if acc.enabled:
            lines.append(f"include {acc.journal_file}")

    index_path.write_text("\n".join(lines) + "\n")
    click.echo(f"Written {index_path}")


@main.command()
@click.option(
    "--config-file",
    "-c",
    default=DEFAULT_CONFIG_FILE,
    show_default=True,
    help="Config file path.",
)
def config(config_file):
    """Interactive setup — discover accounts and create/update configuration."""
    config_path = Path(config_file)
    existing_config = None

    if config_path.exists():
        existing_config = load_config(config_path)
        click.echo(f"Updating existing config: {config_file}\n")

    # 1. Database path
    default_db = existing_config.database_path if existing_config else None
    db_path = _prompt_database_path(default=default_db)

    # 2. Password source — prompt and test connection in a loop
    default_pw = existing_config.password_source if existing_config else DEFAULT_PASSWORD_SOURCE
    cipher_compat = existing_config.cipher_compatibility if existing_config else 4

    while True:
        pw_source = _prompt_password_source(default=default_pw)
        click.echo("Testing connection...")
        try:
            _pw, db_accounts, purpose_col = _test_connection(db_path, pw_source, cipher_compat)
            click.echo(
                click.style(f"Connected — found {len(db_accounts)} accounts.", fg="green")
            )
            break
        except (ValueError, RuntimeError) as e:
            click.echo(click.style(f"Connection failed: {e}", fg="red"))
            default_pw = pw_source  # keep what they typed as default for retry

    # 3. Ledger directory
    default_ledger_dir = existing_config.ledger_dir if existing_config else "./ledger"
    ledger_dir = questionary.text(
        "Ledger directory:", default=default_ledger_dir
    ).ask()
    if not ledger_dir:
        raise click.Abort()

    rules_file = existing_config.rules_file if existing_config else "rules.journal"

    if purpose_col:
        click.echo(f"Discovered purpose column: {purpose_col}")

    # 5. Build discovered account configs
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

    # Merge with existing config to preserve settings
    existing_by_id: dict[int, AccountConfig] = {}
    if existing_config and existing_config.accounts:
        merged, _new, removed = merge_accounts(existing_config.accounts, discovered)
        existing_by_id = {a.id: a for a in existing_config.accounts}
        if removed:
            click.echo(f"\nAccounts no longer in database: {removed}")
    else:
        merged = discovered

    # 6. Account selection — checkbox with previously enabled ones pre-checked
    existing_enabled_ids = {
        a.id for a in existing_config.accounts if a.enabled
    } if existing_config else None

    click.echo("")
    enabled_accounts = _prompt_account_selection(merged, existing_enabled_ids)

    # 7. Per-account customization — only interview newly selected accounts
    previously_configured_ids = set(existing_by_id.keys()) if existing_by_id else set()
    accounts_needing_interview = [
        acc for acc in enabled_accounts if acc.id not in previously_configured_ids
    ]

    if accounts_needing_interview:
        click.echo(f"\nConfigure {len(accounts_needing_interview)} new account(s):")
        for acc in accounts_needing_interview:
            _prompt_account_details(acc, existing_by_id.get(acc.id))

    # 8. Save
    final_config = Config(
        database_path=db_path,
        password_source=pw_source,
        cipher_compatibility=cipher_compat,
        ledger_dir=ledger_dir,
        rules_file=rules_file,
        purpose_column=purpose_col or (existing_config.purpose_column if existing_config else None),
        accounts=merged,
    )

    save_config(final_config, config_path)
    click.echo(f"\nConfig written to {config_file}")

    # Generate index.journal with includes for all enabled accounts
    _write_index_journal(final_config)

    # Print summary
    enabled_count = sum(1 for a in merged if a.enabled)
    click.echo(f"Accounts: {len(merged)} total, {enabled_count} enabled\n")
    for acc in merged:
        status = click.style("enabled", fg="green") if acc.enabled else click.style("disabled", fg="red")
        click.echo(f"  [{acc.id:>3}] {acc.mm_name:<40} {status}")


@main.command("import")
@click.option("--account", "account_name", help="Import only this account (by ledger name). Default: all enabled.")
@click.option(
    "--config-file",
    "-c",
    default=DEFAULT_CONFIG_FILE,
    show_default=True,
    help="Config file path.",
)
def import_cmd(account_name, config_file):
    """Import transactions from MoneyMoney into ledger journals.

    Imports all enabled accounts by default, or a single account with --account.
    """
    config_path = Path(config_file)
    if not config_path.exists():
        raise click.ClickException(
            f"Config file not found: {config_file}\n"
            f"Run 'mm2ledger config' first."
        )

    cfg = load_config(config_path)

    if not account_name:
        results = import_all(cfg)
        total = sum(results.values())
        for acct, count in results.items():
            if count > 0:
                click.echo(f"  {acct}: {count} new transactions")
            else:
                click.echo(f"  {acct}: up to date")
        click.echo(f"\nTotal: {total} new transactions across {len(results)} accounts")

    else:
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
