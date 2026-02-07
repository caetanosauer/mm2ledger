"""Password resolution from multiple sources."""

import os
import subprocess


def resolve_password(source: str) -> str:
    """Resolve a database password from the configured source.

    Supported sources:
        env:VAR_NAME        - Read from environment variable
        op://vault/item/field - Read from 1Password CLI
        keychain:service    - Read from macOS Keychain (not yet implemented)
    """
    if source.startswith("env:"):
        return _from_env(source[4:])
    elif source.startswith("op://"):
        return _from_1password(source)
    elif source.startswith("keychain:"):
        return _from_keychain(source[9:])
    else:
        raise ValueError(
            f"Unknown password source: {source!r}\n"
            f"Supported formats:\n"
            f"  env:VAR_NAME           - environment variable\n"
            f"  op://vault/item/field  - 1Password CLI\n"
            f"  keychain:service       - macOS Keychain (future)"
        )


def _from_env(var_name: str) -> str:
    value = os.environ.get(var_name)
    if not value:
        raise ValueError(
            f"Environment variable {var_name} is not set.\n"
            f"Set it with: export {var_name}='your-password'"
        )
    return value


def _from_1password(reference: str) -> str:
    try:
        result = subprocess.run(
            ["op", "read", reference],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except FileNotFoundError:
        raise RuntimeError(
            "1Password CLI (op) is not installed.\n"
            "Install it from: https://developer.1password.com/docs/cli/get-started/"
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Failed to read from 1Password: {e.stderr.strip()}")


def _from_keychain(service: str) -> str:
    raise NotImplementedError(
        "macOS Keychain support is not yet implemented.\n"
        "Use env: or op:// password sources instead."
    )
