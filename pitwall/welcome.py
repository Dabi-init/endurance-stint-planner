"""Plain-English onboarding content for people new to endurance strategy.

The text lives here, not in the CLI, so it can be asserted in tests and reused
by any future surface without duplicating wording.
"""

from __future__ import annotations

WELCOME_TITLE = "Welcome to Pitwall Agent"

WELCOME_INTRO = (
    "Pitwall Agent is a pre-race planning tool. Every number below is produced "
    "by a deterministic calculator you can audit. It is not live race control."
)

WELCOME_SECTIONS: list[tuple[str, str]] = [
    (
        "What a stint is",
        "A stint is the run between two pit stops: the car leaves the pit lane, "
        "drives a number of laps, and comes back in. Stint length is limited by "
        "whichever runs out first - fuel, tyre life, or the maximum time one "
        "driver is allowed to stay in the car.",
    ),
    (
        "Fuel reserve",
        "The fuel reserve is a deliberate safety buffer, counted in whole laps, "
        "that you never plan to use. With a one-lap reserve the plan assumes you "
        "must be able to complete one extra lap beyond the planned stint. A "
        "bigger reserve is safer but costs laps over the race.",
    ),
    (
        "Tyre life",
        "Tyre life is how many laps you are willing to run one set of tyres. If "
        "the planned stint is longer than the tyre life, the plan needs an extra "
        "tyre change - or a shorter stint.",
    ),
    (
        "P10 and P90 (pessimistic and optimistic)",
        "Pitwall runs the same plan many times with slightly different pace and "
        "fuel burn, then reports the range. P10 (pessimistic/slower) is the "
        "unlucky end of that range and P90 (optimistic/faster) is the lucky end. "
        "Plan for P10, do not promise P90.",
    ),
    (
        "Evidence Levels A, B, and C",
        "Evidence Level A means the numbers came from several audited real "
        "sessions. B means one audited real session. C means assumed, preset, or "
        "synthetic values. Anything at Level C is an estimate, not a measurement.",
    ),
    (
        "Parallel and sequential pit service",
        "Parallel service means refuelling, tyres, and the driver change happen "
        "at the same time, so the stop costs roughly the longest single job. "
        "Sequential service means they happen one after another, so the stop "
        "costs the sum. Your event regulations decide which applies.",
    ),
    (
        "Safety Car scenarios",
        "A Safety Car scenario is a what-if you declare yourself: you tell "
        "Pitwall when a Safety Car appears and how long it lasts, and it "
        "re-plans against that assumption. Pitwall receives no live race control "
        "data and cannot predict real Safety Car events.",
    ),
    (
        "If you have no telemetry",
        "Telemetry is optional. Without it, Pitwall uses your manual assumptions "
        "or a bundled preset, labels the run as 'Manual assumptions', and keeps "
        "the Evidence Level at C. Add a one-row-per-lap CSV with "
        "`pitwall ingest FILE.csv` when you have real data.",
    ),
    (
        "What this tool cannot know",
        "Pitwall cannot see live timing, traffic, weather, track limits, race "
        "control decisions, or your event's specific sporting regulations. It "
        "does not know your competitors' plans. Treat every output as pre-race "
        "decision support that a human must approve.",
    ),
    (
        "Trigger cards",
        "A trigger card names one thing to watch during the race, the band it "
        "should stay inside, and the action agreed in advance if it leaves that "
        "band: HOLD the plan, or RECONSIDER it with a fresh calculation.",
    ),
]

WELCOME_NEXT_STEPS = [
    "pitwall init --guided   # step-by-step race setup with safe ranges",
    "pitwall compare         # rank three strategies under the same uncertainty",
    "pitwall plan            # see the stint-by-stint sheet",
    "pitwall export          # write a Markdown pit sheet for the crew",
    "pitwall model recommend # optional read-only Ollama choices; downloads nothing",
]

GUIDED_OFFER = (
    "Would you like to set up your first race now with guided prompts? "
    "This runs `pitwall init --guided` and writes nothing until you confirm."
)


def welcome_payload() -> dict[str, object]:
    """Machine-readable form of the welcome content for `--json`."""
    return {
        "title": WELCOME_TITLE,
        "intro": WELCOME_INTRO,
        "sections": [
            {"heading": heading, "body": body} for heading, body in WELCOME_SECTIONS
        ],
        "next_steps": list(WELCOME_NEXT_STEPS),
        "guided_offer": GUIDED_OFFER,
    }
