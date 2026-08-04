# Golden master test suite

This suite exists for one reason: to let the app be optimised **without changing
what it computes**. It records the current output of the financial logic and the
report endpoints, and fails if any of it moves.

## Running

Against MySQL, which is what production uses. **Run this one before deploying.**

```bash
python manage.py test tests --settings=main.settings_test_mysql
```

Against SQLite, for fast iteration with no server:

```bash
python manage.py test tests --settings=main.settings_test
```

Both settings modules are committed. The snapshots are generated on MySQL and
pass unchanged on SQLite — if that ever stops being true, something backend-
dependent has crept in and is worth understanding before it ships.

### Why MySQL matters, concretely

SQLite is not a substitute here. A real bug survived four commits of
SQLite-green testing:

> `purchase_total` excluded cash rows with `.exclude(mode__name='Cash')`. When
> that was rewritten to sum prefetched rows in Python it became
> `row.mode.name == 'Cash'`. MySQL's default collation
> (`utf8mb4_0900_ai_ci`) compares case-insensitively, so the original query
> also excluded a mode named `CASH` — the Python version did not, and every
> total on such a booking came out wrong. SQLite compares case-sensitively and
> happily agreed with the broken version.

`test_cash_rule.py` now runs the original query chain beside the property and
asserts they still agree. Its case-variant tests skip on SQLite, because there
the comparison cannot fail.

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

## Test files

| File | Covers |
|---|---|
| `test_golden_master.py` | Money properties, bookings list, 19 report endpoints |
| `test_service_forms.py` | Rendered HTML of the 14 service create/edit forms |
| `test_legacy_filters.py` | Regression tests for the two legacy filter endpoints |
| `test_cash_rule.py` | The rewritten totals still match the ORM query they replaced |

## Two things the fixture pins deliberately

**Primary keys.** `seed.py` assigns explicit ids. Two of them reach rendered
output — `Client.client_id` formats its pk as `C-0004`, and `Booking.save()`
derives `B-0004` from the last row's pk — so letting the database allocate them
made the snapshots backend-dependent. InnoDB in particular does not roll its
`AUTO_INCREMENT` counter back between test classes, so ids drifted as the suite
ran.

**Row order.** Several report querysets had no `ORDER BY`, so their row order
was whatever index the planner chose. That is not merely a test problem: adding
the performance indexes changed which index MySQL picked, which would have
quietly reshuffled the rows in the owner's booking report. Those querysets now
order by `id` explicitly.

## Fixed since the baseline was first taken

Both were pinned as bugs originally, then fixed deliberately. The snapshots were
regenerated afterwards, and in each case the diff was checked to confirm nothing
else moved.

- **Legacy filter endpoints returned HTTP 500 on every call.**
  `reports/views_legacy.py` and `core/views_legacy.py` both chained
  `.values_list("year", flat=True)` onto `.dates("booking_date", "year")`, which
  already yields `date` objects — `FieldError`. The following line
  (`[d.year for d in years]`) was always the intended conversion. Now covered by
  `test_legacy_filters.py`, which seeds real legacy bookings so an empty
  response cannot pass. Regenerating changed exactly seven snapshot entries
  from 500 to 200 and nothing else.

- **Every service edit page opened with its date blank.** All seven form
  widgets rendered `<input type="date">` with `format='%d-%m-%Y'` (Hotel had
  `'%d-%m-%y'`). A date input only accepts `YYYY-MM-DD`, so browsers rejected
  the value and showed an empty box. Saving still worked, because a date input
  always posts `YYYY-MM-DD` regardless — which is why this went unnoticed.
  Fixed in `services/forms.py` via the shared `ServiceDateInput`.

## One deliberate blind spot: Decimal scale

Decimals are compared after `.normalize()`, so `Decimal('7000')` and
`Decimal('7000.00')` count as equal. This is not laziness — the scale of a
summed decimal depends on the *backend*: SQLite's `SUM()` drops it, MySQL's
`SUM(DECIMAL(12,2))` keeps it. Comparing raw representations would fail the
suite here on a difference production does not have.

Any change in **value** is still caught. Only trailing-zero scale is ignored.

## Negative GST on loss-making bookings is INTENDED — do not "fix" it

`Booking.sales_gst` is `min(invoice_amount * 0.05, gross_profit * 0.18)`. When a
booking makes a loss, `gross_profit` is negative, so the `min()` selects the
negative value and GST comes out **negative**, which then *increases* net profit
via `net_profit = gross_profit - sales_gst`. Booking `B-0004` in the fixture is
exactly this case: gross profit −3800, GST −684, net profit −3116.

**This is a business rule, confirmed by the owner: negative profit on cash and
cheque bookings is allowed and was specifically requested.** It looks like a
defect on first reading, which is why it is written down here. Leave it alone.

For scale, on a production snapshot of 1,077 bookings, 5 had negative gross
profit and carried −₹5,213 of GST between them.

## Adding coverage

Extend `REPORT_PARAM_SETS` or `BOOKING_LIST_CASES` in `test_golden_master.py`,
then regenerate. More permutations mean a tighter net around the refactor.
