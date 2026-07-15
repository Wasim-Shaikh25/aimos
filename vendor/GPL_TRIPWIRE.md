# GPL_TRIPWIRE.md — distribution tripwire (§21.1, §22.3 rule 5)

AIMOS is a **private, non-distributed** project, so GPL obligations do not
currently trigger. Every file below carries GPL-origin code (or a concept
reimplementation from GPL-derived design) and MUST be clean-room rewritten from
the spec **before any distribution** (sale, sharing, offering as a service, or
open-sourcing).

> CI prints a reminder whenever this list is non-empty (see
> `scripts/check_gpl_tripwire.py`).

| File | GPL origin (repo:path) | Status |
|---|---|---|
| `vendor/ft_protections/__init__.py` | freqtrade/freqtrade:freqtrade/plugins/protections/ | concept reimpl — rewrite before distribution |
| `aimos/universe/filters.py` (VolatilityFilter) | freqtrade/freqtrade:freqtrade/plugins/pairlist/ | concept reimpl — rewrite before distribution |
