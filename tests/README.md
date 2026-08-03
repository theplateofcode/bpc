# Golden master test suite

This suite exists for one reason: to let the app be optimised **without changing
what it computes**. It records the current output of the financial logic and the
report endpoints, and fails if any of it moves.

## Running

```bash
python manage.py test tests --settings=main.settings_test
```

`main.settings_test` swaps MySQL for in-memory SQLite so the suite runs anywhere,
including CI, with no database server. Nothing in it affects production.

To regenerate the snapshot after an **intentional** behaviour change:

```bash
UPDATE_GOLDEN=1 python manage.py test tests --settings=main.settings_test
```

Then read the diff on `tests/golden_master.json` before committing it. Every line
that changed is a behaviour change you are signing off on. If you did not mean to
change behaviour, do not regenerate — fix the code.

## What is covered

`tests/seed.py` builds a fixed dataset (no randomness, no `now()`) shaped to hit
the branches the money code actually has: cash vs non-cash, domestic vs
international, sales below purchase, zero amounts, a booking with services
assigned but no service rows, a booking with nothing at all, several rows of the
same service type, fractional amounts, and payments in approved / pending /
discounted / split states.

The snapshot has three sections:

| Section | What it pins |
|---|---|
| `model_properties` | All seven `Booking` money properties per booking, plus `all_services_finished()` and `get_service_statuses()` |
| `booking_list` | Row ordering and the four rendered money cells across 24 sort/filter permutations of the bookings list |
| `endpoints` | 19 read-only report endpoints × 7 filter permutations = 133 responses |

## Known-failing endpoints (pre-existing, pinned as-is)

The snapshot records what the app does **today**, bugs included. A baseline that
quietly fixes things is not a baseline.

- `/reports/api/report-filters-legacy/` — returns **HTTP 500 on every call**.
  `reports/views_legacy.py:154` calls `.dates("booking_date", "year")`, which
  yields `date` objects, then calls `.values_list("year", flat=True)` on the
  result. `year` is not a field, so it raises `FieldError`. Line 160
  (`[d.year for d in years]`) shows the `.values_list()` was never intended.
  Recorded as status 500 in the snapshot. Fixing it is a behaviour change and
  needs the snapshot regenerated.

## One deliberate blind spot: Decimal scale

Decimals are compared after `.normalize()`, so `Decimal('7000')` and
`Decimal('7000.00')` count as equal. This is not laziness — the scale of a
summed decimal depends on the *backend*: SQLite's `SUM()` drops it, MySQL's
`SUM(DECIMAL(12,2))` keeps it. Comparing raw representations would fail the
suite here on a difference production does not have.

Any change in **value** is still caught. Only trailing-zero scale is ignored.

## Behaviour worth knowing about before you refactor

`Booking.sales_gst` is `min(invoice_amount * 0.05, gross_profit * 0.18)`. When a
booking makes a loss, `gross_profit` is negative, so the `min()` selects the
negative value and GST comes out **negative**, which then *increases* net profit
via `net_profit = gross_profit - sales_gst`. Booking `B-0004` in the fixture is
exactly this case: gross profit −3800, GST −684, net profit −3116.

This may or may not be intended. It is current behaviour and the snapshot pins
it. Flagging it so an optimisation pass is not blamed for it later.

## Adding coverage

Extend `REPORT_PARAM_SETS` or `BOOKING_LIST_CASES` in `test_golden_master.py`,
then regenerate. More permutations mean a tighter net around the refactor.
