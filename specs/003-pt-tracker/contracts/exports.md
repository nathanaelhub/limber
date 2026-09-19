# Contract: roster CSV

**Feature**: 003-pt-tracker. Pure function of the roster rows plus the generation time.

Header row (units in names), `\r\n` line endings, one row per active patient in attention
order, empty cells for missing values:

```text
patient_id,label,program,program_status,days_since_last_session,sessions_last_7_days,sessions_last_30_days,adherence_percent,pending_reviews,open_flags,practice_gap,last_next_step
```

`practice_gap` is `true`/`false`. File name `roster_<YYYYMMDD_HHMMSS>.csv` under `exports/`
by default; not recorded in any table (research D10).
