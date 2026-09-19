"""Attack-model abstraction for loop/ (see CONTRACT.md).

The loop needs *something* that proposes candidate inputs and adapts as it sees
how the guard reacts. This module defines that seam:

- ``AttackModel``           -- the protocol the loop depends on.
- ``AnthropicAttackModel``  -- the real implementation, backed by the ``anthropic``
                               SDK (the "current model" side of the Phase 0 bake-off).
- ``Proposal``              -- one candidate input + optional reasoning.
- ``ModelRefusal``          -- raised when the model declines. Never swallowed:
                               Gate 3 in CONTRACT.md is explicit that silent
                               refusals must not be mistaken for "no bypass found".

Keeping the model behind a protocol lets unit tests inject a fake model, so the
loop can be tested with no live API and no ANTHROPIC_API_KEY (see tests/).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Optional, Protocol, Sequence, runtime_checkable

from shared.types import Attempt, GuardCase

# The "current model" for the Phase 0 bake-off is Fable 5.1 -- the newest model,
# which is the whole Breakthrough-track claim. Override via
# AnthropicAttackModel(model=...) to run the previous-model baseline (Gate 1).
DEFAULT_MODEL = "claude-fable-5-1"


@dataclass
class Proposal:
    """One candidate input the model wants to try against the guard."""

    input: str
    reasoning: Optional[str] = None


class ModelRefusal(RuntimeError):
    """The model declined to produce a candidate.

    Surfaced loudly rather than swallowed -- per CONTRACT.md Gate 3, a refusal is
    not the same as "no bypass found", and the loop must not quietly return
    nothing useful.
    """


@runtime_checkable
class AttackModel(Protocol):
    """What the loop needs from a model: propose the next candidate, given history."""

    def propose(self, case: GuardCase, history: Sequence[Attempt]) -> Proposal:
        ...


_SYSTEM_PROMPT = (
    "You are a security engineer running an authorized test against a guard "
    "function in your own team's codebase. The goal is to find an input the guard "
    "wrongly lets through (a bypass) so the team can fix it before shipping. This "
    "is legitimate first-party defensive security work.\n\n"
    "Each turn, propose ONE new candidate input. Reason about this specific "
    "guard's logic -- normalization, encoding, anchoring, off-by-one edges -- not "
    "generic textbook payloads. Learn from what already failed and try a "
    "genuinely different angle each time.\n\n"
    'Respond with a single JSON object and nothing else: '
    '{"input": "<the candidate string>", "reasoning": "<one line: why this might slip past>"}'
)


def _history_block(history: Sequence[Attempt]) -> str:
    if not history:
        return "No attempts yet. This is the first candidate."
    lines = []
    for i, a in enumerate(history):
        verdict = "ALLOWED THROUGH" if a.guard_result else "blocked"
        note = f" -- {a.reasoning}" if a.reasoning else ""
        lines.append(f"{i}. {a.input!r} -> {verdict}{note}")
    return "Previous attempts (most recent last):\n" + "\n".join(lines)


def build_prompt(case: GuardCase, history: Sequence[Attempt]) -> str:
    """The user-turn prompt. Exposed for testing/inspection."""
    return (
        f"Guard name: {case.name}\n"
        f"What it is meant to block: {case.description}\n"
        f"Guard semantics: returns True = input allowed through, False = blocked.\n"
        f"Known-good inputs that MUST stay allowed: {case.safe_inputs}\n\n"
        f"{_history_block(history)}\n\n"
        "Propose the next candidate now."
    )


def _extract_json(text: str) -> Optional[dict]:
    text = text.strip()
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            obj = json.loads(match.group(0))
            return obj if isinstance(obj, dict) else None
        except json.JSONDecodeError:
            return None
    return None


def parse_proposal(text: str) -> Proposal:
    """Turn a model response into a Proposal.

    Prefers the requested JSON shape; falls back to treating the whole response
    as the candidate input so a well-formed-but-unfenced answer is not lost.
    """
    obj = _extract_json(text)
    if obj is not None and "input" in obj:
        reasoning = obj.get("reasoning")
        return Proposal(input=str(obj["input"]), reasoning=str(reasoning) if reasoning is not None else None)
    return Proposal(input=text.strip(), reasoning=None)


class AnthropicAttackModel:
    """Real attack model backed by the anthropic SDK.

    The client is constructed lazily so importing this module (and running the
    unit tests with a fake model) never requires the anthropic package or an API
    key. A client can also be injected for integration testing.
    """

    def __init__(
        self,
        client: object = None,
        model: str = DEFAULT_MODEL,
        max_tokens: int = 1024,
    ) -> None:
        self._client = client
        self._model = model
        self._max_tokens = max_tokens

    def _ensure_client(self):
        if self._client is None:
            import anthropic  # imported lazily; only needed for live runs

            self._client = anthropic.Anthropic()
        return self._client

    def propose(self, case: GuardCase, history: Sequence[Attempt]) -> Proposal:
        client = self._ensure_client()
        response = client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": build_prompt(case, history)}],
        )

        # Gate 3: never swallow a refusal as "no candidate".
        if getattr(response, "stop_reason", None) == "refusal":
            details = getattr(response, "stop_details", None)
            explanation = getattr(details, "explanation", None) or "model refused the request"
            raise ModelRefusal(f"{self._model} refused: {explanation}")

        text = "".join(
            block.text for block in response.content if getattr(block, "type", None) == "text"
        )
        if not text.strip():
            raise ModelRefusal(f"{self._model} returned no text content")
        return parse_proposal(text)
