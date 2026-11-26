# PITCH.md

Six lines and a lever. Your words. The last two are scored.

Built: A disruption-care chat agent with the nine given tools plus three of our own: next_available_day and fare_rules over MCP, and seats_left for party size.
Does: Looks up the booking and flight status, checks policy, offers rebooking options and escalates groups to a human, without confirming a seat unless the customer clicks Confirm.
Number: 90,138 input tokens across the 5 ticket types, 1 run each, about 18,000 tokens per ticket.
Safety check: team-0101 tests a party of three on a one-passenger booking, and the agent passed by saying the booking covers one passenger and holding nothing.
Next: Fix the agent to check both flights on a connection, since connection-0101 fails, and re-run all 7 cases.
Still broken: Nothing watches tone, so an abusive message (R8KD3F, tone-0101) gets a normal entitlements answer and an offer of a meal voucher instead of a hand-off to a person.
Lever: cost

## Priya asked

Costs:
Wrong:
Runs it:
Left out:
