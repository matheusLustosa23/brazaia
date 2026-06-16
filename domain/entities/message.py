from dataclasses import dataclass, field

@dataclass(slots=True)
class ToolCall:
    id: str
    name: str
    arguments: dict        


@dataclass(slots=True)
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass(slots=True)
class Completion:
    content: str | None                
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str | None = None   
    usage: Usage = field(default_factory=Usage)