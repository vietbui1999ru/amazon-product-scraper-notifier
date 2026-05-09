# 0001 — Amazon-only comparison baseline

The comparison baseline for drop detection is always the last successful Amazon scrape. Demo drops and scheduled prices (`source="self"`) never become the baseline for future comparisons.

**Why:** Injected prices pollute the baseline. A demo drop to $5 followed by an Amazon scrape at $100 would previously compare $100 against $5 (no drop detected) — hiding real future drops. Option B (Amazon-only baseline) means the ground truth resets correctly after every real scrape, regardless of what was injected.

**Consequence:** If no Amazon scrape exists yet for a product, no comparison baseline exists and no notification fires — even for demo drops. This is acceptable; demo drops on products that have never been scraped are meaningless.
