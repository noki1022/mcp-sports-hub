# Historical odds source registry

This registry keeps every candidate source found during the historical-odds search. It separates
three states:

- `research_smoke_only`: real and licensed, but too small for fitting.
- `closing_market_benchmark_only`: paired odds/results are useful to compare against the market,
  but the source does not prove a pre-close timestamp.
- `highest_priority_external_audit` or `pending_*`: promising, but not yet approved for
  training or redistribution.

No source in this registry is automatically copied into production features. A row must have an
auditable team/result join, an odds timestamp or explicit open/close semantics, a permitted
license, and a chronological split before it can enter training. Unlicensed or ambiguous rows
remain excluded.
