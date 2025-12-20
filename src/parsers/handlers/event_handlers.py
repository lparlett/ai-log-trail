"""Helper functions for processing grouped Codex session events.

Purpose: Encapsulate event handling helpers for session ingest.
Author: Codex with Lauren Parlett
Date: 2025-10-30
"""

# pylint: disable=duplicate-code

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict


EVENT_HANDLER_EXPORTS: tuple[str, ...] = (
    "EventContext",
    "EventHandlerDeps",
    "FunctionCallTracker",
    "InsertEventFn",
    "InsertTokenFn",
    "InsertTurnContextFn",
    "InsertAgentReasoningFn",
    "InsertFunctionPlanFn",
    "InsertFunctionCallFn",
    "UpdateFunctionCallOutputFn",
    "handle_event_msg",
    "handle_turn_context_event",
    "handle_response_item_event",
)

from .db_utils import (
    AgentReasoningInsert,
    EventInsert,
    FunctionCallInsert,
    FunctionCallOutputUpdate,
)

InsertEventFn = Callable[[EventInsert], None]
InsertTokenFn = Callable[[EventInsert], None]
InsertTurnContextFn = Callable[[EventInsert], None]
InsertAgentReasoningFn = Callable[[AgentReasoningInsert], None]
InsertFunctionPlanFn = Callable[[EventInsert], None]
InsertFunctionCallFn = Callable[[FunctionCallInsert], int]
UpdateFunctionCallOutputFn = Callable[[FunctionCallOutputUpdate], None]


@dataclass
class EventContext:
    """Container for event-specific data to reduce argument counts."""

    conn: Any
    file_id: int
    prompt_id: int
    timestamp: str | None
    payload: dict[str, Any]
    raw_event: dict[str, Any]
    counts: dict[str, int]


@dataclass
class EventHandlerDeps:
    """Callable dependencies used by the session event handlers."""

    insert_event: InsertEventFn
    insert_token: InsertTokenFn
    insert_turn_context: InsertTurnContextFn
    insert_agent_reasoning: InsertAgentReasoningFn
    insert_function_plan: InsertFunctionPlanFn
    insert_function_call: InsertFunctionCallFn
    update_function_call_output: UpdateFunctionCallOutputFn


@dataclass
class FunctionCallTracker:
    """Track pending function calls so outputs can be matched accurately."""

    by_id: Dict[str, int] = field(default_factory=dict)
    queue: list[int] = field(default_factory=list)

    def register(self, call_id: str | None, row_id: int) -> None:
        """Register call row by id or queue for later resolution."""

        if call_id:
            self.by_id[call_id] = row_id
        else:
            self.queue.append(row_id)

    def resolve(self, call_id: str | None) -> int | None:
        """Resolve row id for a given call id or fall back to queue."""

        if call_id and call_id in self.by_id:
            return self.by_id.pop(call_id)
        if self.queue:
            return self.queue.pop(0)
        return None


def handle_event_msg(
    deps: EventHandlerDeps,
    event_context: EventContext,
) -> None:
    """Handle event_msg payload variants for a prompt."""

    subtype = event_context.payload.get("type")
    insert_context = EventInsert(
        conn=event_context.conn,
        file_id=event_context.file_id,
        prompt_id=event_context.prompt_id,
        timestamp=event_context.timestamp,
        payload=event_context.payload,
        raw=event_context.raw_event,
    )

    # Insert the base event record first
    deps.insert_event(insert_context)
    event_context.counts["events"] = event_context.counts.get("events", 0) + 1

    if subtype == "token_count":
        deps.insert_token(insert_context)
        event_context.counts["token_messages"] += 1
        return

    if subtype == "agent_reasoning":
        _record_agent_reasoning(
            deps,
            event_context,
            insert_context,
            "event_msg",
        )
        return

    if subtype == "turn_aborted":
        _record_agent_reasoning(
            deps,
            event_context,
            insert_context,
            "turn_aborted",
        )
        return

    if subtype == "agent_message":
        _record_agent_reasoning(
            deps,
            event_context,
            insert_context,
            "agent_message",
        )


def handle_turn_context_event(
    deps: EventHandlerDeps,
    event_context: EventContext,
) -> None:
    """Handle turn_context events and update counts."""

    insert_context = EventInsert(
        conn=event_context.conn,
        file_id=event_context.file_id,
        prompt_id=event_context.prompt_id,
        timestamp=event_context.timestamp,
        payload=event_context.payload,
        raw=event_context.raw_event,
    )
    deps.insert_turn_context(insert_context)
    event_context.counts["turn_context_messages"] += 1


def handle_response_item_event(
    deps: EventHandlerDeps,
    event_context: EventContext,
    tracker: FunctionCallTracker,
) -> None:
    """Handle response_item payload variants."""

    subtype = event_context.payload.get("type")
    if subtype == "reasoning":
        return

    if subtype == "function_call":
        insert_context = EventInsert(
            conn=event_context.conn,
            file_id=event_context.file_id,
            prompt_id=event_context.prompt_id,
            timestamp=event_context.timestamp,
            payload=event_context.payload,
            raw=event_context.raw_event,
        )
        name = event_context.payload.get("name")
        if name == "update_plan":
            deps.insert_function_plan(insert_context)
            event_context.counts["function_plan_messages"] += 1
            return
        _register_function_call(
            deps,
            event_context,
            insert_context,
            tracker,
        )
        return

    if subtype == "function_call_output":
        call_id_value = event_context.payload.get("call_id")
        call_id = (
            call_id_value if isinstance(call_id_value, str) and call_id_value else None
        )
        row_id = tracker.resolve(call_id)
        if row_id is None:
            insert_context = EventInsert(
                conn=event_context.conn,
                file_id=event_context.file_id,
                prompt_id=event_context.prompt_id,
                timestamp=None,
                payload={},
                raw={},
            )
            row_id = _register_function_call(
                deps,
                event_context,
                insert_context,
                tracker,
            )
        deps.update_function_call_output(
            FunctionCallOutputUpdate(
                conn=event_context.conn,
                row_id=row_id,
                timestamp=event_context.timestamp,
                payload=event_context.payload,
                raw=event_context.raw_event,
            )
        )


def _record_agent_reasoning(
    deps: EventHandlerDeps,
    event_context: EventContext,
    insert_context: EventInsert,
    source: str,
) -> None:
    """Persist agent reasoning and update counters."""

    deps.insert_agent_reasoning(
        AgentReasoningInsert(
            conn=insert_context.conn,
            file_id=insert_context.file_id,
            prompt_id=insert_context.prompt_id,
            timestamp=insert_context.timestamp,
            payload=insert_context.payload,
            raw=insert_context.raw,
            source=source,
        )
    )
    event_context.counts["agent_reasoning_messages"] += 1


def _register_function_call(
    deps: EventHandlerDeps,
    event_context: EventContext,
    insert_context: EventInsert,
    tracker: FunctionCallTracker,
) -> int:
    """Insert a function call row and track it for later outputs."""

    row_id = deps.insert_function_call(
        FunctionCallInsert(
            conn=insert_context.conn,
            file_id=insert_context.file_id,
            prompt_id=insert_context.prompt_id,
            timestamp=insert_context.timestamp,
            payload=insert_context.payload,
            raw=insert_context.raw,
        )
    )
    call_id_value = insert_context.payload.get("call_id")
    call_id = (
        call_id_value if isinstance(call_id_value, str) and call_id_value else None
    )
    tracker.register(call_id, row_id)
    event_context.counts["function_calls"] += 1
    return row_id
