"""Tests for Dynamic Chrome Worker Pool configuration.

This module tests the configuration and helper functions for the
Dynamic Chrome Worker Pool (ADR-0014 Phase 3).

Each worker gets its own Chrome instance with dedicated port and profile:
- Worker 0: port=base_port, profile=prefix+00
- Worker 1: port=base_port+1, profile=prefix+01
- Worker N: port=base_port+N, profile=prefix+{N:02d}
"""

from src.utils.config import (
    get_all_chrome_ports,
    get_chrome_port,
    get_chrome_profile,
    get_num_workers,
    get_settings,
)


class TestChromeWorkerPoolConfig:
    """Tests for Dynamic Chrome Worker Pool configuration helpers."""

    # =========================================================================
    # Test Perspectives Table
    # =========================================================================
    #
    # | Case ID | Input / Precondition | Perspective | Expected Result | Notes |
    # |---------|---------------------|-------------|-----------------|-------|
    # | TC-N-01 | worker_id=0 | Normal | base_port | Worker 0 |
    # | TC-N-02 | worker_id=1 | Normal | base_port+1 | Worker 1 |
    # | TC-N-03 | worker_id=5 | Normal | base_port+5 | Worker 5 |
    # | TC-N-04 | profile worker_id=0 | Normal | "Lyra-00" | Profile 0 |
    # | TC-N-05 | profile worker_id=1 | Normal | "Lyra-01" | Profile 1 |
    # | TC-N-06 | profile worker_id=99 | Normal | "Lyra-99" | Large ID |
    # | TC-N-07 | get_all_chrome_ports | Normal | List of ports | All workers |
    # | TC-N-08 | get_num_workers | Normal | num_workers value | Config value |

    def test_get_chrome_port_worker_0(self) -> None:
        """Test that Worker 0 gets the base port.

        Given: Default configuration with chrome_base_port=9222
        When: get_chrome_port(0) is called
        Then: Returns 9222 (base_port + 0)
        """
        # Given
        settings = get_settings()
        expected_port = settings.browser.chrome_base_port

        # When
        actual_port = get_chrome_port(0)

        # Then
        assert actual_port == expected_port

    def test_get_chrome_port_worker_1(self) -> None:
        """Test that Worker 1 gets base_port + 1.

        Given: Default configuration with chrome_base_port=9222
        When: get_chrome_port(1) is called
        Then: Returns 9223 (base_port + 1)
        """
        # Given
        settings = get_settings()
        expected_port = settings.browser.chrome_base_port + 1

        # When
        actual_port = get_chrome_port(1)

        # Then
        assert actual_port == expected_port

    def test_get_chrome_port_worker_5(self) -> None:
        """Test that Worker 5 gets base_port + 5.

        Given: Default configuration with chrome_base_port=9222
        When: get_chrome_port(5) is called
        Then: Returns 9227 (base_port + 5)
        """
        # Given
        settings = get_settings()
        expected_port = settings.browser.chrome_base_port + 5

        # When
        actual_port = get_chrome_port(5)

        # Then
        assert actual_port == expected_port

    def test_get_chrome_profile_worker_0(self) -> None:
        """Test that Worker 0 gets profile 'Lyra-00'.

        Given: Default configuration with chrome_profile_prefix='Lyra-'
        When: get_chrome_profile(0) is called
        Then: Returns 'Lyra-00'
        """
        # Given
        settings = get_settings()
        expected_profile = f"{settings.browser.chrome_profile_prefix}00"

        # When
        actual_profile = get_chrome_profile(0)

        # Then
        assert actual_profile == expected_profile

    def test_get_chrome_profile_worker_1(self) -> None:
        """Test that Worker 1 gets profile 'Lyra-01'.

        Given: Default configuration with chrome_profile_prefix='Lyra-'
        When: get_chrome_profile(1) is called
        Then: Returns 'Lyra-01'
        """
        # Given
        settings = get_settings()
        expected_profile = f"{settings.browser.chrome_profile_prefix}01"

        # When
        actual_profile = get_chrome_profile(1)

        # Then
        assert actual_profile == expected_profile

    def test_get_chrome_profile_large_worker_id(self) -> None:
        """Test that large worker IDs are formatted with 2 digits.

        Given: Default configuration with chrome_profile_prefix='Lyra-'
        When: get_chrome_profile(99) is called
        Then: Returns 'Lyra-99'
        """
        # Given
        settings = get_settings()
        expected_profile = f"{settings.browser.chrome_profile_prefix}99"

        # When
        actual_profile = get_chrome_profile(99)

        # Then
        assert actual_profile == expected_profile

    def test_get_all_chrome_ports(self) -> None:
        """Test that get_all_chrome_ports returns ports for all workers.

        Given: Configuration with num_workers=N and chrome_base_port=B
        When: get_all_chrome_ports() is called
        Then: Returns [B, B+1, ..., B+N-1]
        """
        # Given
        settings = get_settings()
        num_workers = settings.concurrency.search_queue.num_workers
        base_port = settings.browser.chrome_base_port
        expected_ports = [base_port + i for i in range(num_workers)]

        # When
        actual_ports = get_all_chrome_ports()

        # Then
        assert actual_ports == expected_ports

    def test_get_num_workers(self) -> None:
        """Test that get_num_workers returns configured value.

        Given: Configuration with num_workers=N
        When: get_num_workers() is called
        Then: Returns N
        """
        # Given
        settings = get_settings()
        expected_num_workers = settings.concurrency.search_queue.num_workers

        # When
        actual_num_workers = get_num_workers()

        # Then
        assert actual_num_workers == expected_num_workers


class TestBrowserConfigStructure:
    """Tests for BrowserConfig structure changes."""

    def test_browser_config_has_chrome_base_port(self) -> None:
        """Test that BrowserConfig has chrome_base_port field.

        Given: Settings loaded from config
        When: Accessing browser config
        Then: chrome_base_port field exists and is an integer
        """
        # Given
        settings = get_settings()

        # When/Then
        assert hasattr(settings.browser, "chrome_base_port")
        assert isinstance(settings.browser.chrome_base_port, int)

    def test_browser_config_has_chrome_profile_prefix(self) -> None:
        """Test that BrowserConfig has chrome_profile_prefix field.

        Given: Settings loaded from config
        When: Accessing browser config
        Then: chrome_profile_prefix field exists and is a string
        """
        # Given
        settings = get_settings()

        # When/Then
        assert hasattr(settings.browser, "chrome_profile_prefix")
        assert isinstance(settings.browser.chrome_profile_prefix, str)

    def test_browser_config_no_chrome_port(self) -> None:
        """Test that BrowserConfig does NOT have deprecated chrome_port field.

        Given: Settings loaded from config
        When: Accessing browser config
        Then: chrome_port field does NOT exist (replaced by chrome_base_port)
        """
        # Given
        settings = get_settings()

        # When/Then
        assert not hasattr(settings.browser, "chrome_port")


class TestWorkerIsolationConsistency:
    """Tests for Worker isolation consistency across the system."""

    def test_port_uniqueness_for_workers(self) -> None:
        """Test that each worker gets a unique port.

        Given: N workers configured
        When: Calculating ports for all workers
        Then: All ports are unique
        """
        # Given
        num_workers = get_num_workers()

        # When
        ports = [get_chrome_port(i) for i in range(num_workers)]

        # Then
        assert len(ports) == len(set(ports)), "Ports must be unique for each worker"

    def test_profile_uniqueness_for_workers(self) -> None:
        """Test that each worker gets a unique profile.

        Given: N workers configured
        When: Calculating profiles for all workers
        Then: All profiles are unique
        """
        # Given
        num_workers = get_num_workers()

        # When
        profiles = [get_chrome_profile(i) for i in range(num_workers)]

        # Then
        assert len(profiles) == len(set(profiles)), "Profiles must be unique for each worker"

    def test_port_profile_consistency(self) -> None:
        """Test that port and profile calculations are consistent.

        Given: N workers configured
        When: Getting ports and profiles for all workers
        Then: Number of ports equals number of profiles equals num_workers
        """
        # Given
        num_workers = get_num_workers()

        # When
        ports = get_all_chrome_ports()
        profiles = [get_chrome_profile(i) for i in range(num_workers)]

        # Then
        assert len(ports) == num_workers
        assert len(profiles) == num_workers
