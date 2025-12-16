from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db.models import Sum, Q
from django.http import HttpResponseBadRequest, HttpResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.template.loader import render_to_string

from bookings.models import Booking
from services.models import (
    Hotel,
    Insurance,
    Passport,
    SightSeeing,
    Ticket,
    Transfer,
    Visa,
)
from .forms import ModeOfPaymentForm
from .models import PaymentReceived, Mode


User = get_user_model()
ACCOUNTS_GROUP_NAME = "Accounts"  # change if your group name differs


# =========================
#   ROLE HELPERS
# =========================

def is_owner_or_admin(user):
    return user.is_authenticated and (user.role == "OWNER" or user.role == "ADMIN")


def is_accounts(user):
    # Accounts users are identified by group or superuser
    return user.is_superuser or user.groups.filter(name=ACCOUNTS_GROUP_NAME).exists()


# =========================
#   MODES OF PAYMENT (OWNER/ADMIN)
# =========================

@login_required
@user_passes_test(is_owner_or_admin)
def modes_of_payment(request):
    modes = Mode.objects.all().order_by("name")
    return render(request, "modes_of_payment.html", {"modes": modes})


@login_required
@user_passes_test(is_owner_or_admin)
def create_mode(request):
    if request.method == "POST":
        form = ModeOfPaymentForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect("modes_of_payment")
    else:
        form = ModeOfPaymentForm()
    return render(request, "forms/mode_form.html", {"form": form})


@login_required
@user_passes_test(is_owner_or_admin)
def update_mode(request, pk):
    mode = get_object_or_404(Mode, pk=pk)
    if request.method == "POST":
        form = ModeOfPaymentForm(request.POST, instance=mode)
        if form.is_valid():
            form.save()
            return redirect("modes_of_payment")
    else:
        form = ModeOfPaymentForm(instance=mode)
    return render(request, "forms/mode_form.html", {"form": form})


@login_required
@user_passes_test(is_owner_or_admin)
def delete_mode(request, pk):
    mode = get_object_or_404(Mode, pk=pk)
    if request.method == "POST":
        mode.delete()
        return redirect("modes_of_payment")
    return render(request, "payments/mode_confirm_delete.html", {"mode": mode})


# =========================
#   PAYMENT HELPERS
# =========================

def sales_target_for_booking(booking_id):
    """
    Total sales target for a booking:
    = sum of all services.sales_amount + booking.tcs_amount (property)
    """
    # Get the booking instance so we can use the tcs_amount property
    booking = Booking.objects.get(id=booking_id)

    # Sum all services' sales_amount (same as your original behaviour)
    services_total = 0
    for qs in [
        Hotel.objects.filter(booking_id=booking_id).values_list("sales_amount", flat=True),
        Insurance.objects.filter(booking_id=booking_id).values_list("sales_amount", flat=True),
        Passport.objects.filter(booking_id=booking_id).values_list("sales_amount", flat=True),
        SightSeeing.objects.filter(booking_id=booking_id).values_list("sales_amount", flat=True),
        Ticket.objects.filter(booking_id=booking_id).values_list("sales_amount", flat=True),
        Transfer.objects.filter(booking_id=booking_id).values_list("sales_amount", flat=True),
        Visa.objects.filter(booking_id=booking_id).values_list("sales_amount", flat=True),
    ]:
        services_total += sum(float(x or 0) for x in qs)

    # Use the Python property (not ORM field)
    tcs_amount = float(booking.tcs_amount or 0)

    return services_total + tcs_amount

def payments_received_for_booking(booking_id):
    """Return (approved_sum, pending_sum)."""
    approved = (
        PaymentReceived.objects.filter(booking_id=booking_id, approved=True)
        .aggregate(s=Sum("amount"))["s"]
        or 0
    )
    pending = (
        PaymentReceived.objects.filter(booking_id=booking_id, approved=False)
        .aggregate(s=Sum("amount"))["s"]
        or 0
    )
    return float(approved), float(pending)


def approved_sales_amount_for_booking(booking_id):
    """Sum of approved payment amounts for a booking."""
    return float(
        PaymentReceived.objects.filter(booking_id=booking_id, approved=True)
        .aggregate(s=Sum("amount"))["s"]
        or 0
    )


# =========================
#   EMPLOYEE VIEWS
# =========================

@login_required
def payments_home(request):
    # Employee sees only own bookings that are not closed (status_id != 3)
    qs = (
        Booking.objects.filter(created_by=request.user)
        .exclude(status_id=3)
        .order_by("tour_start_date", "booking_date")
    )

    rows = []
    for b in qs:
        target = sales_target_for_booking(b.id)
        approved, pending = payments_received_for_booking(b.id)
        received_total = approved + pending
        remaining = max(0, target - received_total)

        rows.append(
            {
                "booking": b,
                "target": int(round(target)),
                "approved": int(round(approved)),
                "pending": int(round(pending)),
                "remaining": int(round(remaining)),
            }
        )

    modes = Mode.objects.all().order_by("name")
    return render(request, "payments/home.html", {"rows": rows, "modes": modes})


@login_required
def payment_details_modal(request, booking_id):
    # Only allow the creator to see details
    b = get_object_or_404(Booking, id=booking_id, created_by=request.user)
    items = PaymentReceived.objects.filter(booking=b).order_by("-created_at")
    modes = Mode.objects.all().order_by("name")

    html = render_to_string(
        "payments/_details.html",
        {
            "booking": b,
            "items": items,
            "modes": modes,
        },
        request=request,
    )
    return HttpResponse(html)


@login_required
def payment_add_installment(request, booking_id):
    """
    Add an installment.
    - For HTMX: return refreshed details partial.
    - For normal: redirect to payments_home.
    """
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")

    b = get_object_or_404(Booking, id=booking_id, created_by=request.user)
    amount = request.POST.get("amount")
    mode_id = request.POST.get("mode")
    remarks = request.POST.get("remarks", "")
    doc = request.FILES.get("document")

    try:
        amount_val = float(amount or 0)
        if amount_val <= 0:
            return HttpResponseBadRequest("Amount must be > 0.")
    except ValueError:
        return HttpResponseBadRequest("Invalid amount.")

    mode = get_object_or_404(Mode, id=mode_id)

    PaymentReceived.objects.create(
        booking=b,
        mode=mode,
        amount=amount_val,
        received_by=request.user,
        document=doc,
        remarks=remarks,
        sent_for_approval=True,
        approved=False,
    )

    # HTMX request: return updated details partial
    if request.headers.get("HX-Request"):
        items = PaymentReceived.objects.filter(booking=b).order_by("-created_at")
        modes = Mode.objects.all().order_by("name")
        html = render_to_string(
            "payments/_details.html",
            {
                "booking": b,
                "items": items,
                "modes": modes,
            },
            request=request,
        )
        return HttpResponse(html)

    # Non-HTMX: full redirect
    return redirect("payments_home")


@login_required
def payment_mark_full(request, booking_id):
    """
    Mark a booking as fully received (closing entry).
    Creates a PaymentReceived record with:
    - amount = 0
    - discount = remaining (positive if underpaid, negative if overpaid)
    Then sets booking.status_id = 3 (closed).
    """
    b = get_object_or_404(Booking, id=booking_id, created_by=request.user)

    if request.method != "POST":
        return HttpResponseBadRequest("POST required.")

    # Calculate target and remaining
    target = sales_target_for_booking(b.id)
    approved, pending = payments_received_for_booking(b.id)
    received_total = approved + pending
    remaining = max(0, target - received_total)

    # discount: positive = underpaid, negative = overpaid
    discount = 0
    if remaining > 0:
        discount = remaining
    elif received_total > target:
        # overpaid
        discount = target - received_total  # negative

    PaymentReceived.objects.create(
        booking=b,
        mode=Mode.objects.first(),  # choose default mode logically if needed
        amount=0,  # no money, just closing adjustment
        received_by=request.user,
        remarks="Marked as fully received",
        is_full=True,
        discount=discount,
        sent_for_approval=True,
        approved=False,
    )

    # Close the booking
    b.status_id = 3  # closed
    b.save(update_fields=["status_id"])

    # For HTMX: allow caller to remove the row
    return HttpResponse("")


# =========================
#   ACCOUNTS / APPROVALS
# =========================

@login_required
@user_passes_test(is_accounts)
def payment_approvals(request):
    items = PaymentReceived.objects.filter(
        sent_for_approval=True, approved=False
    ).order_by("created_at")
    return render(request, "payments/accountant_dashboard.html", {"items": items})


@login_required
@user_passes_test(is_accounts)
def payment_approve(request, pk):
    item = get_object_or_404(PaymentReceived, pk=pk)
    item.approve(request.user)

    if request.headers.get("HX-Request"):
        # Frontend can fade out this row by ID
        return HttpResponse(
            '<tr id="payrow-{}" class="flash-approved"></tr>'.format(item.id)
        )

    return redirect("accountant_dashboard")


@login_required
@user_passes_test(is_accounts)
def payment_reject(request, pk):
    item = get_object_or_404(PaymentReceived, pk=pk)
    item.delete()

    # HTMX: just remove the row
    if request.headers.get("HX-Request"):
        return HttpResponse("")

    return redirect("accountant_dashboard")


# =========================
#   _ DASHBOARD
# =========================

@login_required
def accountant_dashboard(request):
    """
    Dashboard for ACCOUNTANT / OWNER / ADMIN.
    Shows all payments with filtering by client, status, and order.
    """
    if request.user.role not in ["ACCOUNTANT", "OWNER", "ADMIN"]:
        # Not authorized for full view
        return render(
            request,
            "payments/accountant_dashboard.html",
            {"payments": [], "client": "", "status": "", "order": "desc"},
        )

    qs = PaymentReceived.objects.select_related(
        "booking", "booking__client", "received_by", "mode"
    ).all()

    # --- Filters ---
    client = request.GET.get("client", "")
    status = request.GET.get("status", "")
    order = request.GET.get("order", "desc")

    if client:
        qs = qs.filter(
            Q(booking__client__first_name__icontains=client)
            | Q(booking__client__last_name__icontains=client)
        )

    if status == "approved":
        qs = qs.filter(approved=True)
    elif status == "pending":
        qs = qs.filter(approved=False)

    if order == "asc":
        qs = qs.order_by("created_at")
    else:
        qs = qs.order_by("-created_at")

    return render(
        request,
        "payments/accountant_dashboard.html",
        {
            "payments": qs,
            "client": client,
            "status": status,
            "order": order,
        },
    )
