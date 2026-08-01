# Pitwall Agent — Launch Material

Draft public copy for the unreleased `v0.4.0-alpha.2` hardening release. Replace
the source-only wording with versioned release-asset links only after the tag and
assets exist.

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
> sheets. Optional local Ollama routes plain-language questions; deterministic
> tools own the facts. Alpha, MIT, free.
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
> re-run. An optional local Ollama model can route a plain-English question into
> a typed race-tool call, but it cannot invent or change a single figure.
> Nothing is uploaded anywhere. It is alpha software: all bundled examples use
> synthetic data, and no
> real-session validation exists yet.

---

## 3. LinkedIn announcement

> **Pitwall Agent v0.4.0-alpha.2 — an open-source endurance race strategy tool
> that refuses to let AI do the maths.**
>
> Planning an endurance race means juggling fuel reserves, tyre life, driver
> rotation rules and Safety Car timing. Most tools either stop at "how many laps
> fit in a tank?" or hide the answer behind a model you cannot audit.
>
> Pitwall Agent takes the opposite position. Every fuel, tyre, and driver
> calculation happens in a deterministic Python engine you can read line by
> line. An optional local Ollama model may route a question into an allowlisted
> tool; Pitwall renders the displayed answer locally from the successful result.
> Your telemetry never leaves your machine.
>
> What it does today:
> • Ranks Conservative / Balanced / Fuel Save strategies side by side
> • Plans exact stint fuel loads, additions, tyre sets, and driver rotation
> • Reports P10/P90 uncertainty instead of false precision
> • Audits telemetry CSVs and states the result's source, confidence, and Evidence Level A/B/C
> • Exports a scannable Markdown pit sheet with pre-agreed trigger cards
> • Core planning works offline after installation, with JSON output for scripting
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

## 4. GitHub release announcement (draft `v0.4.0-alpha.2`)

> ## Pitwall Agent v0.4.0-alpha.2
>
> Hardening release focused on safe failure, bounded storage, trustworthy local
> AI routing, and reproducible installation.
>
> ### Hardened
> - Corrupt race or configuration files fail closed with recovery guidance
> - JSON failures return valid error payloads and nonzero exit status
> - Telemetry, history, model responses, and generated reports have explicit size limits
> - App-owned control files use atomic writes; reports remain exclusive-create
> - Unknown or failed model tool calls cannot ground a displayed race answer
> - Python 3.14 joins the tested CI matrix
>
> ### Changed
> - Ollama is a bounded local intent router; final race facts are rendered locally
> - Windows one-click startup caches installation and exposes `/setup`, `/compare`, `/plan`, and `/export`
> - Synthetic telemetry stays at Evidence Level C after renaming or line-ending conversion
> - Narrow terminal output is more compact and actionable
>
> ### Known limitations
> - Alpha software, not production-validated
> - All bundled examples are synthetic (Evidence Level C)
> - No live timing, no competitor data, no official regulation database
> - No published real-model conformance benchmark; direct commands remain the operational path
> - `pitwall model recommend` is advisory only; it never contacts Ollama, downloads a model, creates a workspace, or changes configuration
>
> ### Install the current candidate
> ```
> # Windows: download the source ZIP, extract it, then double-click run.bat
> https://github.com/Dabi-init/endurance-stint-planner/archive/refs/heads/main.zip
> ```
>
> Alpha.2 is not on PyPI and has no release asset yet. Add the versioned wheel
> URL here only after the tag and asset have been published.

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
> - result-level Evidence A/B/C, source, confidence, assumptions, and warnings
> - trigger cards: pre-agreed "hold the plan" / "reconsider" thresholds
> - a Markdown pit sheet you can print or keep open on the second monitor
>
> There is an *optional* local Ollama integration for routing plain-language
> questions into typed tools. It cannot change a number. All arithmetic and
> final race facts come from deterministic Python with tests and CI.
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
> ranked strategies plus a printable pit sheet. Deterministic engine; optional
> local Ollama routes questions but never changes the numbers. Core planning
> works offline after installation. MIT licensed.
>
> ```
> Download the source ZIP, extract it, and double-click run.bat:
> https://github.com/Dabi-init/endurance-stint-planner/archive/refs/heads/main.zip
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
No. On Windows, install Python 3.11–3.14, download and extract the source ZIP, then
double-click `run.bat`. The launcher creates a private environment and opens an
interactive prompt. `/welcome` explains every term, and `/setup` walks
you through setup question by question.

**3. Do I need AI or an API key?**
No. Every deterministic feature works with no model at all. If you install
[Ollama](https://ollama.com/) locally, the model can route plain-English
questions into typed local tools over loopback only. There is no cloud AI and
no API key anywhere.

Pitwall never downloads a model automatically. Core-only remains the verified
operational default. The provisional first model to try is `qwen3:8b` (about
5.2 GB of model storage): opt in with
`ollama pull qwen3:8b`, then `python -m pitwall model use qwen3:8b`. The lighter
unverified candidate is `qwen3:4b` (about 2.5 GB): use `ollama pull qwen3:4b`, then
`python -m pitwall model use qwen3:4b`. Ollama's Windows installation requires
at least 4 GB, so budget roughly 9.2 GB or more for the 8B setup before caches
and other models.

Core-only uses zero model storage, needs no Ollama installation, and keeps every
deterministic function available. Clear a previous selection with
`python -m pitwall model off`, then remove its files with `ollama rm qwen3:8b`
or `ollama rm qwen3:4b`. By comparison, the measured current source plus its
private core environment uses about 28 MB.

`pitwall model recommend` runs a read-only deterministic core self-check and
prints these Ollama-only choices. It never contacts Ollama, downloads a model,
creates a workspace, or changes configuration. Both candidates remain
unverified until Pitwall publishes a real-model tool-calling conformance
benchmark.

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
When there are at least three published anonymised real-session case studies, a
stable CLI and JSON contract, and every remaining gate in `ROADMAP.md` is met.
No date is promised — a fake date would break the honesty rule this project runs
on.

---

## 8. Suggested screenshots and demo commands

Record these in a clean terminal, in a fresh workspace, at ~100 columns:

```
pitwall doctor        # environment check
pitwall welcome       # plain-English concept tour
pitwall init --guided # guided setup with validated ranges
pitwall compare       # three ranked strategies
pitwall plan          # full stint table for one strategy
pitwall scenario 120 20 # pre-race Safety Car what-if (note the disclaimer)
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
> account identifiers. Pitwall Agent anonymises configured driver names in tool
> payloads before returning them to the model, but free-form prompts are not a
> place for private identifiers. `pitwall validate` produces a comparison report
> you can read before sharing anything.
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
> may route a question into an allowlisted tool; Pitwall renders the displayed
> answer locally from deterministic output. Use it as a planning aid, and verify
> anything that matters.
