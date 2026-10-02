from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(frozen=True)
class ActionResult:
    success: bool
    message: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ActionSpec:
    action_id: str
    description: str
    argument_schema: dict[str, Any]
    handler: Callable[..., ActionResult]
    requires_confirmation: bool = False
    examples: tuple[str, ...] = ()
