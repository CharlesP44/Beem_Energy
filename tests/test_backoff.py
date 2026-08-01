# Copyright (c) 2025 CharlesP44
# SPDX-License-Identifier: MIT
import pytest
import time
from unittest.mock import Mock
from custom_components.beem_energy.coordinator import BackoffState


class TestBackoffState:
    """Test backoff state management."""

    def test_backoff_state_initial_state(self):
        """Test initial backoff state."""
        backoff = BackoffState()
        assert backoff.retry_count == 0
        assert backoff.next_allowed_time == 0.0
        assert backoff.is_allowed(time.time()) is True

    def test_backoff_state_429_sets_15_min_delay(self):
        """Test 429 error sets 15-minute backoff."""
        backoff = BackoffState()
        now = time.time()
        backoff.handle_429(now)
        
        assert backoff.retry_count == 1
        assert backoff.next_allowed_time == now + 15 * 60
        assert backoff.is_allowed(now) is False
        assert backoff.is_allowed(now + 15 * 60) is True

    def test_backoff_state_5xx_exponential(self):
        """Test 5xx error uses exponential backoff."""
        backoff = BackoffState()
        now = time.time()
        
        # First 5xx: 5 * 2^0 = 5 seconds
        backoff.handle_5xx(now)
        assert backoff.retry_count == 1
        assert backoff.next_allowed_time == now + 5
        
        # Second 5xx: 5 * 2^1 = 10 seconds
        now = backoff.next_allowed_time
        backoff.handle_5xx(now)
        assert backoff.retry_count == 2
        assert backoff.next_allowed_time == now + 10
        
        # Third 5xx: 5 * 2^2 = 20 seconds
        now = backoff.next_allowed_time
        backoff.handle_5xx(now)
        assert backoff.retry_count == 3
        assert backoff.next_allowed_time == now + 20

    def test_backoff_state_5xx_max_cap(self):
        """Test 5xx backoff caps at 300 seconds (5 minutes)."""
        backoff = BackoffState()
        now = time.time()
        
        # Force retry count to high value to test cap
        backoff.retry_count = 7  # 5 * 2^7 = 640 > 300
        backoff.handle_5xx(now)
        
        # Should cap at 300
        assert backoff.next_allowed_time == now + 300

    def test_backoff_state_reset(self):
        """Test reset clears backoff state on success."""
        backoff = BackoffState()
        now = time.time()
        
        backoff.handle_429(now)
        assert backoff.retry_count == 1
        assert backoff.next_allowed_time > now
        
        backoff.reset()
        assert backoff.retry_count == 0
        assert backoff.next_allowed_time == 0.0
        assert backoff.is_allowed(now) is True

    def test_backoff_state_warning_throttle(self):
        """Test warning throttling (60-second window)."""
        backoff = BackoffState()
        now = time.time()
        
        # First warning should be allowed
        assert backoff.can_warn(now) is True
        assert backoff.last_warning_time == now
        
        # Immediate second warning should be throttled
        assert backoff.can_warn(now + 1) is False
        
        # After 60 seconds, warning should be allowed
        assert backoff.can_warn(now + 60) is True
        assert backoff.last_warning_time == now + 60
