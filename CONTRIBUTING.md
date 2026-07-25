# Contributing

Thanks for helping make endurance strategy more transparent and testable.

## Good contributions

- anonymised telemetry schemas or fixtures that expose an importer gap;
- event-rule examples with a public source;
- adversarial model tests and reproducible defect reports;
- accessibility, explanation, and pit-wall export improvements;
- documentation that narrows an unsupported claim.

Do not submit confidential team data, copyrighted timing feeds, credentials, or
driver personal data.

## Local setup

Python 3.11–3.13 is supported.

```powershell
git clone https://github.com/Dabi-init/endurance-stint-planner.git
Set-Location .\endurance-stint-planner
python -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
& .\.venv\Scripts\python.exe -m pitwall doctor
& .\.venv\Scripts\python.exe -m pitwall compare
```

Before opening a pull request:

```powershell
& .\.venv\Scripts\python.exe -m ruff check .
& .\.venv\Scripts\python.exe -m ruff format --check .
& .\.venv\Scripts\python.exe -m pytest --cov
```

## Model-change standard

A change to fuel, pace, tyre, pit-service, driver, or Safety Car logic should
include:

1. the real decision it supports;
2. units and safe input ranges;
3. the evidence source or a clear “assumption” label;
4. a normal-case unit test;
5. at least one boundary or adversarial test;
6. an explanation of the remaining limitation.

Every user-facing control must materially affect a relevant output or be
removed. Synthetic results must remain labelled synthetic.

## Pull requests

Keep changes focused. Explain the decision impact, tests run, and any change in
model scope. Terminal captures are useful for visible CLI changes. By contributing,
you agree that your work is licensed under the repository’s MIT License.
