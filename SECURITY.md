# Security policy

## Supported version

Security fixes target the latest release and `main`.

## Reporting

Do not open a public issue for a vulnerability. Use GitHub’s
[private vulnerability reporting form](https://github.com/Dabi-init/endurance-stint-planner/security/advisories/new)
with:

- affected version or commit;
- reproduction steps or a minimal file;
- expected impact;
- any suggested remediation.

Never attach credentials, proprietary telemetry, or personal data. You should
receive an acknowledgement within seven days. There is currently no bug-bounty
programme.

## Data and model boundary

Pitwall runs locally and has no project analytics or cloud telemetry service.
Runtime files stay under the selected `.pitwall` workspace. Telemetry must be
explicitly ingested before a model-visible tool can read it; tool file names
cannot escape `.pitwall/data`.

The optional Ollama provider is restricted to loopback hosts. The model receives
six typed race tools and no shell, browser, arbitrary network, arbitrary file,
deletion, or overwrite capability. New reports are create-only.

Security reports are especially useful for:

- path traversal or writes outside `.pitwall`;
- model tool allowlist or argument-validation bypasses;
- prompt injection that changes tool policy;
- hidden network requests or telemetry disclosure;
- report overwrites without explicit CLI action;
- dependency or workflow supply-chain issues.

The race model is decision support, not a safety-certified live control system.
Incorrect sporting assumptions are model-validity issues unless they also cross
a software security boundary.
