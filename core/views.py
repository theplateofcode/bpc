from django.shortcuts import render
from django.contrib.auth import authenticate, login, logout, get_user_model
from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth.forms import PasswordResetForm
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import user_passes_test, login_required
from django.contrib.auth.models import Group
from django.shortcuts import render, redirect, get_object_or_404
# from django.contrib.auth.views import PasswordResetView
# from django.urls import reverse_lazy


# Create your views here.
def home(request):
    return render(request, 'home.html')

def clients(request):
    return render(request, 'clients.html')


User = get_user_model()  # Add this line

@login_required
@user_passes_test(lambda u: u.is_superuser or u.is_staff)
def manage_groups(request):
    groups = Group.objects.all().order_by('name')
    users = User.objects.all().order_by('username')  # Now uses your custom user model

    if request.method == "POST":
        group_id = request.POST.get('group_id')
        user_ids = request.POST.getlist('users')
        group = get_object_or_404(Group, id=group_id)
        group.user_set.set(User.objects.filter(id__in=user_ids))
        return redirect('manage_groups')

    return render(request, 'manage_groups.html', {
        'groups': groups,
        'users': users,
    })


