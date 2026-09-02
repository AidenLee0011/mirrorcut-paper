# -*- coding: utf-8 -*-
"""Experiment A components C1..C4 as switch blocks over tau2's LLMAgent (PREREG_A.md §3).

Switches via env EXPA_SWITCHES = JSON {"c1_guard":1,"c2_schema":-1,"c3_canon":1,"c4_checklist":-1}.
C1 policy guard: deterministic precondition check on state-changing tool calls using ONLY the transcript
   (prior read-tool results + user confirmation). Unmet -> the tool call is replaced by an assistant message
   naming the exact unmet condition (no model call; the model sees the user's next reply).
C2 schema diagnostics: validate tool-call arguments against the tool's JSON schema; on failure inject a
   system note with field-level diagnostics and regenerate once.
C3 tool-state canonicalization: canonical JSON (sorted keys, no whitespace loss) for incoming tool results.
C4 termination checklist: fixed checklist block appended to <instructions>.
Self-test: python -X utf8 components_a.py  (guard rules against synthetic transcripts, no model calls).
"""
from __future__ import annotations
import json, os, re

COMPONENTS = ["c1_guard", "c2_schema", "c3_canon", "c4_checklist"]

# state-changing tools and their preconditions, from the public policies (retail policy.md §Cancel/Modify/Return/Exchange;
# airline policy.md §Book/Modify/Cancel). read_tool = the read call whose result must appear earlier in the transcript.
GUARD = {
    "cancel_pending_order": dict(read="get_order_details", key="order_id", status={"pending"}, confirm=True),
    "modify_pending_order_address": dict(read="get_order_details", key="order_id", status={"pending"}, confirm=True),
    "modify_pending_order_payment": dict(read="get_order_details", key="order_id", status={"pending"}, confirm=True),
    "modify_pending_order_items": dict(read="get_order_details", key="order_id", status={"pending"}, confirm=True),
    "return_delivered_order_items": dict(read="get_order_details", key="order_id", status={"delivered"}, confirm=True),
    "exchange_delivered_order_items": dict(read="get_order_details", key="order_id", status={"delivered"}, confirm=True),
    "modify_user_address": dict(read="get_user_details", key="user_id", status=None, confirm=True),
    "cancel_reservation": dict(read="get_reservation_details", key="reservation_id", status=None, confirm=True),
    "update_reservation_flights": dict(read="get_reservation_details", key="reservation_id", status=None, confirm=True),
    "update_reservation_baggages": dict(read="get_reservation_details", key="reservation_id", status=None, confirm=True),
    "update_reservation_passengers": dict(read="get_reservation_details", key="reservation_id", status=None, confirm=True),
    "book_reservation": dict(read=None, key=None, status=None, confirm=True),
}
CONFIRM_RE = re.compile(r"\b(yes|confirm|confirmed|go ahead|please do|that's right|correct|ok(ay)?|sure)\b", re.I)

C4_BLOCK = ("Before ending the conversation, verify each of the following and fix any gap first: (1) every entity the user "
            "asked about was looked up with a read tool; (2) every policy condition for each action taken was checked "
            "against a tool result; (3) no tool call returned an error that is still unresolved; (4) the user explicitly "
            "confirmed every state-changing action before it was taken.")


def switches():
    s = json.loads(os.environ.get("EXPA_SWITCHES", "{}"))
    return {c: int(s.get(c, -1)) for c in COMPONENTS}


def canon(text):
    """C3: canonical JSON if the payload parses, else the text unchanged."""
    try:
        return json.dumps(json.loads(text), sort_keys=True, ensure_ascii=False, separators=(", ", ": "))
    except Exception:
        return text


def _tool_results(messages):
    """(tool_name, parsed result) pairs from prior tool messages, matched to the assistant tool call by id."""
    calls = {}
    for m in messages:
        for tc in (getattr(m, "tool_calls", None) or []):
            calls[getattr(tc, "id", None)] = (tc.name, tc.arguments)
    out = []
    for m in messages:
        if getattr(m, "role", None) == "tool":
            name, args = calls.get(getattr(m, "id", None), (None, {}))
            try:
                body = json.loads(m.content) if isinstance(m.content, str) else m.content
            except Exception:
                body = None
            out.append((name, args, body))
    return out


def _last_user_confirms(messages):
    for m in reversed(messages):
        if getattr(m, "role", None) == "user":
            return bool(CONFIRM_RE.search(m.content or ""))
    return False


def guard_check(tool_call, messages):
    """C1. Returns None if allowed, else the exact unmet condition (str)."""
    rule = GUARD.get(tool_call.name)
    if rule is None:
        return None
    args = tool_call.arguments or {}
    if rule["read"]:
        ident = args.get(rule["key"])
        seen = [(a, body) for (n, a, body) in _tool_results(messages) if n == rule["read"] and a.get(rule["key"]) == ident]
        if not seen:
            return "%s requires a prior %s call for %s=%s in this conversation" % (tool_call.name, rule["read"], rule["key"], ident)
        if rule["status"]:
            status = None
            body = seen[-1][1]
            if isinstance(body, dict):
                status = body.get("status")
            if status not in rule["status"]:
                return "%s requires %s=%s to have status %s; the last %s result shows status %r" % (
                    tool_call.name, rule["key"], ident, "/".join(sorted(rule["status"])), rule["read"], status)
    if rule["confirm"] and not _last_user_confirms(messages):
        return "%s requires an explicit user confirmation in the message immediately before the call" % tool_call.name
    return None


def schema_check(tool_call, tools):
    """C2. Field-level diagnostics against the tool's pydantic params; None if valid."""
    tool = next((t for t in tools if t.name == tool_call.name), None)
    if tool is None:
        return "unknown tool %s; available: %s" % (tool_call.name, ", ".join(sorted(t.name for t in tools)))
    try:
        tool.params.model_validate(tool_call.arguments or {})
        return None
    except Exception as e:  # pydantic ValidationError
        errs = getattr(e, "errors", None)
        if callable(errs):
            return "; ".join("%s: %s" % (".".join(str(x) for x in er.get("loc", [])), er.get("msg")) for er in errs())
        return str(e)


def register():
    from tau2.registry import registry
    from tau2.agent.llm_agent import LLMAgent
    from tau2.data_model.message import AssistantMessage, SystemMessage, MultiToolMessage

    class ExpAAgent(LLMAgent):
        @property
        def system_prompt(self):
            base = super().system_prompt
            if switches()["c4_checklist"] > 0:
                base = base.replace("</instructions>", "\n" + C4_BLOCK + "\n</instructions>", 1)
            return base

        def _generate_next_message(self, message, state):
            sw = switches()
            if sw["c3_canon"] > 0:
                tms = message.tool_messages if isinstance(message, MultiToolMessage) else ([message] if getattr(message, "role", None) == "tool" else [])
                for tm in tms:
                    if isinstance(tm.content, str):
                        tm.content = canon(tm.content)
            am = super()._generate_next_message(message, state)
            for _ in range(1):  # C2: at most one regeneration
                if sw["c2_schema"] > 0 and am.is_tool_call():
                    diags = [(tc.name, schema_check(tc, self.tools)) for tc in am.tool_calls]
                    bad = [d for d in diags if d[1]]
                    if bad:
                        note = "Tool argument validation failed: " + " | ".join("%s -> %s" % b for b in bad) + ". Fix the arguments and call again."
                        state.messages.append(am); state.messages.append(SystemMessage(role="system", content=note))
                        from tau2.utils.llm_utils import generate
                        am = generate(model=self.llm, tools=self.tools, messages=state.system_messages + state.messages,
                                      call_name="agent_response", **self.llm_args)
            if sw["c1_guard"] > 0 and am.is_tool_call():
                unmet = [guard_check(tc, state.messages) for tc in am.tool_calls]
                unmet = [u for u in unmet if u]
                if unmet:
                    return AssistantMessage(role="assistant", content="Before I can proceed: " + " ".join(unmet) + " Could you confirm, or let me check the current record first?")
            return am

    def create(tools, domain_policy, **kw):
        return ExpAAgent(tools=tools, domain_policy=domain_policy, llm=kw.get("llm"), llm_args=kw.get("llm_args"))
    registry.register_agent_factory(create, "expa_agent")
    return ExpAAgent


# ---- self-test on synthetic transcripts (no tau2 import needed)
class _M:
    def __init__(self, role, content=None, tool_calls=None, id=None):
        self.role, self.content, self.tool_calls, self.id = role, content, tool_calls, id


class _TC:
    def __init__(self, name, arguments, id="t1"):
        self.name, self.arguments, self.id = name, arguments, id


if __name__ == "__main__":
    read = _TC("get_order_details", {"order_id": "#W1"}, "r1")
    hist_pending = [_M("user", "cancel #W1 please"), _M("assistant", None, [read]), _M("tool", json.dumps({"order_id": "#W1", "status": "pending"}), id="r1"),
                    _M("assistant", "Order #W1 is pending. Cancel for 'no longer needed'? Please confirm."), _M("user", "yes, confirm")]
    assert guard_check(_TC("cancel_pending_order", {"order_id": "#W1", "reason": "no longer needed"}), hist_pending) is None
    hist_delivered = hist_pending[:2] + [_M("tool", json.dumps({"order_id": "#W1", "status": "delivered"}), id="r1")] + hist_pending[3:]
    u = guard_check(_TC("cancel_pending_order", {"order_id": "#W1"}), hist_delivered); assert u and "status" in u, u
    u = guard_check(_TC("cancel_pending_order", {"order_id": "#W2"}), hist_pending); assert u and "prior get_order_details" in u, u
    no_confirm = hist_pending[:-1] + [_M("user", "what does that mean?")]
    u = guard_check(_TC("cancel_pending_order", {"order_id": "#W1"}), no_confirm); assert u and "confirmation" in u, u
    assert guard_check(_TC("return_delivered_order_items", {"order_id": "#W1"}), hist_delivered) is None
    assert guard_check(_TC("get_order_details", {"order_id": "#W9"}), []) is None  # read tools never guarded
    assert canon('{"b": 1, "a": [2, 1]}') == '{"a": [2, 1], "b": 1}' and canon("not json") == "not json"
    print("components_a self-test OK: 7 guard cases + canon")
