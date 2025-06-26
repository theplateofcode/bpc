from django.shortcuts import render, redirect, get_object_or_404
from .models import Supplier
from .forms import SupplierForm
from django.contrib.auth.decorators import login_required

@login_required(login_url='/users/login/')
def suppliers(request):
    suppliers = Supplier.objects.select_related('category').all()
    return render(request, 'suppliers.html', {'suppliers': suppliers})

@login_required(login_url='/users/login/')
def create_supplier(request):
    if request.method == 'POST':
        form = SupplierForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('suppliers')
    else:
        form = SupplierForm()
    return render(request, 'forms/create_supplier.html', {'form': form})

@login_required(login_url='/users/login/')
def edit_supplier(request, pk):
    supplier = get_object_or_404(Supplier, pk=pk)
    if request.method == 'POST':
        form = SupplierForm(request.POST, instance=supplier)
        if form.is_valid():
            form.save()
            return redirect('suppliers')
    else:
        form = SupplierForm(instance=supplier)
    return render(request, 'forms/edit_supplier.html', {'form': form, 'supplier': supplier})

@login_required(login_url='/users/login/')
def delete_supplier(request, pk):
    supplier = get_object_or_404(Supplier, pk=pk)
    if request.method == 'POST':
        supplier.delete()
        return redirect('suppliers')
    return render(request, 'forms/delete_supplier.html', {'supplier': supplier})
