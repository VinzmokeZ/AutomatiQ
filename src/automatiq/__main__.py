"""
CLI entry point for AutomatiQ.

Usage:
    python -m automatiq record <url>   # Record a browser session
    python -m automatiq agent          # Run the agent on an existing workspace
    python -m automatiq run <url>      # Record, then launch the agent
"""

import argparse
import multiprocessing
import sys
import threading

from .console import error, info, rule

# ---------------------------------------------------------------------------
# Background preload — runs concurrently with the startup banner so that
# heavy modules are already imported and directories exist by the time the
# animation finishes.
#
# We peek at sys.argv before argparse runs so we can preload only what the
# chosen sub-command actually needs:
#   agent          → litellm, instructor, IPython, yaml
#   record / run   → zendriver, mss, numpy, imageio_ffmpeg  (+ agent deps for run)
# ---------------------------------------------------------------------------

_preload_error = None  # captured if preload raises unexpectedly


def _peek_command() -> str:
    """Return the first positional arg that looks like a sub-command, or ''."""
    for arg in sys.argv[1:]:
        if not arg.startswith("-"):
            return arg
    return ""


def _peek_model() -> str | None:
    """Return the value of --model from sys.argv before argparse runs, or None."""
    args = sys.argv[1:]
    for i, arg in enumerate(args):
        if arg == "--model" and i + 1 < len(args):
            return args[i + 1]
        if arg.startswith("--model="):
            return arg.split("=", 1)[1]
    return None


def _peek_base_url() -> str | None:
    """Return the value of --base-url from sys.argv before argparse runs, or None."""
    args = sys.argv[1:]
    for i, arg in enumerate(args):
        if arg == "--base-url" and i + 1 < len(args):
            return args[i + 1]
        if arg.startswith("--base-url="):
            return arg.split("=", 1)[1]
    return None


def _preload():
    global _preload_error
    try:
        from . import config

        config.ensure_output_dirs()

        from .console import init_file_logger

        init_file_logger(str(config.LOGS_DIR))

        cmd = _peek_command()

        if cmd in ("agent", "run", ""):
            # Agent deps — always needed for 'agent' and 'run'; also the default.
            import instructor  # noqa: F401
            import IPython  # noqa: F401
            import litellm  # noqa: F401
            import yaml  # noqa: F401

            # Suppress litellm's "Give Feedback / Provider List" banners
            litellm.suppress_debug_info = True

        if cmd in ("record", "run"):
            # Recorder deps — only needed when a browser session will be captured.
            import imageio_ffmpeg  # noqa: F401
            import mss  # noqa: F401
            import numpy  # noqa: F401
            import zendriver  # noqa: F401

            # litellm is used by the recorder's AI analyzer too
            if cmd == "record":
                import litellm  # noqa: F401

                litellm.suppress_debug_info = True

    except Exception as exc:
        _preload_error = exc


def _apply_config_overrides(args):
    """Monkey-patch config values from CLI flags before any subcommand logic runs."""
    from . import config

    if getattr(args, "model", None):
        config.AGENT_MODEL = args.model
    if getattr(args, "recorder_model", None):
        config.RECORDER_AI_MODEL = args.recorder_model
    if getattr(args, "output_dir", None):
        from pathlib import Path

        config.OUTPUT_DIR = Path(args.output_dir)
        config.WORKSPACE_DIR = config.OUTPUT_DIR / "workspace"
        config.BLOCKLIST_DIR = config.OUTPUT_DIR / "blocklist"
        config.BLOCKLIST_DB = config.OUTPUT_DIR / "blocklist.db"
    if getattr(args, "max_steps", None) is not None:
        config.MAX_AGENT_STEPS = args.max_steps
    if getattr(args, "sandbox_timeout", None) is not None:
        config.SANDBOX_TIMEOUT_SECONDS = args.sandbox_timeout
    if getattr(args, "base_url", None):
        config.API_BASE = args.base_url


def cmd_record(args):
    _apply_config_overrides(args)
    from . import config
    from .key_checker import check_api_keys

    check_api_keys(config.AGENT_MODEL, config.RECORDER_AI_MODEL)
    from .recorder import run_recording

    success = run_recording(url=args.url)
    if not success:
        error("Recording failed or produced no output.")
        sys.exit(1)
    info("Recording complete. Run 'automatiq agent' to start the agent.")


def cmd_agent(args):
    _apply_config_overrides(args)
    from . import config
    from .key_checker import check_api_keys

    check_api_keys(config.AGENT_MODEL)
    from .bin_manager import ensure_binaries

    ensure_binaries()
    from .main import run_agent

    run_agent()


def cmd_run(args):
    _apply_config_overrides(args)
    from . import config
    from .key_checker import check_api_keys

    check_api_keys(config.AGENT_MODEL, config.RECORDER_AI_MODEL)
    from .bin_manager import ensure_binaries
    from .main import run_agent
    from .recorder import run_recording

    ensure_binaries()

    success = run_recording(url=args.url)
    if not success:
        error("Recording failed. Aborting agent launch.")
        sys.exit(1)

    rule("Recording complete. Launching agent...", style="bold green")
    run_agent()


def main():
    # Start preloading in the background before the banner begins.
    preload_thread = threading.Thread(target=_preload, daemon=True)
    preload_thread.start()

    from . import config
    from .automatiq_banner import show_startup

    banner_model = _peek_model() or config.AGENT_MODEL
    banner_base_url = _peek_base_url()
    if banner_base_url:
        config.API_BASE = banner_base_url
    if config.BANNER_ENABLED:
        show_startup(
            version=config.VERSION,
            model=banner_model,
            recorder_model=config.RECORDER_AI_MODEL,
            speed=config.BANNER_SPEED,
        )

    # Wait for preload to finish before parsing args (usually already done).
    preload_thread.join()

    if _preload_error is not None:
        error(f"Startup init failed: {_preload_error}")
        sys.exit(1)

    parser = argparse.ArgumentParser(
        prog="automatiq",
        description=(
            "AutomatiQ — turn any browser session into a ready-to-run scraping script.\n"
            "\n"
            "Typical workflows:\n"
            "  1. One-shot  : automatiq run https://example.com\n"
            "                 Records your session and immediately hands it to the agent.\n"
            "\n"
            "  2. Step-by-step:\n"
            "     a) automatiq record https://example.com   # capture the session\n"
            "     b) automatiq agent                        # analyse and generate the script\n"
            "\n"
            "Output is written to ./output/ by default (override with --output-dir).\n"
            "Models and timeouts can be overridden per-run with the flags below."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command")

    # ── Shared flag definitions ───────────────────────────────────────────────
    def _add_common_flags(p, include_recorder_model=False):
        g = p.add_argument_group("model options")
        g.add_argument(
            "--model",
            metavar="MODEL",
            help=(
                "LiteLLM model string for the investigator agent.\n"
                f"Default: {config.AGENT_MODEL}\n"
                "Examples: openai/gpt-4o  anthropic/claude-3-5-sonnet  gemini/gemini-2.0-flash"
            ),
        )
        g.add_argument(
            "--base-url",
            metavar="URL",
            help=(
                "Custom OpenAI-compatible API endpoint (e.g. Ollama, LM Studio, vLLM).\n"
                "When set, all LLM requests are routed to this URL.\n"
                "Use with --model openai/<name> (the openai/ prefix is required by litellm).\n"
                "Example: --base-url http://localhost:11434/v1 --model openai/llama3.2"
            ),
        )
        if include_recorder_model:
            g.add_argument(
                "--recorder-model",
                metavar="MODEL",
                help=(
                    "LiteLLM model string for video-clip analysis during recording.\n"
                    f"Default: {config.RECORDER_AI_MODEL}\n"
                    "Use a cheaper/faster vision model here to reduce recording cost."
                ),
            )

        g2 = p.add_argument_group("execution limits")
        g2.add_argument(
            "--max-steps",
            type=int,
            metavar="N",
            help=(
                "Maximum number of agent loop iterations before giving up.\n"
                f"Default: {config.MAX_AGENT_STEPS}. "
                "Raise this for complex sites; lower it to cap API spend."
            ),
        )
        g2.add_argument(
            "--sandbox-timeout",
            type=int,
            metavar="SECONDS",
            help=(
                "How long (seconds) a single IPython cell is allowed to run.\n"
                f"Default: {config.SANDBOX_TIMEOUT_SECONDS}. "
                "Increase for slow sites or heavy scraping jobs."
            ),
        )

        g3 = p.add_argument_group("output")
        g3.add_argument(
            "--output-dir",
            metavar="PATH",
            help=(
                "Root directory for all generated output (workspace, logs, recordings).\n"
                f"Default: {config.OUTPUT_DIR}\n"
                "All sub-paths (workspace/, logs/, blocklist/) are derived from this."
            ),
        )

    p_record = subparsers.add_parser(
        "record",
        help="Capture a browser session (screen + network + actions).",
        description=(
            "Launch a Chrome window and record everything: screen video, network\n"
            "requests, and user interactions. Press Ctrl+C when you are done browsing\n"
            "to stop the recording and compile the workspace.\n"
            "\n"
            "What gets saved to --output-dir/workspace/session_dump/:\n"
            "  full_record.mp4     — full screen recording of the session\n"
            "  requests.json       — all network requests/responses captured via CDP\n"
            "  actions.json        — timestamped user interactions (clicks, typing, navigation)\n"
            "  clips/              — per-action video segments analysed by the vision model\n"
            "  action_analysis/    — structured AI summaries of each clip\n"
            "\n"
            "Run 'automatiq agent' afterwards to generate the scraping script."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_record.add_argument(
        "url",
        nargs="?",
        default="about:blank",
        help="URL to open when the browser starts. Default: about:blank",
    )
    _add_common_flags(p_record, include_recorder_model=True)
    p_record.set_defaults(func=cmd_record)

    p_agent = subparsers.add_parser(
        "agent",
        help="Analyse a recorded workspace and produce a scraping script.",
        description=(
            "Read an existing workspace (produced by 'record') and run the\n"
            "investigator agent. The agent inspects the captured requests, video\n"
            "analysis, and actions, then iteratively writes and tests Python code\n"
            "in a sandboxed IPython environment until it produces a working scraper.\n"
            "\n"
            "The final script is printed to the terminal and saved to:\n"
            "  --output-dir/workspace/final_script.py\n"
            "\n"
            "Use this command when you want to re-run the agent on a session you\n"
            "already recorded, or to try a different model without re-recording."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_common_flags(p_agent)
    p_agent.set_defaults(func=cmd_agent)

    p_run = subparsers.add_parser(
        "run",
        help="Record a session then immediately launch the agent (one-shot).",
        description=(
            "Convenience command that chains 'record' and 'agent' in sequence.\n"
            "Use this for the typical single-pass workflow:\n"
            "\n"
            "  automatiq run https://example.com/products\n"
            "\n"
            "The browser opens, you navigate the target site, press Ctrl+C to stop,\n"
            "and the agent immediately starts analysing and generating the script.\n"
            "\n"
            "If the recording step fails the agent will not be launched."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_run.add_argument(
        "url",
        nargs="?",
        default="about:blank",
        help="URL to open when the browser starts. Default: about:blank",
    )
    _add_common_flags(p_run, include_recorder_model=True)
    p_run.set_defaults(func=cmd_run)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(0)
    args.func(args)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
