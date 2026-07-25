# Pitwall Agent — Launch Material

Ready-to-use copy for the `v0.4.0-alpha.1` public launch.

**Ground rule for every word in this file:** it must be true today. No invented
testimonials, download counts, star counts, team names, benchmarks, or
real-world validation. If a claim cannot be verified from the repository, the
CI logs, or a reproducible command, it does not ship.

- Repository: <https://github.com/Dabi-init/endurance-stint-planner>
- Landing page: <https://dabi-init.github.io/endurance-stint-planner/>
- Licence: MIT
- Status: alpha, synthetic (Evidence Level C) examples only

---

## 1. Short product description (tweet length)

> Pitwall Agent: build your endurance race plan, lap by lap — deterministically.
> Local-first, terminal-based fuel/tyre/driver strategy with auditable pit
> sheets. AI may explain the plan; it never owns the maths. Alpha, MIT, free.
> https://dabi-init.github.io/endurance-stint-planner/

---

## 2. Long product description (paragraph)

> Pitwall Agent is a free, open-source, local-first endurance race strategy tool
> that runs in your terminal. You give it your race duration, lap time, fuel
> burn, tank size, tyre life, and driver rules — or a telemetry CSV — and it
> produces three ranked strategies (Conservative, Balanced, Fuel Save), exact
> stint-by-stint fuel and tyre plans, driver rotation checks, P10/P90
> uncertainty bounds, pre-agreed trigger cards, and a printable Markdown pit
> sheet. Every number comes from a deterministic Python engine you can read and
> re-run. An optional local Ollama model can explain the plan in plain English,
> but it cannot invent or change a single figure. Nothing is uploaded anywhere.
> It is alpha software: all published examples use synthetic data, and no
> real-session validation exists yet.

---

## 3. LinkedIn announcement

> **Pitwall Agent v0.4.0-alpha.1 — an open-source endurance race strategy tool
> that refuses to let AI do the maths.**
>
> Planning an endurance race means juggling fuel reserves, tyre life, driver
> rotation rules and Safety Car timing. Most tools either stop at "how many laps
> fit in a tank?" or hide the answer behind a model you cannot audit.
>
> Pitwall Agent takes the opposite position. Every fuel, tyre, and driver
> calculation happens in a deterministic Python engine you can read line by
> line. An optional local language model may explain the plan — it can never
> invent, change, or own the race mathematics. Your telemetry never leaves your
> machine.
>
> What it does today:
> • Ranks Conservative / Balanced / Fuel Save strategies side by side
> • Plans exact stint fuel loads, additions, tyre sets, and driver rotation
> • Reports P10/P90 uncertainty instead of false precision
> • Ingests telemetry CSVs and labels every input Evidence Level A/B/C
> • Exports a scannable Markdown pit sheet with pre-agreed trigger cards
> • Runs fully offline, with JSON output for anyone who wants to script it
>
> Being honest about the stage: this is alpha. Every published example uses
> synthetic data (Evidence Level C). There is no real-session validation yet,
> no live timing, and no competitor prediction — and I will not claim otherwise
> until someone runs it against a real event and shares the result.
>
> That is exactly what I am asking for. If you run sim endurance races, please
> try it, break it, and tell me what was confusing. If you can share an
> anonymised session, it becomes the first real validation case study.
>
> Docs and install: https://dabi-init.github.io/endurance-stint-planner/
> Source (MIT): https://github.com/Dabi-init/endurance-stint-planner
>
> #simracing #enduranceracing #opensource #python #motorsport #racestrategy

---

## 4. GitHub release announcement (`v0.4.0-alpha.1`)

> ## Pitwall Agent v0.4.0-alpha.1
>
> Alpha release focused on comprehension, auditability, and onboarding.
>
> ### Added
> - `pitwall welcome` — plain-English explanation of every concept the tool uses
> - `pitwall init --guided` — interactive setup with validated ranges and input provenance
> - `pitwall validate` — compare a plan against actual results and write a Markdown report
> - Strategy trigger cards (HOLD / RECONSIDER) in plan, comparison, and pit sheet output
> - Public documentation site and launch material
>
> ### Changed
> - `pitwall export` now defaults to the recommended strategy
> - Pit sheets label P10 as pessimistic and P90 as optimistic, and spell out what each evidence level means
> - Driver names are anonymised (`Driver_1`, `Driver_2`, …) before any model sees a tool result
> - Safety Car output carries an explicit pre-race-only disclaimer
>
> ### Known limitations
> - Alpha software, not production-validated
> - All bundled examples are synthetic (Evidence Level C)
> - No live timing, no competitor data, no official regulation database
> - Ollama is optional; every deterministic feature works without it
>
> ### Install
> ```
> pip install pitwall-agent   # if unavailable, install the wheel from this release
> pitwall doctor
> pitwall welcome
> pitwall compare
> ```

---

## 5. Reddit post — r/simracing and r/enduranceracing

**Title:** I built a free, open-source endurance race strategy planner that runs
in your terminal — and deliberately keeps AI away from the maths

> Hi all,
>
> I kept doing endurance stint planning in messy spreadsheets and losing track of
> which numbers were measured and which ones I had guessed. So I built
> **Pitwall Agent**: a local-first, terminal-based strategy planner.
>
> You enter race duration, lap time, fuel burn, tank size, tyre life and driver
> rules (or feed it a telemetry CSV), and it gives you:
>
> - three ranked strategies — Conservative, Balanced, Fuel Save
> - exact stint plan: laps, driver, fuel start/add, tyre set, pit time
> - P10/P90 uncertainty bounds instead of one fake-precise answer
> - Evidence Level A/B/C on every input, so you know what is measured vs assumed
> - trigger cards: pre-agreed "hold the plan" / "reconsider" thresholds
> - a Markdown pit sheet you can print or keep open on the second monitor
>
> There is an *optional* local Ollama integration, but it only explains the plan.
> It cannot change a number. All the arithmetic is plain deterministic Python
> with tests and CI.
>
> **Honesty section, because this sub deserves it:** it is alpha. Every example
> shipped with it is synthetic data. I have not validated it against a real
> session yet. It does no live timing, no competitor prediction, and it has no
> official rulebook — it only checks the rules you configure.
>
> What I would love: try it, tell me where it confused you, and if you are
> willing, share an anonymised session so I can build the first real validation
> case study.
>
> Site: https://dabi-init.github.io/endurance-stint-planner/
> Code (MIT): https://github.com/Dabi-init/endurance-stint-planner

---

## 6. Discord message template

> **Pitwall Agent — free open-source endurance strategy planner (alpha)** 🏁
>
> Terminal tool that turns fuel burn, tyre life, and driver rules into three
> ranked strategies plus a printable pit sheet. Deterministic engine — AI can
> only explain the plan, never change the numbers. Runs offline, MIT licensed.
>
> ```
> pip install pitwall-agent
> pitwall doctor && pitwall welcome && pitwall compare
> ```
>
> ⚠️ Alpha, synthetic examples only, no real-session validation yet, pre-race
> planning only (no live race control).
>
> Docs → <https://dabi-init.github.io/endurance-stint-planner/>
> Repo → <https://github.com/Dabi-init/endurance-stint-planner>
>
> Feedback and anonymised sessions very welcome — especially "this bit made no
> sense to me" feedback.

---

## 7. FAQ

**1. What exactly is Pitwall Agent?**
A free, open-source command-line tool that builds a pre-race endurance strategy:
stints, fuel, tyres, driver rotation, uncertainty bounds, and a pit sheet.

**2. Do I need to know Python?**
No. You need Python 3.11+ installed, then `pip install pitwall-agent`. After
that you only type `pitwall` commands. `pitwall welcome` explains every term,
and `pitwall init --guided` walks you through setup question by question.

**3. Do I need AI or an API key?**
No. Every deterministic feature works with no model at all. If you install
[Ollama](https://ollama.com/) locally, the model can explain results in plain
English over loopback only. There is no cloud AI and no API key anywhere.

**4. Can I use it for real (non-sim) racing?**
You can, but treat it as a planning aid, not an authority. It is alpha software
with no published real-session validation. Any real-world use is at your own
risk and should be cross-checked against your own numbers.

**5. Does it know my series' sporting regulations?**
No. It checks the rules *you* configure — such as minimum drive time or driver
count. It does not ship an official rulebook for any series, and you remain
responsible for compliance.

**6. Where does my data go?**
Nowhere. Everything is written to a visible `.pitwall/` folder on your machine.
There is no telemetry upload, no analytics, and the landing page contains no
tracking scripts.

**7. Is this only for sim racing?**
It is designed and tested with sim endurance racing in mind, because that is
where the reproducible data is. The maths is not sim-specific, but the only
validation data we have today is synthetic.

**8. How can I contribute?**
Read `CONTRIBUTING.md`. Bug reports and "this was confusing" feedback are as
valuable as code. Contributors: the engine is typed Python, tests run under
pytest, and CI enforces ruff plus 85% coverage.

**9. What does "alpha" mean here concretely?**
Interfaces may change, examples use synthetic data labelled Evidence Level C,
there are no real-session case studies, and some planned features (simulator
adapters, real validation) are still open issues.

**10. When will there be a 1.0?**
When there is at least one published real-session validation case study, a
stable CLI and JSON contract, and the roadmap gates in `ROADMAP.md` are met. No
date is promised — a fake date would break the honesty rule this project runs on.

---

## 8. Suggested screenshots and demo commands

Record these in a clean terminal, in a fresh workspace, at ~100 columns:

```
pitwall doctor        # environment check
pitwall welcome       # plain-English concept tour
pitwall init --guided # guided setup with validated ranges
pitwall compare       # three ranked strategies
pitwall plan          # full stint table for one strategy
pitwall scenario      # pre-race Safety Car what-if (note the disclaimer)
pitwall export        # writes the Markdown pit sheet
```

Also capture the exported pit sheet from `.pitwall/reports/` rendered as
Markdown. Caption every screenshot with: *"Synthetic example data (Evidence
Level C) — not a performance claim."*

---

## 9. Feedback request template

> Thanks for trying Pitwall Agent. Five questions, honest answers please:
>
> 1. Could you install it without help? Where did it stall?
> 2. Did you understand the recommendation it gave you, and why?
> 3. Did the pit sheet actually help you on race day?
> 4. What was confusing, missing, or wrong?
> 5. Would you share an anonymised session so we can validate the engine?
>
> Open an issue: https://github.com/Dabi-init/endurance-stint-planner/issues/new/choose

---

## 10. Anonymised data contribution request

> **We need real data to stop being Evidence Level C.**
>
> Every example we publish today is synthetic. The single most useful thing you
> can give this project is one real session:
>
> - a lap-time CSV (lap number, lap time, and fuel used per lap if available)
> - the actual stint lengths, pit stops, and total laps completed
> - the car/track combination and race duration
>
> Please strip anything you do not want public: driver names, team names, and
> account identifiers. Pitwall Agent already anonymises driver names before any
> model sees them, and `pitwall validate` produces a comparison report you can
> read before sharing anything.
>
> Send it as a pull request or attach it to an issue — see `CONTRIBUTING.md`.
> Contributed sessions will be credited (or kept anonymous, your choice) and
> used to publish the first Evidence Level A/B validation case study.

---

## 11. Limitations statement (reuse verbatim anywhere)

> Pitwall Agent is alpha software for **pre-race planning only**. It is not live
> race control. It has no live timing, no competitor prediction, and no
> proprietary telemetry integrations. All bundled examples use synthetic data
> (Evidence Level C) and no real-session validation has been published. Its
> Safety Car support is a declared pre-race what-if scenario, not a live
> reaction. It checks only the driver and stint rules you configure — it is not
> a substitute for your series' sporting regulations. An optional local model
> may explain results; it never computes or alters them. Use it as a planning
> aid, and verify anything that matters.
