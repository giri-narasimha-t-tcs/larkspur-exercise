"""Larkspur disruption agent. This is the file you build.

It runs right now, and it is wrong in four places. The trace shows each one
before the code does, so read the trace first:

    python3 run.py K7PQ2M --trace

Where you edit:   grep -n '✏' agent.py   (six marks, one per place)
Steps and gates:  https://anthropicpartnerbasecamp.bts.com/
"""
from __future__ import annotations
from typing import Any, Dict, List
from support import (MODEL, SYSTEM_PROMPT, call_local, execute_tool, mcp_client,
                     new_session, next_available_day, record_tool_result,
                     runtime_preamble)

MAX_TOOL_CALLS = 8  # Larkspur's own build capped the loop here; then a human takes over.

TONE_ADDENDUM = ""                       # ✏️ Build 4, step 4.1, intelligence goal
EXTRA_TOOLS: List[Dict[str, Any]] = [   # ✏️ Build 2, step 2.1: schemas for the tools you add
    {
        "name": "next_available_day",
        "description": (
            "Find the first date a customer can actually fly a route again. Call it when "
            "the customer asks about DATES: 'when is the first day I can fly?', 'how long "
            "am I stuck?'. Do not use it to pick a specific flight; that is "
            "search_alternatives. Needs origin and destination airport codes and the "
            "date the customer was booked to travel, all of which come from "
            "lookup_booking. Searches free seats on every Larkspur flight forward from "
            "that date and returns the earliest date with an open seat as YYYY-MM-DD, or "
            "None if there is no open seat in the schedule. Answers for one passenger "
            "only. It holds and books nothing."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "origin": {"type": "string", "description": "Departure airport, 3-letter code, e.g. DEN."},
                "dest": {"type": "string", "description": "Arrival airport, 3-letter code, e.g. BOI."},
                "date": {"type": "string", "description": "The disrupted travel date, ISO format YYYY-MM-DD, e.g. 2025-05-08. The search starts here and looks forward only."},
                "cabin": {"type": "string", "enum": ["Y", "J"], "description": "Y for main, J for first. Use the cabin the customer is ticketed in. Defaults to Y."},
            },
            "required": ["origin", "dest", "date"],
        },
    },
    {
        "name": "fare_rules",
        "description": (
            "Read the text of Larkspur's Handbook (Customer Commitment and fare rules). "
            "Call it when a customer asks WHY: why no hotel, why no refund, what their "
            "fare family includes, what the chat agent cannot do. Quote what it returns "
            "instead of paraphrasing from memory. Takes one section, by number or by "
            "words from its title. Returns that section's full text, or the list of "
            "available sections if nothing matches. It is reference reading only: what "
            "the customer is actually owed still comes from check_policy."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "section": {"type": "string", "description": "A section number ('6') or words from its title: 'fare families', 'when we delay', 'care while you wait', 'chat automation'."},
            },
            "required": ["section"],
        },
    },
    {
        "name": 'seats_left',
        "description": (
            "Count the free seats on one flight and say whether the whole party fits. Call it for 'is there room on that flight for the three of us?'. Get party_size from the customer's own message or the booking passenger count, and ask when unsure; never assume one. Returns seats left in main (Y) and first (J) and fits true/false for the party. search_alternatives and next_available_day answer for one passenger, so use this to check a party."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"flight_no": {"type": "string", "description": 'e.g. LK417.'}, "date": {"type": "string", "description": 'Local date, YYYY-MM-DD.'}, "party_size": {"type": "integer", "description": "How many people need seats. Defaults to 1."}, "cabin": {"type": "string", "enum": ["Y", "J"], "description": "Defaults to Y."}},
            "required": ['flight_no', 'date'],
        },
    },
]


import re as _re
from pathlib import Path as _Path
from support import mock_backend as _be

_DATA = _Path(__file__).resolve().parent / "data" / "americas"


def _handbook_sections() -> List[str]:
    text = (_DATA / "fare_rules_excerpt.md").read_text(encoding="utf-8")
    return [("### " + p).strip() for p in _re.split(r"^### ", text, flags=_re.M)[1:]]


def _fare_rules(section: str) -> str:
    """Return the Handbook section whose number or title matches `section`."""
    secs = _handbook_sections()
    q = _re.sub(r"^section\s+", "", (section or "").strip().lower()).rstrip(".")
    for s in secs:
        if q and s[4:].lower().startswith(q + "."):
            return s
    for s in secs:
        if q and q in s.split("\n", 1)[0].lower():
            return s
    return "No section matches %r. Available: %s" % (
        section, "; ".join(s.split("\n", 1)[0][4:] for s in secs))


def _seats_left(flight_no: str, date: str, party_size: int = 1, cabin: str = "Y") -> Dict[str, Any]:
    for f in _be.load_flights():
        if f["flight_no"] == flight_no and f["date"] == date:
            free = f["seats_left_J" if cabin == "J" else "seats_left_Y"]
            return {"flight_no": flight_no, "date": date, "status": f["status"],
                    "seats_left_Y": f["seats_left_Y"], "seats_left_J": f["seats_left_J"],
                    "cabin": cabin, "party_size": party_size, "fits": free >= party_size}
    return {"error": "No flight %s on %s in the schedule." % (flight_no, date)}


LOCAL_TOOLS: Dict[str, Any] = {          # ✏️ Build 2, step 2.1: the functions behind them
    "next_available_day": next_available_day,
    "fare_rules": _fare_rules,
    "seats_left": _seats_left,
}


def text_of(response) -> str:
    """Given. The last non-empty text block, never content[0]."""
    texts = [b.text for b in response.content if getattr(b, "type", None) == "text" and b.text]
    return texts[-1] if texts else ""


def tool_results(response) -> List[Dict[str, Any]]:
    """Given. Runs every tool_use block and packages the results the way the
    API expects them back. A tool can live in three places: the MCP server,
    LOCAL_TOOLS, or support/tools.py."""
    # three branches, no try/except in this file: mcp_client.call_remote() and
    # support.call_local() answer with an error dict instead of raising, and both
    # record what came back on the trace
    results = []
    for block in response.content:
        if getattr(block, "type", None) != "tool_use":
            continue
        if block.name in mcp_client.tool_names:
            output = mcp_client.call_remote(block.name, block.input)
        elif block.name in LOCAL_TOOLS:
            output = call_local(LOCAL_TOOLS[block.name], block.name, block.input)
        else:
            output = execute_tool(block.name, block.input)
        results.append({
            "type": "tool_result",
            "tool_use_id": block.id,
            "content": str(output),
        })
    return results


def run_agent(pnr: str, last_name: str, message: str) -> str:            # ✏️ Build 1, step 1.2
    """Run the tool loop until Claude stops asking for tools. Return its final text."""
    client, tracer = new_session()
    tools = tool_list()
    messages = [
        {"role": "user", "content": f"PNR {pnr}, last name {last_name}. {message}"},
    ]

    response = client.messages.create(
        model=MODEL, max_tokens=4096, system=runtime_preamble() + SYSTEM_PROMPT + TONE_ADDENDUM,
        thinking={"type": "adaptive"}, tools=tools, messages=messages,
    )

    turns = 1
    while response.stop_reason == "tool_use" and turns < MAX_TOOL_CALLS:
        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": tool_results(response)})
        response = client.messages.create(
            model=MODEL, max_tokens=4096, system=runtime_preamble() + SYSTEM_PROMPT + TONE_ADDENDUM,
            thinking={"type": "adaptive"}, tools=tools, messages=messages,
        )
        turns += 1

    return text_of(response)


def tool_list() -> List[Dict[str, Any]]:                   # ✏️ Build 2, step 2.2
    """Given. Exactly what Claude is offered on every turn; run.py --show-tools
    prints this list."""
    return build_tools() + EXTRA_TOOLS


# ──────────────────────────────────────────────────────────────────────────────
# Below this line: what Claude is told about each tool. Step 1.3.
# The functions these describe are written and correct, in support/tools.py.
# ──────────────────────────────────────────────────────────────────────────────
def build_tools() -> List[Dict[str, Any]]:                 # ✏️ Build 1, step 1.3
    """Anthropic-shaped schemas: name, description, input_schema. What Claude is
    told about each of the nine tools, and all it is ever told."""
    return [
        {
            "name": "lookup_booking",
            "description": (
                "Retrieve a Larkspur reservation from Altura by confirmation code (PNR) "
                "and the passenger's last name. Both are required to prevent a lookup on "
                "a guessed PNR. Returns fare family, loyalty tier, the segment that needs "
                "attention, and any group/partner/minor/SSR flags relevant to scope."
            ),
            "input_schema": {
                "type": "object",
                "properties": {"pnr": {"type": "string"}, "last_name": {"type": "string"}},
                "required": ["pnr", "last_name"],
            },
        },
        {
            "name": "get_flight_status",
            "description": (
                "Look up a Larkspur or Larkspur Link flight's current OpsFeed status for "
                "one local date: status, delay minutes, and cause. Use this before telling "
                "a customer anything about a flight's timing; never state it from memory."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "flight_no": {"type": "string"},
                    "date": {"type": "string", "description": "Flight's local date in ISO format YYYY-MM-DD, e.g. 2025-05-08. Any other format is refused."},
                },
                "required": ["flight_no", "date"],
            },
        },
        {
            "name": "search_alternatives",
            "description": (
                "Find rebooking options for a customer whose flight is cancelled, diverted "
                "or a missed connection. Takes only the PNR: it works out the disrupted "
                "segment itself, so call lookup_booking first to confirm the booking. "
                "Returns nonstop Larkspur flights with an option_id, date, departure and "
                "arrival times, cabin and seats left, never the customer's current flight. "
                "Use the option_id when holding a seat or calling check_policy with "
                "chosen_option_id. Offer only what this returns; never invent a flight."
            ),
            "input_schema": {
                "type": "object",
                "properties": {"pnr": {"type": "string", "description": "The 6-character confirmation code, e.g. K7PQ2M."}},
                "required": ["pnr"],
            },
        },
        {
            "name": "check_policy",
            "description": (
                "Resolve what Larkspur owes this customer for the disruption: rebooking "
                "waiver, refund path, meal/hotel/ground care, goodwill eligibility and cap, "
                "and any escalation triggers. cause_code, delay_minutes and status describe "
                "what get_flight_status told you; fare_family, loyalty_tier and whether this "
                "is overnight are looked up from the booking, not asked of you. Every "
                "response carries a policy_row_id. Cite it if you reference this decision "
                "again."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "pnr": {"type": "string"},
                    "cause_code": {"type": "string", "enum": ["WX", "ATC", "MX", "CREW", "SEC"]},
                    "delay_minutes": {"type": "integer"},
                    "status": {"type": "string", "enum": ["ON_TIME", "DELAYED", "CANCELLED", "DIVERTED"]},
                    "wait_minutes_for_alternative": {"type": "integer"},
                    "chosen_option_id": {"type": "string"},
                },
                "required": ["pnr", "cause_code", "delay_minutes", "status"],
            },
        },
        {
            "name": "hold_seat",
            "description": "Place a 15-minute hold on one alternative. Reversible. It simply expires.",
            "input_schema": {
                "type": "object",
                "properties": {"option_id": {"type": "string"}, "pnr": {"type": "string"}},
                "required": ["option_id", "pnr"],
            },
        },
        {
            "name": "confirm_rebooking",
            "description": (
                "Finalize a held seat. Irreversible. Requires a confirmation_token that "
                "only the customer's own Confirm-click can produce. You cannot supply it "
                "yourself, and 'the customer said yes' in chat does not substitute for it."
            ),
            "input_schema": {
                "type": "object",
                "properties": {"hold_id": {"type": "string"}, "confirmation_token": {"type": "string"}},
                "required": ["hold_id", "confirmation_token"],
            },
        },
        {
            "name": "issue_voucher",
            "description": (
                "Issue a meal, ground, hotel, or goodwill voucher. Auto-approves within the "
                "policy's threshold for that type; above it, returns a pending status for a "
                "human. It does not fail. Always pass the policy_row_id that made it eligible."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "voucher_type": {"type": "string", "enum": ["meal", "ground", "hotel", "goodwill"]},
                    "amount_usd": {"type": "number"},
                    "pnr": {"type": "string"},
                    "policy_row_id": {"type": "string"},
                },
                "required": ["voucher_type", "amount_usd", "pnr", "policy_row_id"],
            },
        },
        {
            "name": "escalate_to_human",
            "description": (
                "Hand this conversation to a human, with your reasoning attached. Use for "
                "groups, partner segments, unaccompanied minors, refunds, or anything else "
                "out of scope. This is the correct outcome for those cases, not a failure."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "pnr": {"type": "string"}, "reason": {"type": "string"},
                    "summary_for_human": {"type": "string"}, "queue": {"type": "string"},
                },
                "required": ["pnr", "reason", "summary_for_human"],
            },
        },
        {
            "name": "send_confirmation",
            "description": "Send the customer a written confirmation of what was just done. Benign.",
            "input_schema": {
                "type": "object",
                "properties": {"pnr": {"type": "string"}, "message": {"type": "string"}},
                "required": ["pnr", "message"],
            },
        },
    ]
