"""
Agent loop — the core interactive session where the LLM investigates a
recorded browser session and produces a standalone automation/extraction script.
"""

import atexit
import json
import os
import sys
import threading
import time

import instructor
import litellm
import yaml
from instructor.core import InstructorRetryException
from litellm.exceptions import (
    APIConnectionError,
    APIError,
    RateLimitError,
    ServiceUnavailableError,
    Timeout,
)

from . import config
from .console import (
    code_block,
    countdown,
    error,
    info,
    init_file_logger,
    log_exception,
    output_panel,
    print_exception,
    spinner,
    step_info,
    think,
    warn,
)
from .console import prompt as rich_prompt
from .ipython_sandbox import AgentSandbox
from .prompt import PromptFactory
from .schema import (
    AgentStep,
    AssistantResponse,
    Input,
    ModeEnum,
    ModeNotification,
    ToolEnum,
    ToolResponse,
    UserMessage,
)

litellm.suppress_debug_info = True


# ---------------------------------------------------------------------------
# Cancel mechanism — press Esc during any blocking operation (LLM call or
# sandbox execution) to abandon it and return to the >>> prompt.
# ---------------------------------------------------------------------------


class _CancelRequested(Exception):
    """Raised when the user cancels a blocking operation."""


_cancel_flag = threading.Event()
_monitor_active = threading.Event()
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
    """Spawn a platform-appropriate daemon thread that watches for Esc."""

    if sys.platform == "win32":
        import msvcrt

        def _listen():
            while True:
                _monitor_active.wait()
                while _monitor_active.is_set():
                    if msvcrt.kbhit():
                        key = msvcrt.getch()
                        if key == b"\x1b":
                            _cancel_flag.set()
                            _monitor_active.clear()
                            break
                    time.sleep(0.05)

    else:
        import select
        import termios
        import tty

        def _listen():
            fd = sys.stdin.fileno()
            while True:
                _monitor_active.wait()
                old = termios.tcgetattr(fd)
                global _original_term_attrs
                if _original_term_attrs is None:
                    _original_term_attrs = termios.tcgetattr(fd)
                    atexit.register(_restore_terminal)
                try:
                    tty.setcbreak(fd)
                    while _monitor_active.is_set():
                        ready, _, _ = select.select([sys.stdin], [], [], 0.05)
                        if ready:
                            ch = os.read(fd, 1)
                            if ch == b"\x1b":
                                _cancel_flag.set()
                                _monitor_active.clear()
                                break
                finally:
                    termios.tcsetattr(fd, termios.TCSADRAIN, old)
                    termios.tcflush(fd, termios.TCIFLUSH)

    threading.Thread(target=_listen, daemon=True).start()


# Guard: only start the listener if stdin is an actual terminal
if sys.stdin.isatty():
    _start_esc_listener()


def _run_interruptible(fn, *args, **kwargs):
    """Run *fn* in a daemon thread; poll for Esc in the main thread."""
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

    _cancel_flag.clear()
    _monitor_active.set()

    t = threading.Thread(target=_worker, daemon=True)
    t.start()

    while not done.is_set():
        if _cancel_flag.is_set():
            _cancel_flag.clear()
            _monitor_active.clear()
            raise _CancelRequested()
        done.wait(timeout=0.15)

    _monitor_active.clear()

    if error_box[0] is not None:
        raise error_box[0]
    return result_box[0]


def run_agent():
    """Interactive agent loop. Reads from the workspace produced by the recorder."""

    # ensure_output_dirs() and init_file_logger() are called by __main__.py
    # during the preload phase (concurrent with the startup banner).
    # Only call them here when run_agent() is invoked directly (e.g. in tests).
    if not config.LOGS_DIR.exists():
        config.ensure_output_dirs()
        init_file_logger(str(config.LOGS_DIR))

    workspace_dir = config.WORKSPACE_DIR
    session_dump = workspace_dir / "session_dump"
    if not session_dump.exists() or not any(session_dump.iterdir()):
        error(f"No recorded session found at {session_dump}")
        info("Run 'automatiq record <url>' first, or use 'automatiq run <url>' for one-shot.")
        sys.exit(1)

    workspace = str(workspace_dir)
    os.makedirs(workspace, exist_ok=True)

    client = instructor.from_litellm(litellm.completion, mode=instructor.Mode.MD_JSON)

    sandbox = AgentSandbox(
        working_dir=workspace,
        timeout_seconds=config.SANDBOX_TIMEOUT_SECONDS,
        bin_path=str(config.BIN_DIR),
    )

    global_memory = []
    agent = PromptFactory.create_agent("main", shared_memory=global_memory)

    reading_injection = agent.mode_injections.get(ModeEnum.reading, "")
    agent.add_step(
        AgentStep(
            role="user",
            content=Input(
                input=ModeNotification(mode_switched=f"{reading_injection}\n\nSession started. You are in reading mode.")
            ),
        )
    )

    needs_user_input = True
    awaiting_tool_complete = False
    awaiting_mode_switch = False
    scr = ""
    mode_switch_notification = ""
    final_script_bounces = 0
    MAX_FINAL_SCRIPT_BOUNCES = 1
    _first_prompt = True

    # --- Guardrails against repetition and stalling ---
    exec_history: list[tuple[str, str, int]] = []
    consecutive_execs = 0
    cell_counter = 0
    MAX_CONSECUTIVE_EXECS = 12
    prev_thought = ""

    MAX_LLM_RETRIES = 5
    BASE_BACKOFF = 10  # seconds; doubles each retry

    def _extract_message(exc):
        """Pull a readable summary from an exception, stripping litellm wrapper noise."""
        import re

        def _clean(raw):
            s = str(raw)
            # Strip "litellm.FooError: ProviderException FooError - " wrappers
            s = re.sub(r"^litellm\.\w+:\s*", "", s)
            s = re.sub(r"^\w+Exception\s+\w+\s*-\s*", "", s)
            # Try to extract JSON body from the error
            json_match = re.search(r"\{.*\}", s, re.DOTALL)
            if json_match:
                try:
                    body = json.loads(json_match.group())
                    # Gemini nests: {"error": {"message": "..."}}
                    if "error" in body:
                        err = body["error"]
                        if isinstance(err, dict) and "message" in err:
                            return err["message"]
                        return str(err)
                    if "message" in body:
                        return body["message"]
                except json.JSONDecodeError:
                    pass
            return s.split("\n")[0][:300]

        if isinstance(exc, InstructorRetryException):
            for fa in exc.failed_attempts or []:
                if fa.exception:
                    return _clean(fa.exception)
        return _clean(exc)

    def _call_llm(messages):
        """Blocking LLM call — runs inside the interruptible wrapper."""
        kwargs = dict(
            model=config.AGENT_MODEL,
            response_model=AssistantResponse,
            messages=messages,
            max_retries=3,
            temperature=0.3,
            timeout=30,
        )
        if config.API_BASE:
            kwargs["api_base"] = config.API_BASE
        return client.chat.completions.create_with_completion(**kwargs)

    try:
        for step in range(config.MAX_AGENT_STEPS):
            # Check if a background cancel completed — inject system message to agent
            if sandbox.cancel_result is not None:
                cr = sandbox._cancel_result
                sandbox._cancel_result = None
                if cr == "lost":
                    agent.add_step(
                        AgentStep(
                            role="user",
                            content=Input(
                                input=ToolResponse(
                                    tool_response=(
                                        "SYSTEM: Execution cancelled by user — process was force-killed. "
                                        "State lost. Run %restore to recover previous variables."
                                    )
                                )
                            ),
                        )
                    )
                elif cr == "preserved":
                    agent.add_step(
                        AgentStep(
                            role="user",
                            content=Input(
                                input=ToolResponse(
                                    tool_response=(
                                        "SYSTEM: Execution interrupted by user. State preserved — variables are intact."
                                    )
                                )
                            ),
                        )
                    )
                awaiting_tool_complete = False
                awaiting_mode_switch = False
                needs_user_input = True
                continue

            if needs_user_input:
                if _first_prompt:
                    info("Type in q to quit · Esc to cancel processing")
                    _first_prompt = False
                ip = rich_prompt()
                if ip.strip().lower() == "q":
                    info("User requested exit.")
                    break
                agent.add_step(
                    AgentStep(
                        role="user",
                        content=Input(input=UserMessage(message_from_user=ip)),
                    )
                )
                needs_user_input = False
                consecutive_execs = 0

            elif awaiting_tool_complete:
                agent.add_step(
                    AgentStep(
                        role="user",
                        content=Input(input=ToolResponse(tool_response=f"<terminal_output>\n{scr}\n</terminal_output>")),
                    )
                )
                awaiting_tool_complete = False

            elif awaiting_mode_switch:
                agent.add_step(
                    AgentStep(
                        role="user",
                        content=Input(input=ModeNotification(mode_switched=mode_switch_notification)),
                    )
                )
                awaiting_mode_switch = False

            compiled_messages = agent.compile()
            resp = None
            aborted = False  # True → skip this turn, return to prompt

            for attempt in range(1, MAX_LLM_RETRIES + 1):
                try:
                    with spinner("Thinking..."):
                        resp, raw_response = _run_interruptible(_call_llm, compiled_messages)
                    break

                except _CancelRequested:
                    info("Cancelled by Esc. Returning to prompt.")
                    aborted = True
                    break

                except (
                    InstructorRetryException,
                    RateLimitError,
                    ServiceUnavailableError,
                    APIConnectionError,
                    Timeout,
                    APIError,
                ) as exc:
                    msg = _extract_message(exc)
                    wait = BASE_BACKOFF * (2 ** (attempt - 1))
                    warn(f"LLM call failed (attempt {attempt}/{MAX_LLM_RETRIES}): {msg}")
                    log_exception()
                    if attempt < MAX_LLM_RETRIES:
                        warn(f"Retrying in {wait}s ...")
                        cancelled = countdown(wait, cancel_check=_cancel_flag.is_set)
                        if cancelled:
                            _cancel_flag.clear()
                            _monitor_active.clear()
                            info("Cancelled by Esc. Returning to prompt.")
                            aborted = True
                            break
                    else:
                        error("Max retries exceeded. Returning to prompt.")
                        aborted = True
                        break

            if aborted or resp is None:
                needs_user_input = True
                awaiting_tool_complete = False
                awaiting_mode_switch = False
                continue

            step_info(step, raw_response.usage.prompt_tokens)

            # --- Guardrail: reject exact-duplicate thought_process ---
            current_thought = resp.thought_process
            if current_thought == prev_thought and current_thought:
                warn("Exact duplicate thought_process detected.")
                agent.add_step(AgentStep(role="assistant", content=resp))
                agent.add_step(
                    AgentStep(
                        role="user",
                        content=Input(
                            input=ToolResponse(
                                tool_response=(
                                    "SYSTEM: Your reasoning is identical to the previous turn — "
                                    "word for word. You are looping. Either:\n"
                                    "1. Switch to a different mode for a fresh perspective, or\n"
                                    "2. Tell the user what you've found so far and ask for guidance.\n"
                                    "Do NOT repeat the same action."
                                )
                            )
                        ),
                    )
                )
                continue
            prev_thought = current_thought

            agent.add_step(AgentStep(role="assistant", content=resp))
            think(resp.thought_process)

            if resp.tool == ToolEnum.message_to_user:
                # Final script delivery is only allowed in building mode
                if resp.tool_content.does_it_contain_the_final_script and agent.current_mode != ModeEnum.building:
                    warn("Final script submitted outside building mode — bouncing back.")
                    agent.add_step(
                        AgentStep(
                            role="user",
                            content=Input(
                                input=ToolResponse(
                                    tool_response=(
                                        "Hey, it seems you are trying to finish the script while not in building mode. "
                                        "If you are stuck, or the output is coming, switch to reading or testing mode "
                                        "as you wish. We have only one True RULE: Truth and truth alone."
                                    )
                                )
                            ),
                        )
                    )
                    continue

                # Final script in building mode — bounce back for confidence check,
                # then let it through after MAX_FINAL_SCRIPT_BOUNCES attempts.
                if resp.tool_content.does_it_contain_the_final_script:
                    final_script_bounces += 1
                    if final_script_bounces <= MAX_FINAL_SCRIPT_BOUNCES:
                        agent.add_step(
                            AgentStep(
                                role="user",
                                content=Input(
                                    input=ToolResponse(
                                        tool_response=(
                                            "Hi there, looks like you have created the final script. "
                                            "I just came here to verify if you have actually tested it or not. "
                                            "In case the script isn't running, don't worry, just go back to "
                                            "reading mode or testing mode. They will take care of the validity. "
                                            "If test and read modes actually say they can't find any way "
                                            "to make this work, then you can yield before the user that you "
                                            "can't find any solution. If you are truly confident, I want you to show me "
                                            "the output of the script you are trying to submit to user."
                                        )
                                    )
                                ),
                            )
                        )
                        continue
                    # Agent persisted through the confidence checks — deliver to user
                    final_script_bounces = 0

                print(f"\n{resp.tool_content.message_to_user}\n")
                needs_user_input = True

            elif resp.tool == ToolEnum.execute_ipython:
                script_to_run = resp.tool_content.ipython_script
                consecutive_execs += 1
                cell_counter += 1
                current_cell = cell_counter

                # --- Guardrail: block if both script AND output matched twice already ---
                repeat_count = 0
                matched_cell = None
                for prev_script, _prev_output, prev_cell in exec_history:
                    if script_to_run.strip() == prev_script:
                        repeat_count += 1
                        matched_cell = prev_cell

                if repeat_count >= 2 and matched_cell is not None:
                    warn(f"Blocked: same script already ran {repeat_count} times (last: Cell_{matched_cell}).")
                    agent.add_step(
                        AgentStep(
                            role="user",
                            content=Input(
                                input=ToolResponse(
                                    tool_response=(
                                        f"SYSTEM: This exact script has already been executed {repeat_count} times "
                                        f"with the same output. It was NOT executed again. "
                                        f"Use %view_output Cell_{matched_cell} to review the previous output. "
                                        f"Try a fundamentally different approach."
                                    )
                                )
                            ),
                        )
                    )
                    continue

                code_block(script_to_run)

                try:
                    with spinner("Running..."):
                        scr = _run_interruptible(sandbox.execute, script_to_run)
                except _CancelRequested:
                    sandbox.cancel()
                    info("Cancelled by Esc. Returning to prompt.")
                    needs_user_input = True
                    continue

                # --- Guardrail: if output is identical to a previous cell, just reference it ---
                output_match_cell = None
                for _prev_script, prev_output, prev_cell in exec_history:
                    if prev_output and scr == prev_output and len(scr) > 100:
                        output_match_cell = prev_cell
                        break

                if output_match_cell is not None:
                    scr = (
                        f"The output is the same as Cell_{output_match_cell}. "
                        f"Use %view_output Cell_{output_match_cell} if you need to review it."
                    )

                exec_history.append((script_to_run.strip(), scr, current_cell))

                output_panel(scr)
                awaiting_tool_complete = True

                # --- Guardrail: nudge to switch modes if stuck ---
                if consecutive_execs >= MAX_CONSECUTIVE_EXECS:
                    agent.add_step(
                        AgentStep(
                            role="user",
                            content=Input(
                                input=ToolResponse(tool_response=f"<terminal_output>\n{scr}\n</terminal_output>")
                            ),
                        )
                    )
                    agent.add_step(
                        AgentStep(
                            role="user",
                            content=Input(
                                input=ToolResponse(
                                    tool_response=(
                                        f"SYSTEM: You have been running code for {consecutive_execs} consecutive turns "
                                        f"without switching modes or talking to the user. "
                                        f"Take a step back and evaluate your progress:\n"
                                        f"- Are you making forward progress or going in circles?\n"
                                        f"- Would switching to a different mode help?\n"
                                        f"- Is there something you should ask the user about?\n"
                                        f"If you are stuck, switch modes. "
                                        f"If you have findings, share them with the user."
                                    )
                                )
                            ),
                        )
                    )
                    awaiting_tool_complete = False
                    continue

            elif resp.tool == ToolEnum.switch_mode:
                target_mode = resp.tool_content.target_mode
                context_memo = resp.tool_content.context
                consecutive_execs = 0

                info(f"Switching to {target_mode.value} mode")
                agent.switch_mode(target_mode)

                # The mode notification is injected as the next user-role step.
                # It contains the mode injection text + the agent's own research memo.
                mode_injection = agent.mode_injections.get(target_mode, "")
                mode_switch_notification = (
                    f"{mode_injection}\n\n--- Research memo from previous mode ---\n{context_memo}"
                )
                awaiting_mode_switch = True

    except KeyboardInterrupt:
        info("Interrupted by user (Ctrl+C). Saving session ...")
        sandbox.cancel()

    except Exception as exc:
        error(f"Unexpected error: {exc}")
        print_exception()
        sandbox.cancel()

    finally:
        _monitor_active.clear()
        try:
            _export_session_logs(global_memory, agent)
        except Exception as exc:
            error(f"Failed to save session logs: {exc}")
            print_exception()
        sandbox.close()


def _export_session_logs(global_memory, agent):
    """Write both uncompressed and compressed YAML session logs to output/history/."""

    class _SessionDumper(yaml.Dumper):
        pass

    def multiline_presenter(dumper, data):
        if "\n" in data:
            return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
        return dumper.represent_scalar("tag:yaml.org,2002:str", data)

    _SessionDumper.add_representer(str, multiline_presenter)

    history_dir = str(config.HISTORY_DIR)

    uncompressed_path = os.path.join(history_dir, "messages_uncompressed.yaml")
    uncompressed_data = [s.model_dump(exclude_none=True) for s in global_memory]
    with open(uncompressed_path, "w", encoding="utf-8") as f:
        yaml.dump(uncompressed_data, f, Dumper=_SessionDumper, sort_keys=False, allow_unicode=True)
    info(f"Saved full session history to {uncompressed_path}")

    compiled_messages = agent.compile()
    compressed_data = []
    for msg in compiled_messages:
        if "content" in msg and isinstance(msg["content"], str):
            try:
                compressed_data.append({"role": msg["role"], "content": json.loads(msg["content"])})
            except json.JSONDecodeError:
                compressed_data.append(msg)
        else:
            compressed_data.append(msg)

    compressed_path = os.path.join(history_dir, "messages_compressed.yaml")
    with open(compressed_path, "w", encoding="utf-8") as f:
        yaml.dump(compressed_data, f, Dumper=_SessionDumper, sort_keys=False, allow_unicode=True)
    info(f"Saved compressed session history to {compressed_path}")
