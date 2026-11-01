# 007 Multi-Company Consensus Quality and Fusion Guardrails

## Purpose

Use multiple validated Titan007 company-ID quotes to build a robust market reference for NBA full-game spread and total markets. This is a research reference only. It must not replace the direct Jingcai price, the fixed Crown ID 3 price, the independent model probability, or any production selection.

## Quote admission

- Accept only dated 007 company-ID rows already admitted by the source audit.
- Keep company IDs distinct; duplicate IDs are rejected rather than counted twice.
- Require timezone-aware source-capture timestamps, pre-tip quotes, a maximum capture age of 15 minutes, and a maximum cross-company capture skew of 15 minutes.
- Keep ID 3 as the user's fixed Crown mapping. Do not infer bookmaker names, ranking, or professional status from IDs.
- Convert each company's two Hong Kong water prices to implied probabilities, then remove that company's margin before aggregation.

## Main-line selection

A statistical median can fall between two real offered lines. It is useful as a robust summary, but it is not a price that any company quoted.

The pipeline therefore reports both:
- `median_line`: statistical median of admitted company lines.
- `main_line`: the most-supported actual line among non-outlier companies.

Ties in modal support are resolved only when one tied line is uniquely closest to the statistical median. Otherwise the main line is marked ambiguous. A usable main line requires at least three distinct companies at that exact line.

Line outliers are identified using a median/MAD threshold and excluded from the effective-company, line-range, same-line price, and effective capture-skew calculations. Raw company count and raw capture skew remain visible for audit; effective company count, excluded IDs, main-line support and exact same-line IDs remain separately visible.

## Market probability reference

At the selected actual main line, calculate each company's no-vig probability independently. The market reference is the equal-weight median of those company probabilities, with IQR, range, company IDs and capture skew retained.

Do not average quotes across different lines. Do not interpolate probabilities onto a synthetic line. Do not apply company-specific weights until there is sufficient timestamped, independent, chronological evidence for those weights.

## Independent model and fusion

The independent NBA model remains odds-blind. Multi-company market probabilities are compared with it in shadow mode only.

Fusion research must:
- pair the same game and market at the same actual line;
- require the market snapshot to predate the frozen model report, with no more than 15 minutes of lag;
- reject post-tip data, missing report-generation timestamps and duplicate event rows;
- split by Beijing game dates in chronological order (60% train / 20% validation / 20% holdout);
- select the market weight on validation dates only;
- report accuracy, Brier score, Log Loss, calibration gap and 10-bin ECE;
- report a paired 95% bootstrap interval clustered by Beijing game date.

The existing review threshold remains at least 100 matched events across at least 24 distinct Beijing dates. Meeting the threshold permits research review, not automatic production promotion.

## Known limitations

- The current multi-company feed supplies spread and total quotes, not direct head-to-head quotes. Spread consensus is not a moneyline probability.
- The source capture timestamp is the time the 007 page was collected; it is not independently verified as the bookmaker's own last price-update time.
- The validated source IDs are not a verified ranking of the displayed top ten bookmakers. Company names and professional status remain unverified.
- Historical 007 coverage is still accumulating. No ROI, CLV or accuracy improvement is claimed without matched, frozen, chronological settlement evidence.

## Production boundary

Production model probabilities, market decision gates, schedules and PushPlus output remain unchanged. A candidate may be promoted only after an untouched chronological holdout demonstrates improvement over both the independent model and the multi-company market reference, with no leakage or data-quality regression and a separate explicit approval.
