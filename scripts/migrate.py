#!/usr/bin/env python3
"""
Database migration runner for Lyra.

Provides versioned schema migrations with tracking.

Usage:
    python scripts/migrate.py up          # Apply all pending migrations
    python scripts/migrate.py status      # Show migration status
    python scripts/migrate.py create NAME # Create a new migration file
"""

import argparse
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

# Project root and migrations directory
PROJECT_ROOT = Path(__file__).parent.parent
MIGRATIONS_DIR = PROJECT_ROOT / "migrations"
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "lyra.db"


def get_connection(db_path: Path) -> sqlite3.Connection:
    """Get SQLite connection with proper settings."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def ensure_migrations_table(conn: sqlite3.Connection) -> None:
    """Create schema_migrations table if it doesn't exist."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()


def get_applied_migrations(conn: sqlite3.Connection) -> set[int]:
    """Get set of applied migration versions."""
    cursor = conn.execute("SELECT version FROM schema_migrations ORDER BY version")
    return {row["version"] for row in cursor.fetchall()}


def get_pending_migrations(conn: sqlite3.Connection) -> list[tuple[int, str, Path]]:
    """Get list of pending migrations as (version, name, path) tuples."""
    applied = get_applied_migrations(conn)
    pending = []

    if not MIGRATIONS_DIR.exists():
        return pending

    # Pattern: 001_name.sql
    pattern = re.compile(r"^(\d{3})_(.+)\.sql$")

    for sql_file in sorted(MIGRATIONS_DIR.glob("*.sql")):
        match = pattern.match(sql_file.name)
        if match:
            version = int(match.group(1))
            name = match.group(2)
            if version not in applied:
                pending.append((version, name, sql_file))

    return pending


def apply_migration(conn: sqlite3.Connection, version: int, name: str, path: Path) -> None:
    """Apply a single migration file."""
    sql_content = path.read_text(encoding="utf-8")

    # Split by semicolons and execute each statement
    # (SQLite executescript doesn't work well with ALTER TABLE in all cases)
    statements = [s.strip() for s in sql_content.split(";") if s.strip()]

    for statement in statements:
        # Skip comments-only statements
        if statement.startswith("--") and "\n" not in statement:
            continue

        # Handle "column already exists" gracefully for idempotency
        try:
            conn.execute(statement)
        except sqlite3.OperationalError as e:
            error_msg = str(e).lower()
            if "duplicate column" in error_msg or "already exists" in error_msg:
                print("  [SKIP] Column already exists, continuing...")
            else:
                raise

    # Record migration as applied
    conn.execute(
        "INSERT INTO schema_migrations (version, name) VALUES (?, ?)",
        (version, name)
    )
    conn.commit()


def cmd_up(db_path: Path) -> int:
    """Apply all pending migrations."""
    conn = get_connection(db_path)
    ensure_migrations_table(conn)

    pending = get_pending_migrations(conn)

    if not pending:
        print("No pending migrations.")
        return 0

    print(f"Applying {len(pending)} migration(s)...")

    for version, name, path in pending:
        print(f"  [{version:03d}] {name}...")
        try:
            apply_migration(conn, version, name, path)
            print(f"  [{version:03d}] {name} [OK]")
        except Exception as e:
            print(f"  [{version:03d}] {name} [FAILED]")
            print(f"  Error: {e}")
            conn.close()
            return 1

    conn.close()
    print(f"Applied {len(pending)} migration(s) successfully.")
    return 0


def cmd_status(db_path: Path) -> int:
    """Show migration status."""
    conn = get_connection(db_path)
    ensure_migrations_table(conn)

    applied = get_applied_migrations(conn)
    pending = get_pending_migrations(conn)

    print(f"Database: {db_path}")
    print(f"Applied: {len(applied)} migration(s)")
    print(f"Pending: {len(pending)} migration(s)")

    if applied:
        print("\nApplied migrations:")
        cursor = conn.execute(
            "SELECT version, name, applied_at FROM schema_migrations ORDER BY version"
        )
        for row in cursor.fetchall():
            print(f"  [{row['version']:03d}] {row['name']} (applied: {row['applied_at']})")

    if pending:
        print("\nPending migrations:")
        for version, name, _ in pending:
            print(f"  [{version:03d}] {name}")

    conn.close()
    return 0


def cmd_create(name: str) -> int:
    """Create a new migration file."""
    MIGRATIONS_DIR.mkdir(parents=True, exist_ok=True)

    # Find next version number
    pattern = re.compile(r"^(\d{3})_.+\.sql$")
    max_version = 0

    for sql_file in MIGRATIONS_DIR.glob("*.sql"):
        match = pattern.match(sql_file.name)
        if match:
            version = int(match.group(1))
            max_version = max(max_version, version)

    next_version = max_version + 1

    # Sanitize name
    safe_name = re.sub(r"[^a-z0-9_]", "_", name.lower())
    filename = f"{next_version:03d}_{safe_name}.sql"
    filepath = MIGRATIONS_DIR / filename

    # Create migration file with template
    template = f"""-- Migration: {name}
-- Created: {datetime.now().isoformat()}

-- Add your SQL statements here
-- Each statement should be terminated with a semicolon

"""

    filepath.write_text(template, encoding="utf-8")
    print(f"Created migration: {filepath}")
    return 0


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Database migration runner for Lyra"
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB_PATH,
        help=f"Database path (default: {DEFAULT_DB_PATH})"
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # up command
    subparsers.add_parser("up", help="Apply all pending migrations")

    # status command
    subparsers.add_parser("status", help="Show migration status")

    # create command
    create_parser = subparsers.add_parser("create", help="Create a new migration file")
    create_parser.add_argument("name", help="Migration name")

    args = parser.parse_args()

    if args.command == "up":
        return cmd_up(args.db)
    elif args.command == "status":
        return cmd_status(args.db)
    elif args.command == "create":
        return cmd_create(args.name)

    return 1


if __name__ == "__main__":
    sys.exit(main())

