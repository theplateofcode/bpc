from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User

@admin.register(User)
class CustomUserAdmin(UserAdmin):
    # Add groups/permissions to fieldsets
    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        ('Personal Info', {'fields': ('first_name', 'last_name', 'email')}),
        ('Permissions', {
            'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions'),
        }),
        ('Custom Fields', {'fields': ('role', 'service_category')}),
        ('Important Dates', {'fields': ('last_login', 'date_joined')}),
    )
    
    # For add user page
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('username', 'password1', 'password2', 'role', 'service_category'),
        }),
    )
    
    # List display and filtering
    list_display = ['username', 'email', 'role', 'is_active', 'is_superuser']
    list_filter = ['role', 'is_active', 'is_superuser', 'groups']
    
    # Enable horizontal filter widget for groups
    filter_horizontal = ('groups', 'user_permissions',)
