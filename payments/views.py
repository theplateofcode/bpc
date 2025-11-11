from django.contrib.auth import get_user_model
# adjust if your Mode class lives elsewhere
from .models import PaymentReceived, Mode
from services.models import Hotel, Insurance, Passport, SightSeeing, Ticket, Transfer, Visa
from bookings.models import Booking
from django.utils import timezone
from django.template.loader import render_to_string
from django.db.models import Sum, Value, CharField
from django.http import HttpResponseBadRequest, HttpResponse, JsonResponse
from django.shortcuts import render, get_object_or_404
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from .models import Mode
from .forms import ModeOfPaymentForm


def is_owner_or_admin(user):
    return user.is_authenticated and (user.role == 'OWNER' or user.role == 'ADMIN')


@login_required
@user_passes_test(is_owner_or_admin)
def modes_of_payment(request):
    modes = Mode.objects.all().order_by('name')
    return render(request, 'modes_of_payment.html', {'modes': modes})


@login_required
@user_passes_test(is_owner_or_admin)
def create_mode(request):
    if request.method == 'POST':
        form = ModeOfPaymentForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('modes_of_payment')
    else:
        form = ModeOfPaymentForm()
    return render(request, 'forms/mode_form.html', {'form': form})


@login_required
@user_passes_test(is_owner_or_admin)
def update_mode(request, pk):
    mode = get_object_or_404(Mode, pk=pk)
    if request.method == 'POST':
        form = ModeOfPaymentForm(request.POST, instance=mode)
        if form.is_valid():
            form.save()
            return redirect('modes_of_payment')
    else:
        form = ModeOfPaymentForm(instance=mode)
    return render(request, 'forms/mode_form.html', {'form': form})


@login_required
@user_passes_test(is_owner_or_admin)
def delete_mode(request, pk):
    mode = get_object_or_404(Mode, pk=pk)
    if request.method == 'POST':
        mode.delete()
        return redirect('modes_of_payment')
    return render(request, 'payments/mode_confirm_delete.html', {'mode': mode})


User = get_user_model()

ACCOUNTS_GROUP_NAME = "Accounts"  # change if your group name differs


def is_accounts(user):
    return user.is_superuser or user.groups.filter(name=ACCOUNTS_GROUP_NAME).exists()

# ---- Helpers ----


def sales_target_for_booking(booking_id):
    """Sum of services.sales_amount for a booking (target goal)."""
    # If you have a booking-level agreed price, swap this to read that field.
    total = 0
    for qs in [
        Hotel.objects.filter(booking_id=booking_id).values_list(
            "sales_amount", flat=True),
        Insurance.objects.filter(booking_id=booking_id).values_list(
            "sales_amount", flat=True),
        Passport.objects.filter(booking_id=booking_id).values_list(
            "sales_amount", flat=True),
        SightSeeing.objects.filter(booking_id=booking_id).values_list(
            "sales_amount", flat=True),
        Ticket.objects.filter(booking_id=booking_id).values_list(
            "sales_amount", flat=True),
        Transfer.objects.filter(booking_id=booking_id).values_list(
            "sales_amount", flat=True),
        Visa.objects.filter(booking_id=booking_id).values_list(
            "sales_amount", flat=True),
    ]:
        total += sum([float(x or 0) for x in qs])
    return total


def payments_received_for_booking(booking_id):
    """Return (approved_sum, pending_sum)."""
    approved = PaymentReceived.objects.filter(
        booking_id=booking_id, approved=True).aggregate(s=Sum("amount"))["s"] or 0
    pending = PaymentReceived.objects.filter(
        booking_id=booking_id, approved=False).aggregate(s=Sum("amount"))["s"] or 0
    return float(approved), float(pending)

# You can reuse this in reports later


def approved_sales_amount_for_booking(booking_id):
    return float(PaymentReceived.objects.filter(booking_id=booking_id, approved=True).aggregate(s=Sum("amount"))["s"] or 0)

# ---- Employee views ----


from django.contrib.auth import get_user_model
from django.db.models import Sum, Value, CharField
from django.http import HttpResponseBadRequest, HttpResponse, JsonResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.template.loader import render_to_string
from django.utils import timezone

from bookings.models import Booking
from services.models import Hotel, Insurance, Passport, SightSeeing, Ticket, Transfer, Visa
from .models import PaymentReceived, Mode

User = get_user_model()
ACCOUNTS_GROUP_NAME = "Accounts"  # change if needed

def is_accounts(user):
    return user.is_superuser or user.groups.filter(name=ACCOUNTS_GROUP_NAME).exists()

# ---------- helpers ----------
def sales_target_for_booking(booking_id):
    total = 0
    for qs in [
        Hotel.objects.filter(booking_id=booking_id).values_list("sales_amount", flat=True),
        Insurance.objects.filter(booking_id=booking_id).values_list("sales_amount", flat=True),
        Passport.objects.filter(booking_id=booking_id).values_list("sales_amount", flat=True),
        SightSeeing.objects.filter(booking_id=booking_id).values_list("sales_amount", flat=True),
        Ticket.objects.filter(booking_id=booking_id).values_list("sales_amount", flat=True),
        Transfer.objects.filter(booking_id=booking_id).values_list("sales_amount", flat=True),
        Visa.objects.filter(booking_id=booking_id).values_list("sales_amount", flat=True),
    ]:
        total += sum(float(x or 0) for x in qs)
    return total

def payments_received_for_booking(booking_id):
    approved = PaymentReceived.objects.filter(booking_id=booking_id, approved=True).aggregate(s=Sum("amount"))["s"] or 0
    pending = PaymentReceived.objects.filter(booking_id=booking_id, approved=False).aggregate(s=Sum("amount"))["s"] or 0
    return float(approved), float(pending)

# ---------- employee views ----------
from django.contrib.auth.decorators import login_required

@login_required
def payments_home(request):
    qs = Booking.objects.filter(
    created_by=request.user).exclude(status_id=3).order_by("tour_start_date", "booking_date")

    rows = []
    for b in qs:
        target = sales_target_for_booking(b.id)
        approved, pending = payments_received_for_booking(b.id)
        received_total = approved + pending
        remaining = max(0, target - received_total)
        rows.append({
            "booking": b,
            "target": int(round(target)),
            "approved": int(round(approved)),
            "pending": int(round(pending)),
            "remaining": int(round(remaining)),
        })
    modes = Mode.objects.all().order_by("name")
    return render(request, "payments/home.html", {"rows": rows, "modes": modes})


@login_required
def payment_details_modal(request, booking_id):
    print("➡️ payment_details_modal called for booking", booking_id)
    b = get_object_or_404(Booking, id=booking_id, created_by=request.user)
    items = PaymentReceived.objects.filter(booking=b).order_by("-created_at")
    modes = Mode.objects.all().order_by("name")
    print("✅ Found booking, items:", len(items))
    html = render_to_string("payments/_details.html", {
        "booking": b,
        "items": items,
        "modes": modes,
    }, request=request)
    return HttpResponse(html)



@login_required
def payment_add_installment(request, booking_id):
    """Add an installment. For HTMX: return refreshed details partial. For normal: redirect to home."""
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

    # HTMX? return refreshed details
    if request.headers.get("HX-Request"):
        items = PaymentReceived.objects.filter(booking=b).order_by("-created_at")
        modes = Mode.objects.all().order_by("name")
        html = render_to_string("payments/_details.html", {
            "booking": b,
            "items": items,
            "modes": modes,
        }, request=request)
        return HttpResponse(html)

    # Non-HTMX: full redirect
    return redirect("payments_home")


@login_required
def payment_mark_full(request, booking_id):
    b = get_object_or_404(Booking, id=booking_id, created_by=request.user)

    if request.method == "POST":
        # Calculate targets
        target = sales_target_for_booking(b.id)
        approved, pending = payments_received_for_booking(b.id)
        received_total = approved + pending
        remaining = max(0, target - received_total)

        # Compute discount: positive = underpaid, negative = overpaid
        discount = 0
        if remaining > 0:
            discount = remaining
        elif remaining < 0:
            discount = remaining  # can be negative

        # Create a closing payment record
        PaymentReceived.objects.create(
            booking=b,
            mode=Mode.objects.first(),  # default mode or choose logically
            amount=0,  # no actual new money, just marking full
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

        # Respond HTMX: remove the row visually
        return HttpResponse("")  # removes the table row
    return HttpResponseBadRequest("POST required.")



@login_required
@user_passes_test(is_accounts)
def payment_approvals(request):
    items = PaymentReceived.objects.filter(
        sent_for_approval=True, approved=False).order_by("created_at")
    return render(request, "payments/approvals.html", {"items": items})


from django.template.loader import render_to_string
from django.http import HttpResponse

@login_required
def payment_approve(request, pk):
    item = get_object_or_404(PaymentReceived, pk=pk)
    item.approve(request.user)

    if request.headers.get("Hx-Request"):
        # Return a simple signal instead of row HTML
        # so that front-end can fade it out
        return HttpResponse('<tr id="payrow-{}" class="flash-approved"></tr>'.format(item.id))

    return redirect("approvals")



@login_required
def payment_reject(request, pk):
    item = get_object_or_404(PaymentReceived, pk=pk)
    item.delete()

    # On reject: return an empty string to remove the row
    if request.headers.get("Hx-Request"):
        return HttpResponse("")

    return redirect("approvals")





from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import render
from .models import PaymentReceived

@login_required
def accountant_dashboard(request):
    # Only allow accountants, owners, admins
    if request.user.role not in ["ACCOUNTANT", "OWNER", "ADMIN"]:
        return render(request, "payments/accountant_dashboard.html", {"payments": []})

    # Base queryset: all received payments with linked booking/client
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

    print("Total payments for accountant:", qs.count())

    return render(request, "payments/accountant_dashboard.html", {
        "payments": qs,
        "client": client,
        "status": status,
        "order": order,
    })
