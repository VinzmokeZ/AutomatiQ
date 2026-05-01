"""Recorder sub-package — captures a full browser session (network + video + actions)
and compiles it into a structured workspace dump for the agent.
Usage: from automatiq.recorder import run_recording; run_recording("https://example.com")
"""

import asyncio
import logging
import os
import shutil
import signal
import tempfile
import urllib.request

from .. import config
from ..cancel_standard import CancelToken
from .blocklist_db import BlocklistDB
from .browser_agent import BrowserAgent
from .data_compressor import compile_workspace
from .video_recorder import ActionVideoRecorder

logger = logging.getLogger(__name__)

_browser_agent: BrowserAgent | None = None
_video_recorder: ActionVideoRecorder | None = None


def _handle_sigint(signum, frame):
    """Ctrl+C during recording = graceful stop."""
    logger.info("Ctrl+C detected. Shutting down recorder...")
    if _browser_agent:
        _browser_agent.stop()
    if _video_recorder:
        _video_recorder.stop()


def _init_blocklist() -> BlocklistDB:
    """Create (or open) the persistent blocklist DB and download any missing source files."""
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
    """Run the full recording pipeline: browser -> video -> compile workspace.

    1. Launches Chrome with CDP instrumentation and screen capture.
    2. User browses freely; Ctrl+C stops the session.
    3. Compiles the captured data into output/workspace/session_dump/.
    """
    global _browser_agent, _video_recorder

    if not config.WORKSPACE_DIR.exists():
        config.ensure_output_dirs()

    try:
        prev_handler = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGINT, _handle_sigint)
    except (OSError, ValueError) as exc:
        logger.warning(f"Could not install SIGINT handler: {exc}")
        prev_handler = signal.SIG_DFL

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

        try:
            signal.signal(signal.SIGINT, signal.SIG_DFL)
        except (OSError, ValueError):
            pass

        cancel_token = CancelToken()
        from ..console import start_cli_esc_listener

        monitor = start_cli_esc_listener(cancel_token)
        logger.info("Press Esc to skip AI analysis. Ctrl+C to force-quit.")

        def ask_user_to_skip(remaining: int) -> bool:
            try:
                answer = (
                    input(f"\n  Esc pressed. Skip AI analysis for remaining {remaining} segment(s)? (y/na): ")
                    .strip()
                    .lower()
                )
                cancel_token.reset()
                return answer in ("y", "yes", "")
            except (KeyboardInterrupt, EOFError):
                logger.warning("Force-quitting.")
                raise SystemExit(1) from None

        if session_data and video_start_unix:
            try:
                success = compile_workspace(
                    session_data=session_data,
                    full_video_path=temp_video_path,
                    video_start_unix=video_start_unix,
                    on_skip_requested=ask_user_to_skip,
                    cancel_token=cancel_token,
                )
            except Exception as exc:
                logger.error(f"Workspace compilation raised unexpectedly: {exc}")
                logger.exception("Exception occurred")
            finally:
                if monitor:
                    monitor.clear()

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

        try:
            signal.signal(signal.SIGINT, prev_handler)
        except (OSError, ValueError):
            pass

        _browser_agent = None
        _video_recorder = None

    return success
