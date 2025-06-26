from django.contrib.auth import authenticate, login, logout, get_user_model
from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth.forms import PasswordResetForm
from django.contrib.auth.views import PasswordResetView
from django.urls import reverse_lazy

User = get_user_model()

# LOGIN VIEW
def login_view(request):
    if request.user.is_authenticated:
        return redirect('home')  # Change 'home' to your landing page

    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            return redirect('home')  # Change 'home' to your landing page
        else:
            messages.error(request, "Invalid username or password.")

    return render(request, 'login.html')

def signup_view(request):
    if request.user.is_authenticated:
        return redirect('home')

    if request.method == 'POST':
        username = request.POST.get('username')
        email = request.POST.get('email')
        first_name = request.POST.get('first_name')
        last_name = request.POST.get('last_name')
        password1 = request.POST.get('password1')
        password2 = request.POST.get('password2')

        if password1 != password2:
            messages.error(request, "Passwords do not match.")
        elif User.objects.filter(username=username).exists():
            messages.error(request, "Username already exists.")
        elif User.objects.filter(email=email).exists():
            messages.error(request, "Email already exists.")
        else:
            user = User.objects.create_user(
                username=username,
                email=email,
                password=password1,
                first_name=first_name,
                last_name=last_name
            )
            user.is_active = True
            user.save()
            login(request, user)
            return redirect('home')
    return render(request, 'signup.html')

# LOGOUT VIEW
def logout_view(request):
    logout(request)
    return redirect('login')

# FORGOT PASSWORD VIEW (uses Django's PasswordResetForm)
def forgot_password_view(request):
    if request.method == 'POST':
        email = request.POST.get('email')
        form = PasswordResetForm({'email': email})
        if form.is_valid():
            # form.save(
            #     request=request,
            #     use_https=request.is_secure(),
            #     email_template_name='users/password_reset_email.html',
            #     subject_template_name='users/password_reset_subject.txt',
            #     from_email=None,
            #     html_email_template_name=None,
            #     extra_email_context=None,
            # )
            messages.success(request, "A password reset link has been sent to your email.")
            return redirect('login')
        else:
            messages.error(request, "Invalid email address.")
    return render(request, 'forgot-password.html')

# Optionally, you can subclass Django's PasswordResetView for more control:
# class CustomPasswordResetView(PasswordResetView):
#     template_name = 'users/forgot-password.html'
#     success_url = reverse_lazy('login')
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.shortcuts import render
from bookings.models import Booking

User = get_user_model()

from django.contrib.auth.decorators import login_required

@login_required(login_url='/users/login/')
def users_list(request):
    users = User.objects.all().prefetch_related('groups')
    user_data = []
    for user in users:
        user_data.append({
            'id': user.id,  # Add this line
            'username': user.username,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'groups': ', '.join([g.name for g in user.groups.all()]),
            'entries': Booking.objects.filter(created_by=user).count(),
        })
    return render(request, 'users_list.html', {'user_data': user_data})


# views.py
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test

User = get_user_model()

def is_owner_or_superuser(user):
    return user.is_superuser or getattr(user, 'role', '') == 'Owner'


@login_required(login_url='/users/login/')
@user_passes_test(is_owner_or_superuser)
def edit_user(request, user_id):
    user = get_object_or_404(User, id=user_id)
    groups = Group.objects.all()
    if request.method == "POST":
        # Update role
        user.role = request.POST.get('role')
        # Update groups
        group_ids = request.POST.getlist('groups')
        user.groups.set(Group.objects.filter(id__in=group_ids))
        user.save()
        messages.success(request, "User roles updated.")
        return redirect('users')
    return render(request, 'forms/edit_user.html', {
        'user_obj': user,
        'all_groups': groups,
        'role_choices': User.ROLE_CHOICES,
    })
from django.db.models import ProtectedError

from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import user_passes_test
from django.shortcuts import get_object_or_404, redirect
from django.contrib import messages
from django.db.models import ProtectedError
from django.core.exceptions import PermissionDenied


@login_required(login_url='/users/login/')
@user_passes_test(is_owner_or_superuser)
@require_POST  # Ensure only POST requests are accepted
def delete_user(request, user_id):
    user = get_object_or_404(User, id=user_id)
    
    try:
        # Validate permissions
        if user.is_superuser:
            raise PermissionDenied("Cannot delete superusers.")
        if user == request.user:
            raise PermissionDenied("Cannot delete your own account.")
        
        # Attempt deletion
        user.delete()
        messages.success(request, f"User {user.username} deleted successfully.")
    
    except ProtectedError as e:
        # Handle protected relations (e.g., Hotel.created_by)
        protected_objects = [str(obj) for obj in e.protected_objects]
        messages.error(request, 
            f"Cannot delete user. Related items must be deleted first: {', '.join(protected_objects)}")
    
    except PermissionDenied as e:
        messages.error(request, str(e))
    
    except Exception as e:
        # Generic error fallback
        messages.error(request, f"Deletion failed: {str(e)}")
    
    return redirect('users')

