#!/bin/bash
# Lyra shell - standardized exit codes

# Success
export EXIT_SUCCESS=0

# General errors (1-9)
export EXIT_ERROR=1              # General/unknown error
export EXIT_USAGE=2              # Invalid usage/arguments
export EXIT_CONFIG=3             # Configuration error (missing .env, invalid config)
export EXIT_DEPENDENCY=4         # Missing dependency (podman, uv, etc.)
export EXIT_TIMEOUT=5            # Operation timed out
export EXIT_PERMISSION=6         # Permission denied

# Resource errors (10-19)
export EXIT_NOT_FOUND=10         # Resource not found (file, container, etc.)
export EXIT_ALREADY_EXISTS=11    # Resource already exists
export EXIT_NOT_RUNNING=12       # Service/container not running
export EXIT_NOT_READY=13         # Service not ready (health check failed)

# Test-specific errors (20-29)
export EXIT_TEST_FAILED=20       # Tests failed
export EXIT_TEST_ERROR=21        # Test execution error (not test failure)
export EXIT_TEST_TIMEOUT=22      # Test timeout
export EXIT_TEST_FATAL=23        # Fatal test error (disk I/O, OOM)

# Operation errors (30-39)
export EXIT_OPERATION_FAILED=30  # Generic operation failure
export EXIT_NETWORK=31           # Network/connection error
export EXIT_CONTAINER=32         # Container operation failed


