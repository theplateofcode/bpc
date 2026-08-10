# Booking Profit Calculator — working rules

## The logic is frozen

The owner has reviewed the calculations against production data and signed them
off. **Optimise, refactor and restructure freely. Never change what the software
computes.**

If a change moves a number, it is a bug in the change — not an improvement —
even when the new number looks more correct.

### Deliberate behaviour. Do not "fix" these.

- **Negative GST on loss-making bookings.** `sales_gst = min(invoice × 5%,
  gross_profit × 18%)`. When gross profit is negative the `min()` picks the
  negative branch, and because `net_profit = gross_profit − sales_gst`, negative
  GST *raises* reported profit. The business asked for negative profit on cash
  and cheque bookings to be allowed.

- **GST comes off non-cash profit only.**
  `profit_non_cash = (sales_non_cash_net − purchase_non_cash) − gst`, with cash
  profit left whole. Both actuals reports do this identically.

- **The bookings list and the reports compute GST differently.** The list caps
  at 5% of invoice; the reports charge a flat 18% of margin. Known, accepted,
  and documented for the client. Unifying them is a business decision, not a
  cleanup task.

- **TCS applies only to hotel / transfer / sightseeing rows that are
  `international` and not cash**, at 2% of sales. It is added to the customer's
  bill and is not revenue.

## How the freeze is enforced

`tests/` holds a golden-master suite: the money properties, the bookings list
across 29 sort/filter permutations, every routed report endpoint, and the
rendered HTML of all 14 service forms.

```bash
python manage.py test tests --settings=main.settings_test_mysql   # before shipping
python manage.py test tests --settings=main.settings_test         # fast, SQLite
```

The snapshots are regenerable, so the suite is only as strong as the discipline
around it:

> **Never regenerate a snapshot to make a failing test pass.** A red golden
> master means the change altered behaviour. Diff it, understand exactly what
> moved, and either fix the change or get the owner's explicit sign-off — then
> regenerate and record what moved and why in the commit message.

## Verify against MySQL

Production is MySQL 8. SQLite is available for speed but is **not** sufficient
on its own — its collation is case-sensitive and its `SUM()` drops decimal
scale. A real money bug once survived four SQLite-green commits because of
exactly this. See `tests/README.md`.

## Deployment

Production tracks the branch named in `.github/workflows/deploy.yml`
(`DEPLOY_BRANCH`), **not `main`**. `main` is intentionally left at the
pre-optimisation commit, so a fresh clone of `main` is not what is running.

## Known-broken by design

Retired reports (the before-payments reports and the legacy reports) are
commented out of the URLconfs, not deleted. Their view code is intact. If you
re-enable one, put its link back in `templates/base.html` too — and note that
Django still reverses `{% url %}` tags inside HTML comments, so a commented-out
link to a missing route will 500 every page in the app.
