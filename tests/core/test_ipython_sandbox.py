import tempfile
import threading
import time

import pytest

from automatiq.core import config
from automatiq.core.ipython_sandbox import AgentSandbox


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


def test_basic_execution(sandbox: AgentSandbox):
    result = sandbox.execute('print("hello world")')
    assert "Status: Success" in result
    assert "hello world" in result


def test_state_persistence(sandbox: AgentSandbox):
    sandbox.execute("x = 42")
    result = sandbox.execute("print(x)")
    assert "Status: Success" in result
    assert "42" in result


def test_execution_error(sandbox: AgentSandbox):
    result = sandbox.execute("1 / 0")
    assert "Status: ERROR" in result
    assert "ZeroDivisionError" in result


def test_soft_timeout(sandbox: AgentSandbox):
    # This should trigger a soft timeout if custom_timeout is very short.
    # We use custom_timeout=1 and a busy loop.
    result = sandbox.execute("import time\nend = time.time() + 5\nwhile time.time() < end:\n    pass", custom_timeout=1)
    assert "Status: ERROR" in result
    assert "[TIMEOUT: Execution interrupted. State preserved.]" in result


def test_cancel_soft_interrupt(sandbox: AgentSandbox):
    """Test soft cancellation where the kernel catches KeyboardInterrupt."""
    # Start a slow task in a separate thread so we don't block the test
    results = {}

    def run_slow_code():
        # Busy loops can catch KeyboardInterrupt
        code = (
            "import time\n"
            "try:\n"
            "    end = time.time() + 5\n"
            "    while time.time() < end:\n"
            "        pass\n"
            "except KeyboardInterrupt:\n"
            "    print('caught interrupt')\n"
        )
        results["out"] = sandbox.execute(code)

    t = threading.Thread(target=run_slow_code)
    t.start()

    # Give it a moment to start executing
    time.sleep(1)

    # Trigger cancellation
    sandbox.cancel()

    # Wait for the background cancel worker to finish (max ~1.5s)
    time.sleep(2.0)

    assert sandbox.cancel_result == "preserved"
    t.join(timeout=2)
    assert "caught interrupt" in results.get("out", "")


def test_cancel_hard_kill(sandbox: AgentSandbox):
    """Test hard cancellation where the kernel ignores KeyboardInterrupt."""
    # We simulate a stubborn kernel that ignores KeyboardInterrupt
    results = {}

    def run_stubborn_code():
        code = (
            "import time\nwhile True:\n    try:\n        time.sleep(0.5)\n    except KeyboardInterrupt:\n        pass\n"
        )
        results["out"] = sandbox.execute(code, custom_timeout=10)

    t = threading.Thread(target=run_stubborn_code)
    t.start()

    time.sleep(1)

    # Trigger cancellation
    sandbox.cancel()

    # Wait for hard kill to process
    time.sleep(2)

    assert sandbox.cancel_result == "lost"
    t.join(timeout=2)
    assert "CancelledByUser" in results.get("out", "") or "Status: ERROR" in results.get("out", "")


def test_magic_reset(sandbox: AgentSandbox):
    sandbox.execute("secret_var = 'hidden_value'")
    reset_result = sandbox.execute("%reset")
    assert "RESET SUCCESSFUL" in reset_result

    check_result = sandbox.execute("print(secret_var)")
    assert "NameError" in check_result


def test_magic_restore(sandbox: AgentSandbox):
    sandbox.execute("y = 100")
    sandbox.execute("y += 50")

    # Simulate a crash/restart (this kills the kernel but preserves history in Sandbox object)
    sandbox.start_process()

    # Try to access y (should fail since kernel restarted)
    check_pre = sandbox.execute("print(y)")
    assert "NameError" in check_pre

    # Restore the state
    restore_result = sandbox.execute("%restore")
    assert "RESTORED" in restore_result
    assert "2 previous cells" in restore_result

    # Verify state is back
    check_post = sandbox.execute("print(y)")
    assert "150" in check_post


def test_syntax_error(sandbox: AgentSandbox):
    """Test standard syntax error path"""
    result = sandbox.execute("if True print('missing colon')")
    assert "Status: ERROR" in result
    assert "SyntaxError" in result


def test_shell_command(sandbox: AgentSandbox):
    """Test basic shell command execution"""
    result = sandbox.execute("!echo hello shell")
    assert "hello shell" in result
    assert "Status: Success" in result


def test_shell_command_error(sandbox: AgentSandbox):
    """Test shell command that fails"""
    result = sandbox.execute("!some_nonexistent_binary_123")
    # IPython catches the shell error and prints it, but the python cell itself 'succeeded'
    assert "Status: Success" in result
    assert "not found" in result.lower() or "not recognized" in result.lower() or "error" in result.lower()


def test_magic_view_output(sandbox: AgentSandbox):
    """Test the pagination/view_output magic command"""
    code = "for i in range(1, 101):\n    print(f'Line {i}')"
    res1 = sandbox.execute(code)
    assert "Line 1" in res1
    assert "Line 100" in res1

    # It should be Cell_1 because we are in a fresh sandbox
    view_res = sandbox.execute("%view_output Cell_1 --offset 50")
    assert "Starting at line 50" in view_res
    assert "Line 50" in view_res
    assert "Line 100" in view_res
    assert " 1 | Line 1\n" not in view_res
