import logging
import queue
import threading

from ..core.cancel_standard import CancelToken
from ..core.events import EventType
from ..core.main import run_agent
from .console import (
    code_block,
    countdown,
    error,
    info,
    output_panel,
    prompt,
    spinner,
    step_info,
    think,
    warn,
)

logger = logging.getLogger(__name__)


def run_agent_cli(cancel_token: CancelToken = None):
    if cancel_token is None:
        cancel_token = CancelToken()

    input_queue = queue.Queue()
    output_queue = queue.Queue()

    def backend_worker():
        try:
            run_agent(input_queue=input_queue, output_queue=output_queue, cancel_token=cancel_token)
        except Exception:
            logger.exception("Agent loop crashed")
        finally:
            output_queue.put({"type": EventType.AGENT_DONE})

    t = threading.Thread(target=backend_worker, daemon=True)
    t.start()

    _first_prompt = True
    active_spinner = None

    try:
        while True:
            event = output_queue.get()

            # Since event is an AgentEvent object
            if isinstance(event, dict):
                ev_type = event.get("type")
                payload = event.get("payload", {})
            else:
                ev_type = event.type
                payload = event.payload

            if ev_type == EventType.AGENT_DONE:
                break

            elif ev_type == EventType.STEP_START:
                step_info(payload["step"], payload["prompt_tokens"])

            elif ev_type == EventType.THOUGHT:
                think(payload["text"])

            elif ev_type == EventType.TOOL_MESSAGE:
                print(payload["text"])

            elif ev_type == EventType.MODE_SWITCH:
                info(f"Switching to {payload['mode']} mode")

            elif ev_type == EventType.CODE_EXEC:
                code_block(payload["script"])

            elif ev_type == EventType.CODE_OUTPUT:
                output_panel(payload["output"])

            elif ev_type == EventType.LLM_REQUEST_START:
                active_spinner = spinner("Thinking...")
                active_spinner.__enter__()

            elif ev_type == EventType.LLM_REQUEST_END:
                if active_spinner:
                    active_spinner.__exit__(None, None, None)
                    active_spinner = None

            elif ev_type == EventType.CODE_EXEC_START:
                active_spinner = spinner("Running...")
                active_spinner.__enter__()

            elif ev_type == EventType.CODE_EXEC_END:
                if active_spinner:
                    active_spinner.__exit__(None, None, None)
                    active_spinner = None

            elif ev_type == EventType.WAIT_START:
                cancelled = countdown(
                    payload["seconds"], message=payload.get("reason", "Retrying"), cancel_check=cancel_token.is_cancelled
                )
                if cancelled:
                    cancel_token.reset()

            elif ev_type == EventType.PROMPT_REQUEST:
                if _first_prompt:
                    info("Type in q to quit | Esc to cancel processing")
                    _first_prompt = False

                try:
                    ip = prompt()
                except (KeyboardInterrupt, EOFError):
                    ip = "q"
                input_queue.put(ip)
                if ip.strip().lower() == "q":
                    break

            elif ev_type == EventType.LOG_INFO:
                info(payload["text"])

            elif ev_type == EventType.LOG_WARN:
                warn(payload["text"])

            elif ev_type == EventType.LOG_ERROR:
                error(payload["text"])

    except KeyboardInterrupt:
        info("Interrupted by user (Ctrl+C). Exiting...")
        cancel_token.cancel()
    finally:
        if active_spinner:
            active_spinner.__exit__(None, None, None)
