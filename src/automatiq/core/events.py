from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class EventType(Enum):
    STEP_START = "step_start"  # payload: {"step": int, "prompt_tokens": int}
    THOUGHT = "thought"  # payload: {"text": str}
    TOOL_MESSAGE = "tool_message"  # payload: {"text": str}
    MODE_SWITCH = "mode_switch"  # payload: {"mode": str}
    CODE_EXEC = "code_exec"  # payload: {"script": str}
    CODE_OUTPUT = "code_output"  # payload: {"output": str}
    AGENT_DONE = "agent_done"  # payload: {}

    # New events for UI decoupling
    LLM_REQUEST_START = "llm_request_start"  # payload: {}
    LLM_REQUEST_END = "llm_request_end"  # payload: {}
    CODE_EXEC_START = "code_exec_start"  # payload: {}
    CODE_EXEC_END = "code_exec_end"  # payload: {}
    WAIT_START = "wait_start"  # payload: {"seconds": int, "reason": str}
    PROMPT_REQUEST = "prompt_request"  # payload: {}
    LOG_INFO = "log_info"  # payload: {"text": str}
    LOG_WARN = "log_warn"  # payload: {"text": str}
    LOG_ERROR = "log_error"  # payload: {"text": str}


@dataclass
class AgentEvent:
    type: EventType
    payload: dict[str, Any] = field(default_factory=dict)
