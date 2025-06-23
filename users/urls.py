from django.urls import path
from . import views
from django.contrib.auth import views as auth_views
from .views import users_list, edit_user, delete_user

urlpatterns = [
    # Login
    path('login/', views.login_view, name='login'),

    # Signup
    path('signup/', views.signup_view, name='signup'),

    # Logout (optional)
    path('logout/', views.logout_view, name='logout'),

    # Forgot password (request reset link)
    path('forgot-password/', views.forgot_password_view, name='forgot_password'),

    path('users/', users_list, name='users'),
    path('users/<int:user_id>/edit/', edit_user, name='edit_user'),
    path('users/<int:user_id>/delete/', delete_user, name='delete_user'),

    # Password reset confirmation (Django built-in)
    path('reset/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(
        template_name='users/reset-password.html'
    ), name='password_reset_confirm'),

    # Password reset done (Django built-in)
    path('reset/done/', auth_views.PasswordResetCompleteView.as_view(
        template_name='users/reset-done.html'
    ), name='password_reset_complete'),

    # Password reset sent (Django built-in)
    path('password-reset/done/', auth_views.PasswordResetDoneView.as_view(
        template_name='users/reset-sent.html'
    ), name='password_reset_done'),
]
