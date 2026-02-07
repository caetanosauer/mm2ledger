# mm2ledger

Import transactions from [MoneyMoney](https://moneymoney-app.com/) into [ledger](https://ledger-cli.org/) journal files.

## Prerequisites

- **sqlcipher** — for reading MoneyMoney's encrypted database
- **ledger** — for transaction conversion and duplicate detection
- **Python 3.11+**

## Installation

```bash
uv tool install mm2ledger
```

Or for development:

```bash
git clone https://github.com/your/mm2ledger
cd mm2ledger
uv sync
```

## Quick Start

### 1. Configure

Point mm2ledger at your MoneyMoney database:

```bash
export MM_DB_PASSWORD='your-database-password'
mm2ledger config --db-path ~/Library/Containers/com.moneymoney-app.retail/Data/Library/Application\ Support/MoneyMoney/Database/MoneyMoney.sqlite
```

This discovers all accounts and writes `mm2ledger.toml`. Edit the file to:
- Enable the accounts you want to import (`enabled = true`)
- Set the ledger account names (e.g., `ledger_account = "Assets:Checking"`)
- Set the start date for each account

### 2. Import

```bash
# Import all enabled accounts
mm2ledger import --all

# Import a specific account
mm2ledger import --account "Assets:Checking"
```

### 3. Update config

Re-run `config` any time to pick up new accounts:

```bash
mm2ledger config
```

Existing account settings are preserved; new accounts are added as disabled.

## Configuration

### Password Sources

The database password can be provided via:

- **Environment variable** (default): `password_source = "env:MM_DB_PASSWORD"`
- **1Password CLI**: `password_source = "op://vault/item/password"`
- **macOS Keychain**: `password_source = "keychain:MoneyMoney"` *(planned)*

### Config File Format

```toml
[database]
path = "/path/to/MoneyMoney.sqlite"
password_source = "env:MM_DB_PASSWORD"
cipher_compatibility = 4

[ledger]
dir = "./ledger"
rules_file = "rules.journal"

[schema]
purpose_column = "a1717838516"

[[accounts]]
id = 1
mm_name = "My Checking"
currency = "EUR"
ledger_account = "Assets:Checking"
journal_file = "Assets_Checking.journal"
start_date = "2024-01-01"
enabled = true
```

### Categorization Rules

Create a `rules.journal` file using ledger's native payee-matching syntax:

```
account Expenses:Supermarket
  payee Edeka
  payee Lidl
  payee REWE

account Expenses:Transportation
  payee Deutsche Bahn
  payee Uber
```

## How It Works

1. Reads transactions from MoneyMoney's encrypted SQLite database via `sqlcipher`
2. Converts them to CSV with UUID-based identifiers for duplicate detection
3. Runs `ledger convert` with your rules file for automatic categorization
4. Appends new transactions to per-account journal files
5. Preserves full transaction metadata as JSON comments

## License

MIT
