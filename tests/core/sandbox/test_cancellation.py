import sys
import threading
import time

from automatiq.core.ipython_sandbox import AgentSandbox


def test_soft_cancel_python_loop(sandbox: AgentSandbox):
    """Test soft cancellation where the kernel catches KeyboardInterrupt in a python busy loop."""
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

    time.sleep(1)  # Give it a moment to start executing

    sandbox.cancel()

    time.sleep(2.0)  # Wait for the background cancel worker to finish

    assert sandbox.cancel_result == "preserved"
    t.join(timeout=2)
    assert "caught interrupt" in results.get("out", "")


def test_cancel_native_sleep(sandbox: AgentSandbox):
    """Test cancellation of time.sleep().
    On Windows, sleep blocks the thread so KeyboardInterrupt cannot be caught, resulting in a wipe.
    On POSIX, SIGINT breaks the sleep natively, resulting in preserved state.
    """
    results = {}

    def run_sleep_code():
        code = "import time\ntry:\n    time.sleep(5)\nexcept KeyboardInterrupt:\n    print('caught interrupt')\n"
        results["out"] = sandbox.execute(code, custom_timeout=10)

    t = threading.Thread(target=run_sleep_code)
    t.start()

    time.sleep(1)

    sandbox.cancel()

    time.sleep(2.0)

    if sys.platform == "win32":
        # Windows cannot interrupt time.sleep() using _thread.interrupt_main()
        # It should escalate to a hard kill.
        assert sandbox.cancel_result == "lost"
        t.join(timeout=2)
        assert "CancelledByUser" in results.get("out", "")
    else:
        # Mac/Linux can interrupt it via SIGINT
        assert sandbox.cancel_result == "preserved"
        t.join(timeout=2)
        assert "caught interrupt" in results.get("out", "")


def test_soft_timeout(sandbox: AgentSandbox):
    """Test that execution times out correctly without manual cancellation."""
    # We use custom_timeout=1 and a busy loop.
    result = sandbox.execute("import time\nend = time.time() + 5\nwhile time.time() < end:\n    pass", custom_timeout=1)
    assert "Status: ERROR" in result
    assert "[TIMEOUT: Execution interrupted. State preserved.]" in result
