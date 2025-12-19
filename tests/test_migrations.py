"""
Tests for the database migration system.

See scripts/migrate.py for the migration runner implementation.

## Test Perspectives Table

| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|---------------------|--------------------------------------|-----------------|-------|
| TC-N-01 | Fresh DB, pending migration | Equivalence - normal | Migration applied, version recorded | - |
| TC-N-02 | DB with applied migration | Equivalence - normal | No changes, status shows applied | - |
| TC-N-03 | Multiple pending migrations | Equivalence - normal | All applied in order | - |
| TC-N-04 | Migration with ALTER TABLE | Equivalence - normal | Column added successfully | - |
| TC-A-01 | Non-existent DB path | Boundary - invalid input | DB created, migration applied | Creates parent dirs |
| TC-A-02 | Malformed migration SQL | Equivalence - error | Migration fails, error reported | - |
| TC-A-03 | Empty migrations directory | Boundary - empty | No-op, no error | - |
| TC-A-04 | Duplicate column ADD | Equivalence - idempotent | Skipped gracefully, no error | - |
| TC-B-01 | Migration version 0 | Boundary - min | Applied if valid | - |
| TC-B-02 | Migration version 999 | Boundary - max practical | Applied if valid | - |
| TC-B-03 | Empty migration file | Boundary - empty | No-op, recorded as applied | - |
"""

import sqlite3

# Import the migration module
# Note: We import functions directly to test them
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from migrate import (
    apply_migration,
    cmd_create,
    cmd_status,
    cmd_up,
    ensure_migrations_table,
    get_applied_migrations,
    get_connection,
    get_pending_migrations,
)


class TestMigrationInfrastructure:
    """Tests for migration infrastructure components."""

    def test_get_connection_creates_db(self, tmp_path: Path):
        """
        TC-A-01: Test DB creation for non-existent path.

        Given: A path to a non-existent database file
        When: get_connection is called
        Then: Database file is created and connection is valid
        """
        # Given: Non-existent DB path
        db_path = tmp_path / "subdir" / "test.db"
        assert not db_path.exists()

        # When: Get connection (parent dir needs to exist for sqlite)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = get_connection(db_path)

        # Then: Connection is valid
        assert conn is not None
        cursor = conn.execute("SELECT 1")
        assert cursor.fetchone()[0] == 1
        conn.close()
        assert db_path.exists()

    def test_ensure_migrations_table_creates_table(self, tmp_path: Path):
        """
        TC-N-01 (setup): Test schema_migrations table creation.

        Given: A fresh database with no tables
        When: ensure_migrations_table is called
        Then: schema_migrations table exists with correct schema
        """
        # Given: Fresh DB
        db_path = tmp_path / "test.db"
        conn = get_connection(db_path)

        # When: Ensure table
        ensure_migrations_table(conn)

        # Then: Table exists with correct schema
        cursor = conn.execute("PRAGMA table_info(schema_migrations)")
        columns = {row[1]: row[2] for row in cursor.fetchall()}

        assert "version" in columns
        assert "name" in columns
        assert "applied_at" in columns
        assert columns["version"] == "INTEGER"

        conn.close()

    def test_get_applied_migrations_empty(self, tmp_path: Path):
        """
        TC-A-03: Test empty migrations.

        Given: A database with empty schema_migrations table
        When: get_applied_migrations is called
        Then: Returns empty set
        """
        # Given: Fresh DB with table
        db_path = tmp_path / "test.db"
        conn = get_connection(db_path)
        ensure_migrations_table(conn)

        # When: Get applied
        applied = get_applied_migrations(conn)

        # Then: Empty set
        assert applied == set()
        conn.close()

    def test_get_applied_migrations_with_data(self, tmp_path: Path):
        """
        TC-N-02: Test with existing applied migrations.

        Given: A database with applied migrations
        When: get_applied_migrations is called
        Then: Returns set of applied versions
        """
        # Given: DB with migrations
        db_path = tmp_path / "test.db"
        conn = get_connection(db_path)
        ensure_migrations_table(conn)
        conn.execute("INSERT INTO schema_migrations (version, name) VALUES (1, 'first')")
        conn.execute("INSERT INTO schema_migrations (version, name) VALUES (2, 'second')")
        conn.commit()

        # When: Get applied
        applied = get_applied_migrations(conn)

        # Then: Returns versions
        assert applied == {1, 2}
        conn.close()


class TestMigrationDiscovery:
    """Tests for migration file discovery."""

    def test_get_pending_migrations_no_dir(self, tmp_path: Path):
        """
        TC-A-03: Test with non-existent migrations directory.

        Given: No migrations directory
        When: get_pending_migrations is called
        Then: Returns empty list
        """
        # Given: DB but no migrations dir
        db_path = tmp_path / "test.db"
        conn = get_connection(db_path)
        ensure_migrations_table(conn)

        # When: Get pending (with patched MIGRATIONS_DIR)
        with patch("migrate.MIGRATIONS_DIR", tmp_path / "nonexistent"):
            pending = get_pending_migrations(conn)

        # Then: Empty list
        assert pending == []
        conn.close()

    def test_get_pending_migrations_finds_files(self, tmp_path: Path):
        """
        TC-N-01: Test migration file discovery.

        Given: Migrations directory with SQL files
        When: get_pending_migrations is called
        Then: Returns list of pending migrations in order
        """
        # Given: Migrations dir with files
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        (migrations_dir / "001_first.sql").write_text("-- first")
        (migrations_dir / "002_second.sql").write_text("-- second")
        (migrations_dir / "not_a_migration.txt").write_text("-- ignored")

        db_path = tmp_path / "test.db"
        conn = get_connection(db_path)
        ensure_migrations_table(conn)

        # When: Get pending
        with patch("migrate.MIGRATIONS_DIR", migrations_dir):
            pending = get_pending_migrations(conn)

        # Then: Returns ordered list
        assert len(pending) == 2
        assert pending[0][0] == 1  # version
        assert pending[0][1] == "first"  # name
        assert pending[1][0] == 2
        assert pending[1][1] == "second"
        conn.close()

    def test_get_pending_excludes_applied(self, tmp_path: Path):
        """
        TC-N-02: Test that applied migrations are excluded.

        Given: Some migrations already applied
        When: get_pending_migrations is called
        Then: Only unapplied migrations are returned
        """
        # Given: Migrations dir with files, one already applied
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        (migrations_dir / "001_first.sql").write_text("-- first")
        (migrations_dir / "002_second.sql").write_text("-- second")

        db_path = tmp_path / "test.db"
        conn = get_connection(db_path)
        ensure_migrations_table(conn)
        conn.execute("INSERT INTO schema_migrations (version, name) VALUES (1, 'first')")
        conn.commit()

        # When: Get pending
        with patch("migrate.MIGRATIONS_DIR", migrations_dir):
            pending = get_pending_migrations(conn)

        # Then: Only second migration pending
        assert len(pending) == 1
        assert pending[0][0] == 2
        conn.close()


class TestMigrationExecution:
    """Tests for migration execution."""

    def test_apply_migration_simple(self, tmp_path: Path):
        """
        TC-N-01: Test applying a simple migration.

        Given: A migration file with valid SQL
        When: apply_migration is called
        Then: SQL is executed and migration is recorded
        """
        # Given: Migration file
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        migration_file = migrations_dir / "001_create_test.sql"
        migration_file.write_text("""
            CREATE TABLE test_table (
                id INTEGER PRIMARY KEY,
                name TEXT
            );
        """)

        db_path = tmp_path / "test.db"
        conn = get_connection(db_path)
        ensure_migrations_table(conn)

        # When: Apply migration
        apply_migration(conn, 1, "create_test", migration_file)

        # Then: Table exists and migration recorded
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='test_table'")
        assert cursor.fetchone() is not None

        applied = get_applied_migrations(conn)
        assert 1 in applied
        conn.close()

    def test_apply_migration_alter_table(self, tmp_path: Path):
        """
        TC-N-04: Test migration with ALTER TABLE.

        Given: An existing table and ALTER TABLE migration
        When: apply_migration is called
        Then: Column is added successfully
        """
        # Given: Existing table
        db_path = tmp_path / "test.db"
        conn = get_connection(db_path)
        ensure_migrations_table(conn)
        conn.execute("CREATE TABLE domains (domain TEXT PRIMARY KEY)")
        conn.commit()

        # Given: ALTER TABLE migration
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        migration_file = migrations_dir / "001_add_column.sql"
        migration_file.write_text("""
            ALTER TABLE domains ADD COLUMN new_column INTEGER DEFAULT 0;
        """)

        # When: Apply migration
        apply_migration(conn, 1, "add_column", migration_file)

        # Then: Column exists
        cursor = conn.execute("PRAGMA table_info(domains)")
        columns = [row[1] for row in cursor.fetchall()]
        assert "new_column" in columns
        conn.close()

    def test_apply_migration_duplicate_column_graceful(self, tmp_path: Path):
        """
        TC-A-04: Test idempotent handling of duplicate column.

        Given: A table that already has the column
        When: Migration tries to add the same column
        Then: Migration completes without error (skips gracefully)
        """
        # Given: Table with column already
        db_path = tmp_path / "test.db"
        conn = get_connection(db_path)
        ensure_migrations_table(conn)
        conn.execute("CREATE TABLE domains (domain TEXT PRIMARY KEY, existing_col INTEGER)")
        conn.commit()

        # Given: Migration adding same column
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        migration_file = migrations_dir / "001_add_existing.sql"
        migration_file.write_text("""
            ALTER TABLE domains ADD COLUMN existing_col INTEGER DEFAULT 0;
        """)

        # When: Apply migration - should not raise
        apply_migration(conn, 1, "add_existing", migration_file)

        # Then: Migration recorded
        applied = get_applied_migrations(conn)
        assert 1 in applied
        conn.close()

    def test_apply_migration_empty_file(self, tmp_path: Path):
        """
        TC-B-03: Test empty migration file.

        Given: An empty migration file
        When: apply_migration is called
        Then: Migration is recorded without error
        """
        # Given: Empty migration file
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        migration_file = migrations_dir / "001_empty.sql"
        migration_file.write_text("-- This migration is intentionally empty")

        db_path = tmp_path / "test.db"
        conn = get_connection(db_path)
        ensure_migrations_table(conn)

        # When: Apply migration
        apply_migration(conn, 1, "empty", migration_file)

        # Then: Recorded as applied
        applied = get_applied_migrations(conn)
        assert 1 in applied
        conn.close()

    def test_apply_migration_malformed_sql(self, tmp_path: Path):
        """
        TC-A-02: Test malformed SQL migration.

        Given: A migration file with invalid SQL
        When: apply_migration is called
        Then: Exception is raised
        """
        # Given: Invalid SQL
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        migration_file = migrations_dir / "001_bad.sql"
        migration_file.write_text("THIS IS NOT VALID SQL AT ALL;")

        db_path = tmp_path / "test.db"
        conn = get_connection(db_path)
        ensure_migrations_table(conn)

        # When/Then: Raises exception
        with pytest.raises(sqlite3.OperationalError):
            apply_migration(conn, 1, "bad", migration_file)

        conn.close()


class TestMigrationCommands:
    """Tests for CLI commands."""

    def test_cmd_up_applies_pending(self, tmp_path: Path):
        """
        TC-N-01: Test cmd_up applies pending migrations.

        Given: Pending migrations
        When: cmd_up is called
        Then: All pending migrations are applied
        """
        # Given: Migrations
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        (migrations_dir / "001_first.sql").write_text("CREATE TABLE t1 (id INTEGER);")
        (migrations_dir / "002_second.sql").write_text("CREATE TABLE t2 (id INTEGER);")

        db_path = tmp_path / "test.db"

        # When: Run cmd_up
        with patch("migrate.MIGRATIONS_DIR", migrations_dir):
            result = cmd_up(db_path)

        # Then: Success and tables exist
        assert result == 0
        conn = get_connection(db_path)
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = [row[0] for row in cursor.fetchall()]
        assert "t1" in tables
        assert "t2" in tables
        assert "schema_migrations" in tables
        conn.close()

    def test_cmd_up_no_pending(self, tmp_path: Path):
        """
        TC-N-02: Test cmd_up with no pending migrations.

        Given: No pending migrations
        When: cmd_up is called
        Then: Returns success, no changes
        """
        # Given: No migrations
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        db_path = tmp_path / "test.db"

        # When: Run cmd_up
        with patch("migrate.MIGRATIONS_DIR", migrations_dir):
            result = cmd_up(db_path)

        # Then: Success
        assert result == 0

    def test_cmd_status_shows_applied(self, tmp_path: Path, capsys):
        """
        TC-N-02: Test cmd_status shows applied migrations.

        Given: Applied migrations
        When: cmd_status is called
        Then: Shows correct count and list
        """
        # Given: Applied migration
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        (migrations_dir / "001_first.sql").write_text("SELECT 1;")

        db_path = tmp_path / "test.db"
        conn = get_connection(db_path)
        ensure_migrations_table(conn)
        conn.execute("INSERT INTO schema_migrations (version, name) VALUES (1, 'first')")
        conn.commit()
        conn.close()

        # When: Run cmd_status
        with patch("migrate.MIGRATIONS_DIR", migrations_dir):
            result = cmd_status(db_path)

        # Then: Success and output contains info
        assert result == 0
        captured = capsys.readouterr()
        assert "Applied: 1" in captured.out
        assert "Pending: 0" in captured.out

    def test_cmd_create_new_migration(self, tmp_path: Path, capsys):
        """
        TC-N-01: Test cmd_create creates new migration file.

        Given: Empty migrations directory
        When: cmd_create is called with a name
        Then: Creates 001_name.sql file with template
        """
        # Given: Empty migrations dir
        migrations_dir = tmp_path / "migrations"
        # Note: cmd_create creates the directory

        # When: Create migration
        with patch("migrate.MIGRATIONS_DIR", migrations_dir):
            result = cmd_create("add_test_column")

        # Then: File created
        assert result == 0
        files = list(migrations_dir.glob("*.sql"))
        assert len(files) == 1
        assert "001_add_test_column.sql" in files[0].name

        content = files[0].read_text()
        assert "add_test_column" in content

    def test_cmd_create_increments_version(self, tmp_path: Path):
        """
        TC-N-03: Test cmd_create increments version number.

        Given: Existing migrations
        When: cmd_create is called
        Then: Creates next version number
        """
        # Given: Existing migrations
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        (migrations_dir / "001_first.sql").write_text("-- first")
        (migrations_dir / "002_second.sql").write_text("-- second")

        # When: Create new migration
        with patch("migrate.MIGRATIONS_DIR", migrations_dir):
            result = cmd_create("third")

        # Then: Version 003
        assert result == 0
        assert (migrations_dir / "003_third.sql").exists()


class TestBoundaryConditions:
    """Tests for boundary conditions."""

    def test_migration_version_zero(self, tmp_path: Path):
        """
        TC-B-01: Test migration version 0.

        Given: A migration file named 000_init.sql
        When: Migrations are discovered
        Then: Version 0 is handled correctly
        """
        # Given: Version 0 migration
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        (migrations_dir / "000_init.sql").write_text("CREATE TABLE init (id INTEGER);")

        db_path = tmp_path / "test.db"
        conn = get_connection(db_path)
        ensure_migrations_table(conn)

        # When: Get pending
        with patch("migrate.MIGRATIONS_DIR", migrations_dir):
            pending = get_pending_migrations(conn)

        # Then: Version 0 is included
        assert len(pending) == 1
        assert pending[0][0] == 0
        conn.close()

    def test_migration_version_large(self, tmp_path: Path):
        """
        TC-B-02: Test large migration version number.

        Given: A migration with version 999
        When: Migrations are discovered
        Then: Version 999 is handled correctly
        """
        # Given: Large version migration
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        (migrations_dir / "999_large.sql").write_text("SELECT 1;")

        db_path = tmp_path / "test.db"
        conn = get_connection(db_path)
        ensure_migrations_table(conn)

        # When: Get pending
        with patch("migrate.MIGRATIONS_DIR", migrations_dir):
            pending = get_pending_migrations(conn)

        # Then: Version 999 is included
        assert len(pending) == 1
        assert pending[0][0] == 999
        conn.close()

    def test_multiple_statements_in_migration(self, tmp_path: Path):
        """
        TC-N-03: Test migration with multiple SQL statements.

        Given: Migration file with multiple statements
        When: apply_migration is called
        Then: All statements are executed
        """
        # Given: Multi-statement migration
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        migration_file = migrations_dir / "001_multi.sql"
        migration_file.write_text("""
            CREATE TABLE table1 (id INTEGER);
            CREATE TABLE table2 (id INTEGER);
            CREATE INDEX idx_t1 ON table1(id);
        """)

        db_path = tmp_path / "test.db"
        conn = get_connection(db_path)
        ensure_migrations_table(conn)

        # When: Apply
        apply_migration(conn, 1, "multi", migration_file)

        # Then: All objects exist
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = [row[0] for row in cursor.fetchall()]
        assert "table1" in tables
        assert "table2" in tables

        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='index' AND name='idx_t1'")
        assert cursor.fetchone() is not None
        conn.close()

