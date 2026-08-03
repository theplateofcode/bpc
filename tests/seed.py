"""Deterministic test dataset.

Every value here is fixed -- no randomness, no `timezone.now()` -- so the golden
master snapshot is reproducible on any machine, on any day. The shapes are chosen
to exercise the branches that the financial properties actually care about:

  * cash vs non-cash mode          -> purchase_total / sales_total exclusions
  * international vs domestic      -> tcs_amount
  * sales < purchase               -> the min() branch in sales_gst
  * zero amounts                   -> division/rounding edges
  * a booking with no services     -> empty aggregates returning None
  * several rows of the same type  -> aggregation across rows, not just one
  * approved / pending / discounted payments -> the reports' approval gates
"""
from datetime import date, datetime, timezone as dt_timezone
from decimal import Decimal

from bookings.models import Booking, BookingService, Status
from clients.models import Client
from payments.models import Mode, PaymentReceived
from services.models import (
    Carrier, Hotel, Insurance, Passport, ServiceList, SightSeeing, Ticket,
    Transfer, Visa,
)
from suppliers.models import Supplier
from users.models import User

SERVICE_CODES = [
    "ticket", "visa", "hotel", "insurance", "transfer", "sightseeing", "passport",
]

SERVICE_MODELS = {
    "ticket": Ticket,
    "visa": Visa,
    "hotel": Hotel,
    "insurance": Insurance,
    "transfer": Transfer,
    "sightseeing": SightSeeing,
    "passport": Passport,
}

PACKAGE_CODES = {"hotel", "transfer", "sightseeing"}

FIXED_DT = datetime(2025, 3, 15, 9, 30, tzinfo=dt_timezone.utc)


def D(value):
    return Decimal(str(value))


class Fixture:
    """Container so tests can reach the objects they need by name."""

    def __init__(self):
        self.users = {}
        self.services = {}
        self.suppliers = {}
        self.modes = {}
        self.statuses = {}
        self.clients = []
        self.bookings = []


def _service_row(code, booking, supplier, mode, purchase, sales, creator,
                 travel_type=None):
    model = SERVICE_MODELS[code]
    kwargs = dict(
        booking=booking,
        date=FIXED_DT,
        supplier=supplier,
        mode=mode,
        purchase_amount=D(purchase),
        sales_amount=D(sales),
        created_by=creator,
    )
    if code in PACKAGE_CODES:
        kwargs["travel_type"] = travel_type or "domestic"
    if code == "ticket":
        kwargs["carrier"] = None
    return model.objects.create(**kwargs)


def build():
    """Create the full fixture. Returns a Fixture."""
    f = Fixture()

    # --- reference data -------------------------------------------------
    for name in ("Cash", "Card", "Bank Transfer"):
        f.modes[name] = Mode.objects.create(name=name)

    for name in ("open", "in process", "closed"):
        f.statuses[name] = Status.objects.create(name=name)

    for code in SERVICE_CODES:
        f.services[code] = ServiceList.objects.create(code=code, name=code.title())

    Carrier.objects.create(name="TestAir")

    for code in SERVICE_CODES:
        f.suppliers[code] = Supplier.objects.create(
            name=f"Supplier {code.title()}", category=f.services[code]
        )
    # A second supplier on hotels, so the supplier filter has something to bite on.
    f.suppliers["hotel_alt"] = Supplier.objects.create(
        name="Supplier Hotel Alt", category=f.services["hotel"]
    )

    # --- users ----------------------------------------------------------
    owner = User.objects.create_superuser(
        username="owner", password="x", email="owner@example.com"
    )
    owner.role = "OWNER"
    owner.save()
    f.users["owner"] = owner

    for uname, role in (("staff1", "STAFF"), ("staff2", "STAFF"),
                        ("acct", "ACCOUNTANT"), ("admin1", "ADMIN")):
        u = User.objects.create_user(username=uname, password="x")
        u.role = role
        u.save()
        f.users[uname] = u

    # --- clients --------------------------------------------------------
    for i in range(6):
        f.clients.append(Client.objects.create(
            first_name=f"First{i}",
            last_name=f"Last{i}",
            contact_number=f"90000000{i:02d}",
        ))

    cash = f.modes["Cash"]
    card = f.modes["Card"]
    bank = f.modes["Bank Transfer"]
    staff1, staff2 = f.users["staff1"], f.users["staff2"]

    def new_booking(client, creator, booking_date, status, adults=2, children=0):
        b = Booking.objects.create(
            created_by=creator,
            client=client,
            booking_date=booking_date,
            number_of_adults=adults,
            number_of_children=children,
            status=status,
        )
        f.bookings.append(b)
        return b

    def assign(booking, code, user):
        BookingService.objects.create(
            booking=booking, service=f.services[code], assigned_to=user
        )

    # 1. All services, all non-cash, all international where applicable.
    #    Exercises every branch of purchase_total / sales_total / tcs_amount.
    b1 = new_booking(f.clients[0], staff1, date(2025, 1, 10), f.statuses["closed"])
    for code in SERVICE_CODES:
        assign(b1, code, staff1)
        _service_row(code, b1, f.suppliers[code], card, 1000, 1500, staff1,
                     travel_type="international")

    # 2. Everything cash -> most services excluded from totals, but tickets
    #    are always included. TCS must be zero.
    b2 = new_booking(f.clients[1], staff1, date(2025, 1, 20), f.statuses["closed"])
    for code in SERVICE_CODES:
        assign(b2, code, staff1)
        _service_row(code, b2, f.suppliers[code], cash, 800, 1200, staff1,
                     travel_type="international")

    # 3. Mixed modes, domestic packages -> TCS zero despite non-cash.
    b3 = new_booking(f.clients[2], staff2, date(2025, 2, 5), f.statuses["in process"])
    for i, code in enumerate(SERVICE_CODES):
        assign(b3, code, staff2)
        _service_row(code, b3, f.suppliers[code], cash if i % 2 else bank,
                     500 + i * 100, 700 + i * 150, staff2, travel_type="domestic")

    # 4. Loss-making booking: sales < purchase. gross_profit negative, so
    #    sales_gst takes the min() of a negative and a positive.
    b4 = new_booking(f.clients[3], staff2, date(2025, 2, 18), f.statuses["closed"])
    assign(b4, "ticket", staff2)
    _service_row("ticket", b4, f.suppliers["ticket"], card, 5000, 3200, staff2)
    assign(b4, "hotel", staff2)
    _service_row("hotel", b4, f.suppliers["hotel"], card, 9000, 7000, staff2,
                 travel_type="international")

    # 5. Zero amounts throughout.
    b5 = new_booking(f.clients[4], staff1, date(2025, 3, 1), f.statuses["open"])
    assign(b5, "visa", staff1)
    _service_row("visa", b5, f.suppliers["visa"], card, 0, 0, staff1)

    # 6. Booking with services assigned but NO service rows at all --
    #    every aggregate returns None and must coalesce to 0.
    b6 = new_booking(f.clients[5], staff1, date(2025, 3, 8), f.statuses["open"])
    assign(b6, "hotel", staff1)
    assign(b6, "ticket", staff1)

    # 7. No services assigned and no rows -- all_services_finished() is vacuously true.
    b7 = new_booking(f.clients[0], staff2, date(2025, 3, 12), f.statuses["open"])

    # 8. Multiple rows of the SAME service type, mixed modes within the type.
    b8 = new_booking(f.clients[1], staff1, date(2025, 4, 2), f.statuses["closed"])
    assign(b8, "hotel", staff1)
    _service_row("hotel", b8, f.suppliers["hotel"], card, 1200, 2000, staff1,
                 travel_type="international")
    _service_row("hotel", b8, f.suppliers["hotel_alt"], cash, 900, 1400, staff1,
                 travel_type="international")
    _service_row("hotel", b8, f.suppliers["hotel"], bank, 700, 1100, staff1,
                 travel_type="domestic")
    assign(b8, "ticket", staff1)
    _service_row("ticket", b8, f.suppliers["ticket"], cash, 300, 450, staff1)
    _service_row("ticket", b8, f.suppliers["ticket"], card, 600, 950, staff1)

    # 9. Different year, for the year/month report filters.
    b9 = new_booking(f.clients[2], staff2, date(2024, 11, 22), f.statuses["closed"])
    for code in ("visa", "insurance", "passport"):
        assign(b9, code, staff2)
        _service_row(code, b9, f.suppliers[code], bank, 250, 600, staff2)

    # 10. Fractional amounts -- rounding behaviour must be preserved exactly.
    b10 = new_booking(f.clients[3], staff1, date(2025, 4, 15), f.statuses["closed"])
    assign(b10, "transfer", staff1)
    _service_row("transfer", b10, f.suppliers["transfer"], card,
                 "333.33", "777.77", staff1, travel_type="international")
    assign(b10, "sightseeing", staff1)
    _service_row("sightseeing", b10, f.suppliers["sightseeing"], card,
                 "1111.11", "2222.22", staff1, travel_type="international")

    # --- payments -------------------------------------------------------
    # b1: fully approved across every service -> passes the "fully approved" gate.
    for code in SERVICE_CODES:
        PaymentReceived.objects.create(
            booking=b1, service=f.services[code], mode=card,
            amount=D(1500), received_on=date(2025, 1, 15),
            received_by=f.users["acct"], approved=True,
            approved_by=owner, approved_on=FIXED_DT,
            discount=D(0), is_full=True,
        )

    # b2: cash payments, approved, with a discount recorded.
    for code in SERVICE_CODES:
        PaymentReceived.objects.create(
            booking=b2, service=f.services[code], mode=cash,
            amount=D(1000), received_on=date(2025, 1, 25),
            received_by=f.users["acct"], approved=True,
            approved_by=owner, approved_on=FIXED_DT,
            discount=D(200), is_full=False,
        )

    # b3: one approved, one still pending -> booking must FAIL the gate.
    PaymentReceived.objects.create(
        booking=b3, service=f.services["ticket"], mode=bank,
        amount=D(700), received_on=date(2025, 2, 10),
        received_by=f.users["acct"], approved=True,
        approved_by=owner, approved_on=FIXED_DT,
    )
    PaymentReceived.objects.create(
        booking=b3, service=f.services["visa"], mode=bank,
        amount=D(850), received_on=date(2025, 2, 11),
        received_by=f.users["acct"], approved=False,
    )

    # b8: split payments on one service -> sums across multiple rows.
    for amt, m in ((D(1000), card), (D(800), cash), (D(700), bank)):
        PaymentReceived.objects.create(
            booking=b8, service=f.services["hotel"], mode=m,
            amount=amt, received_on=date(2025, 4, 10),
            received_by=f.users["acct"], approved=True,
            approved_by=owner, approved_on=FIXED_DT,
            discount=D(50),
        )
    PaymentReceived.objects.create(
        booking=b8, service=f.services["ticket"], mode=card,
        amount=D(1400), received_on=date(2025, 4, 11),
        received_by=f.users["acct"], approved=True,
        approved_by=owner, approved_on=FIXED_DT,
    )

    # b9: approved, prior year.
    for code in ("visa", "insurance", "passport"):
        PaymentReceived.objects.create(
            booking=b9, service=f.services[code], mode=bank,
            amount=D(600), received_on=date(2024, 11, 30),
            received_by=f.users["acct"], approved=True,
            approved_by=owner, approved_on=FIXED_DT,
        )

    # b10: approved with fractional amounts.
    for code in ("transfer", "sightseeing"):
        PaymentReceived.objects.create(
            booking=b10, service=f.services[code], mode=card,
            amount=D("777.77") if code == "transfer" else D("2222.22"),
            received_on=date(2025, 4, 20),
            received_by=f.users["acct"], approved=True,
            approved_by=owner, approved_on=FIXED_DT,
        )

    # --- completion flags ------------------------------------------------
    # Vary these so get_service_statuses() and all_services_finished() differ
    # across bookings rather than being uniformly False.
    b1.tickets_finished = True
    b1.visas_finished = True
    b1.hotels_finished = True
    b1.insurances_finished = True
    b1.transfers_finished = True
    b1.sightseeings_finished = True
    b1.passports_finished = True
    b1.accounts_done = True
    b1.save()

    b3.tickets_finished = True
    b3.save()

    b8.hotels_finished = True
    b8.save()

    return f
