# Contributing

Start with a concrete debugging case. A small callback and synthetic bars are more useful than a screenshot of a suspicious Sharpe ratio. Do not submit credentials, account details, licensed market datasets or proprietary strategies.

```bash
python -m pip install -e ".[dev,adapters]"
python -m pytest
python -m build
```

Keep the standard-library core independent of optional engines. A new adapter must recreate all engine state, return every bar and document whether it records intended targets or observed positions. Include a planted leaky control and a causal control through the actual framework.

Tests should assert externally meaningful behavior. Use hand-calculated ledgers and independent traces; avoid tests that duplicate production formulas. For detector changes include repeatability, availability timing and budget behavior. For report changes test offline output, hostile text and narrow-screen/keyboard usability. A generated regression test is expected to fail on the planted bug and should pass after the callback is fixed.

Describe the concrete problem and resulting behavior in a change request. Include validation and material limits. Keep API changes documented in the callback contract/report schema. Discuss broad asset/execution support before adding it: silent interpretation changes can invalidate findings.
