"""
Recorder sub-package — captures a full browser session (network + video + actions)
and compiles it into a structured workspace dump for the agent.

Usage:
    from automatiq.recorder import run_recording
    run_recording("https://example.com")
"""

import asyncio
import atexit
import logging
import os
import shutil
import signal
import sys
import tempfile
import threading
import time
import urllib.request

from .. import config
from .blocklist_db import BlocklistDB
from .browser_agent import BrowserAgent
from .data_compressor import compile_workspace
from .video_recorder import ActionVideoRecorder

logger = logging.getLogger(__name__)

# Module-level refs so the SIGINT handler can reach them
_browser_agent: BrowserAgent | None = None
_video_recorder: ActionVideoRecorder | None = None


def _handle_sigint(signum, frame):
    """Ctrl+C during recording = graceful stop."""
    logger.info("Ctrl+C detected. Shutting down recorder...")
    if _browser_agent:
        _browser_agent.stop()
    if _video_recorder:
        _video_recorder.stop()


# ---------------------------------------------------------------------------
# Esc-key listener for the compilation phase.
#
# Same pattern as the agent loop in main.py: a daemon thread polls for the
# Esc key and sets a threading.Event.  The AI analysis loop in
# data_compressor.py checks the event between segments.
# ---------------------------------------------------------------------------


class EscCancelled(Exception):
    """Raised by run_interruptible() when Esc is pressed during a blocking call."""


_esc_flag = threading.Event()
_esc_monitor_active = threading.Event()
_esc_thread_started = False
_original_term_attrs = None


def _restore_terminal():
    global _original_term_attrs
    if _original_term_attrs is not None:
        try:
            import termios

            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, _original_term_attrs)
            termios.tcflush(sys.stdin.fileno(), termios.TCIFLUSH)
        except Exception:
            pass
        _original_term_attrs = None


def _start_esc_listener():
    """Spawn a daemon thread that watches for Esc (platform-appropriate)."""
    global _esc_thread_started
    if _esc_thread_started:
        return
    _esc_thread_started = True

    if sys.platform == "win32":
        import msvcrt

        def _listen():
            while True:
                _esc_monitor_active.wait()
                while _esc_monitor_active.is_set():
                    if msvcrt.kbhit():
                        key = msvcrt.getch()
                        if key == b"\x1b":
                            _esc_flag.set()
                            _esc_monitor_active.clear()
                            break
                    time.sleep(0.05)
    else:
        import select
        import termios
        import tty

        def _listen():
            fd = sys.stdin.fileno()
            while True:
                _esc_monitor_active.wait()
                old = termios.tcgetattr(fd)
                global _original_term_attrs
                if _original_term_attrs is None:
                    _original_term_attrs = termios.tcgetattr(fd)
                    atexit.register(_restore_terminal)
                try:
                    tty.setcbreak(fd)
                    while _esc_monitor_active.is_set():
                        ready, _, _ = select.select([sys.stdin], [], [], 0.05)
                        if ready:
                            ch = os.read(fd, 1)
                            if ch == b"\x1b":
                                _esc_flag.set()
                                _esc_monitor_active.clear()
                                break
                finally:
                    termios.tcsetattr(fd, termios.TCSADRAIN, old)
                    termios.tcflush(fd, termios.TCIFLUSH)

    threading.Thread(target=_listen, daemon=True).start()


def _activate_esc_monitor():
    """Start watching for Esc (called when compilation begins)."""
    if sys.stdin.isatty():
        _start_esc_listener()
    _esc_flag.clear()
    _esc_monitor_active.set()


def _deactivate_esc_monitor():
    """Stop watching for Esc."""
    _esc_monitor_active.clear()
    _esc_flag.clear()


def check_esc_pressed() -> bool:
    """Return True if Esc was pressed since monitoring was activated."""
    return _esc_flag.is_set()


def clear_esc_flag() -> None:
    """Reset the Esc flag (e.g. after the user chooses to continue)."""
    _esc_flag.clear()


def run_interruptible(fn, *args, **kwargs):
    """Run *fn* in a daemon thread; raise EscCancelled if Esc is pressed."""
    result_box = [None]
    error_box = [None]
    done = threading.Event()

    def _worker():
        try:
            result_box[0] = fn(*args, **kwargs)
        except Exception as exc:
            error_box[0] = exc
        finally:
            done.set()

    t = threading.Thread(target=_worker, daemon=True)
    t.start()

    while not done.is_set():
        if _esc_flag.is_set():
            raise EscCancelled()
        done.wait(timeout=0.15)

    if error_box[0] is not None:
        raise error_box[0]
    return result_box[0]


def _init_blocklist() -> BlocklistDB:
    """Create (or open) the persistent blocklist DB and ensure all configured
    sources are downloaded and loaded. Skips re-downloading files that already
    exist on disk."""
    db = BlocklistDB(db_path=str(config.BLOCKLIST_DB))

    for name, url in config.BLOCKLIST_SOURCES.items():
        hosts_file = config.BLOCKLIST_DIR / f"{name}.txt"

        if not hosts_file.exists():
            logger.info(f"Downloading blocklist '{name}' ...")
            try:
                urllib.request.urlretrieve(url, str(hosts_file))
                logger.info(f"Saved {hosts_file.name}")
            except Exception as exc:
                logger.warning(f"Failed to download blocklist '{name}': {exc}")
                continue

        count = db.load_file(str(hosts_file), source_name=name, source_url=url)
        logger.debug(f"{name}: {count:,} domains")

    return db


def run_recording(url: str = "about:blank") -> bool:
    """Run the full recording pipeline: browser → video → compile workspace.

    1. Launches Chrome with CDP instrumentation and screen capture.
    2. User browses freely; Ctrl+C stops the session.
    3. Compiles the captured data into output/workspace/session_dump/.

    Args:
        url: Starting URL to navigate to.

    Returns:
        True if the workspace was compiled successfully, False otherwise.
    """
    global _browser_agent, _video_recorder

    # ensure_output_dirs() is called by __main__.py during the preload phase.
    # Only call it here when run_recording() is invoked directly (e.g. in tests).
    if not config.WORKSPACE_DIR.exists():
        config.ensure_output_dirs()

    try:
        prev_handler = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGINT, _handle_sigint)
    except (OSError, ValueError) as exc:
        # signal.signal() raises ValueError when called from a non-main thread.
        logger.warning(f"Could not install SIGINT handler (running in a thread?): {exc}")
        prev_handler = signal.SIG_DFL

    # Write the temp video outside workspace/ so compile_workspace can wipe it cleanly
    temp_video_path = os.path.join(tempfile.gettempdir(), "automatiq_full_record.mp4")

    blocklist = _init_blocklist()

    _video_recorder = ActionVideoRecorder(fps=config.FPS, output_path=temp_video_path)
    _browser_agent = BrowserAgent(blocklist=blocklist)

    logger.info("[RULE] STARTING RECORDER")
    logger.info(f"Target URL : {url}")
    logger.info(f"AI Model   : {config.RECORDER_AI_MODEL}")
    logger.info(f"Blocklist  : {blocklist.total_enabled_domains()} domains loaded")
    logger.info("Press Ctrl+C to stop recording")

    session_data = None
    success = False

    try:
        _video_recorder.start()
        session_data = asyncio.run(_browser_agent.run_session(url=url))
    except Exception as exc:
        logger.error(f"Recording session failed: {exc}")
        logger.exception("Exception occurred")
    finally:
        video_start_unix = None
        try:
            video_start_unix = _video_recorder.stop()
        except Exception as exc:
            logger.error(f"Failed to stop video recorder: {exc}")
            logger.exception("Exception occurred")

        # Switch Ctrl+C to default (force-quit) during compilation.
        # Esc is used for the soft "skip AI?" prompt instead.
        try:
            signal.signal(signal.SIGINT, signal.SIG_DFL)
        except (OSError, ValueError):
            pass
        _activate_esc_monitor()
        logger.info("Press Esc to skip AI analysis. Ctrl+C to force-quit.")

        if session_data and video_start_unix:
            try:
                success = compile_workspace(
                    session_data=session_data,
                    full_video_path=temp_video_path,
                    video_start_unix=video_start_unix,
                )
            except Exception as exc:
                logger.error(f"Workspace compilation raised unexpectedly: {exc}")
                logger.exception("Exception occurred")

            # Move the full recording into the compiled workspace
            final_video_path = os.path.join(str(config.WORKSPACE_DIR), "session_dump", "full_record.mp4")
            if success and os.path.exists(temp_video_path):
                try:
                    os.makedirs(os.path.dirname(final_video_path), exist_ok=True)
                    shutil.move(temp_video_path, final_video_path)
                    logger.info(f"Full recording saved to {final_video_path}")
                except OSError as exc:
                    logger.error(f"Failed to move recording to workspace: {exc}")
                    logger.exception("Exception occurred")
        else:
            logger.warning("Session data or video timestamp missing. Skipping compilation.")

        blocked = _browser_agent.stats["blocked_by_blocklist"] if _browser_agent else 0
        if blocked:
            logger.info(f"Blocklist filtered {blocked} ad/tracker request(s)")

        try:
            blocklist.close()
        except Exception as exc:
            logger.warning(f"Failed to close blocklist DB: {exc}")

        _deactivate_esc_monitor()
        try:
            signal.signal(signal.SIGINT, prev_handler)
        except (OSError, ValueError):
            pass

        _browser_agent = None
        _video_recorder = None

    return success
