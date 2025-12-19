"""
Tests for cloud agent environment detection.

This module tests the environment detection and test skip logic
added for cloud agent compatibility (Cursor, Claude Code, GitHub Actions, etc.)
"""

import os
import pytest
from unittest.mock import patch


class TestCloudAgentDetection:
    """Test cloud agent environment detection."""
    
    def test_detect_environment_returns_environment_info(self):
        """Test that detect_environment returns proper EnvironmentInfo."""
        from tests.conftest import detect_environment, EnvironmentInfo
        
        env = detect_environment()
        
        assert isinstance(env, EnvironmentInfo)
        assert isinstance(env.is_cloud_agent, bool)
        assert isinstance(env.is_e2e_capable, bool)
        assert isinstance(env.is_wsl, bool)
        assert isinstance(env.is_container, bool)
        assert isinstance(env.has_display, bool)
    
    def test_cursor_cloud_agent_detection(self):
        """Test Cursor Cloud Agent environment detection."""
        from tests.conftest import detect_environment, CloudAgentType
        
        with patch.dict(os.environ, {"CURSOR_CLOUD_AGENT": "true"}):
            env = detect_environment()
            assert env.is_cloud_agent is True
            assert env.cloud_agent_type == CloudAgentType.CURSOR
    
    def test_cursor_session_id_detection(self):
        """Test Cursor detection via CURSOR_SESSION_ID."""
        from tests.conftest import detect_environment, CloudAgentType
        
        with patch.dict(os.environ, {"CURSOR_SESSION_ID": "abc123"}, clear=False):
            # Clear other cloud agent vars
            env_copy = os.environ.copy()
            for key in ["CURSOR_CLOUD_AGENT", "CLAUDE_CODE", "GITHUB_ACTIONS", "GITLAB_CI", "CI"]:
                env_copy.pop(key, None)
            env_copy["CURSOR_SESSION_ID"] = "abc123"
            
            with patch.dict(os.environ, env_copy, clear=True):
                env = detect_environment()
                assert env.is_cloud_agent is True
                assert env.cloud_agent_type == CloudAgentType.CURSOR
    
    def test_claude_code_detection(self):
        """Test Claude Code environment detection."""
        from tests.conftest import detect_environment, CloudAgentType
        
        # Clear other cloud agent vars and set CLAUDE_CODE
        env_copy = {k: v for k, v in os.environ.items() 
                   if k not in ["CURSOR_CLOUD_AGENT", "CURSOR_SESSION_ID", "CURSOR_BACKGROUND", 
                               "GITHUB_ACTIONS", "GITLAB_CI", "CI"]}
        env_copy["CLAUDE_CODE"] = "true"
        
        with patch.dict(os.environ, env_copy, clear=True):
            env = detect_environment()
            assert env.is_cloud_agent is True
            assert env.cloud_agent_type == CloudAgentType.CLAUDE_CODE
    
    def test_github_actions_detection(self):
        """Test GitHub Actions environment detection."""
        from tests.conftest import detect_environment, CloudAgentType
        
        env_copy = {k: v for k, v in os.environ.items() 
                   if k not in ["CURSOR_CLOUD_AGENT", "CURSOR_SESSION_ID", "CURSOR_BACKGROUND", 
                               "CLAUDE_CODE", "GITLAB_CI", "CI"]}
        env_copy["GITHUB_ACTIONS"] = "true"
        
        with patch.dict(os.environ, env_copy, clear=True):
            env = detect_environment()
            assert env.is_cloud_agent is True
            assert env.cloud_agent_type == CloudAgentType.GITHUB_ACTIONS
    
    def test_gitlab_ci_detection(self):
        """Test GitLab CI environment detection."""
        from tests.conftest import detect_environment, CloudAgentType
        
        env_copy = {k: v for k, v in os.environ.items() 
                   if k not in ["CURSOR_CLOUD_AGENT", "CURSOR_SESSION_ID", "CURSOR_BACKGROUND", 
                               "CLAUDE_CODE", "GITHUB_ACTIONS", "CI"]}
        env_copy["GITLAB_CI"] = "true"
        
        with patch.dict(os.environ, env_copy, clear=True):
            env = detect_environment()
            assert env.is_cloud_agent is True
            assert env.cloud_agent_type == CloudAgentType.GITLAB_CI
    
    def test_generic_ci_detection(self):
        """Test generic CI environment detection."""
        from tests.conftest import detect_environment, CloudAgentType
        
        env_copy = {k: v for k, v in os.environ.items() 
                   if k not in ["CURSOR_CLOUD_AGENT", "CURSOR_SESSION_ID", "CURSOR_BACKGROUND", 
                               "CLAUDE_CODE", "GITHUB_ACTIONS", "GITLAB_CI"]}
        env_copy["CI"] = "true"
        
        with patch.dict(os.environ, env_copy, clear=True):
            env = detect_environment()
            assert env.is_cloud_agent is True
            assert env.cloud_agent_type == CloudAgentType.GENERIC_CI
    
    def test_is_cloud_agent_function(self):
        """Test is_cloud_agent helper function."""
        from tests.conftest import is_cloud_agent
        
        result = is_cloud_agent()
        assert isinstance(result, bool)
    
    def test_is_e2e_capable_function(self):
        """Test is_e2e_capable helper function."""
        from tests.conftest import is_e2e_capable
        
        result = is_e2e_capable()
        assert isinstance(result, bool)
    
    def test_cloud_agent_type_enum_values(self):
        """Test CloudAgentType enum has expected values."""
        from tests.conftest import CloudAgentType
        
        expected_types = ["none", "cursor", "claude_code", "github_actions", 
                         "gitlab_ci", "generic_ci", "headless"]
        
        actual_types = [t.value for t in CloudAgentType]
        
        for expected in expected_types:
            assert expected in actual_types, f"Missing CloudAgentType: {expected}"


class TestEnvironmentInfoDataclass:
    """Test EnvironmentInfo dataclass."""
    
    def test_environment_info_fields(self):
        """Test EnvironmentInfo has all expected fields."""
        from tests.conftest import EnvironmentInfo, CloudAgentType
        
        env = EnvironmentInfo(
            is_cloud_agent=True,
            cloud_agent_type=CloudAgentType.CURSOR,
            is_e2e_capable=False,
            is_wsl=False,
            is_container=True,
            has_display=False,
        )
        
        assert env.is_cloud_agent is True
        assert env.cloud_agent_type == CloudAgentType.CURSOR
        assert env.is_e2e_capable is False
        assert env.is_wsl is False
        assert env.is_container is True
        assert env.has_display is False
