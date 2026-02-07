# mm2ledger

Import transactions from [MoneyMoney](https://moneymoney-app.com/) into [ledger](https://ledger-cli.org/) journal files.

## Prerequisites

- **sqlcipher** — for reading MoneyMoney's encrypted database
- **ledger** — for transaction conversion and duplicate detection
- **Python 3.11+**

## Installation

```bash
# From local checkout
uv tool install /path/to/mm2ledger

# For development
git clone https://github.com/your/mm2ledger
cd mm2ledger
uv sync
```

## Quick Start

### 1. Configure

```bash
export MM_DB_PASSWORD='your-database-password'
mm2ledger config
```

This walks you through an interactive setup:
- Auto-discovers the MoneyMoney database at its default macOS location
- Tests the database connection and re-prompts on failure
- Lets you select which accounts to enable via a checkbox list
- Asks for ledger account names and start dates for new accounts
- Writes everything to `mm2ledger.toml`

### 2. Import

```bash
# Import all enabled accounts
mm2ledger import

# Import a specific account
mm2ledger import --account "Assets:Checking"
```

### 3. Update config

Re-run `config` any time to pick up new accounts:

```bash
mm2ledger config
```

Previously configured accounts keep their settings; new accounts are interviewed individually.

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

### Categorization Rules (Optional)

If a `rules.journal` file exists in the ledger directory, it will be used by `ledger convert` for automatic categorization via ledger's native payee-matching syntax:

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
3. Runs `ledger convert` (with optional rules file) for automatic categorization
4. Appends new transactions to per-account journal files
5. Preserves full transaction metadata as JSON comments

## License

MIT
