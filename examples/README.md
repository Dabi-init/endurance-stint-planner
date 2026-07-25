# Example telemetry

`spa_6h_synthetic.csv` is deliberately synthetic. It demonstrates the expected
one-row-per-completed-lap format and the calibration workflow; it is not evidence
about a real car, driver, event, or simulator.

Required columns:

- `lap`
- `lap_time_sec` (seconds or `M:SS.sss`)

Recommended columns:

- `driver`
- `fuel_remaining_liters`
- `tyre_age_laps`
- `track_status` (`green`, `sc`, `fcy`, or another explicit label)
- `pit` (`true`/`false`)

The importer also recognizes common aliases such as `lap_number`, `laptime`,
`fuel_level`, `tire_age`, `status`, and `in_pit`. Fuel burn is estimated only
from consecutive, non-pit green laps with a plausible drop in remaining fuel.
Pace outliers are filtered with an interquartile-range rule.

Run the following to inspect mapped columns, row coverage, quality findings,
central estimates, and the uncertainty ranges used for strategy:

```powershell
pitwall ingest .\examples\spa_6h_synthetic.csv
pitwall --json ask "Audit telemetry quality"
```
