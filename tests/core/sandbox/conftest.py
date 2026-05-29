import os
import tempfile
import time

import pytest

from automatiq.core import config
from automatiq.core.bin_manager import ensure_binaries
from automatiq.core.ipython_sandbox import AgentSandbox


@pytest.fixture(scope="session", autouse=True)
def download_test_binaries():
    """Ensure required sandbox binaries are downloaded once before any tests run."""
    if os.environ.get("GITHUB_ACTIONS") == "true":
        # Only download rg and busybox (on Windows) inside GitHub Workflows
        ensure_binaries(tools=["rg", "busybox"])
    else:
        # Full suite download for local developer testing
        ensure_binaries()


@pytest.fixture
def sandbox():
    """Provides a fresh, isolated AgentSandbox instance for each test."""
    with tempfile.TemporaryDirectory() as temp_dir:
        sb = AgentSandbox(working_dir=temp_dir, timeout_seconds=2, bin_path=str(config.BIN_DIR))
        try:
            yield sb
        finally:
            sb.close()
            # Give Windows processes a moment to fully release file locks
            time.sleep(0.5)
