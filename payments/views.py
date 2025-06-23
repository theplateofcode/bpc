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
