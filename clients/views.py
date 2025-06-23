from django.shortcuts import render, redirect, get_object_or_404
from .models import Client
from .forms import ClientForm

def clients(request):
    clients = Client.objects.all()
    return render(request, 'clients.html', {'clients': clients})

def create_client(request):
    if request.method == 'POST':
        form = ClientForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('clients')
    else:
        form = ClientForm()
    return render(request, 'forms/create_client.html', {'form': form})

def edit_client(request, pk):
    client = get_object_or_404(Client, pk=pk)
    if request.method == 'POST':
        form = ClientForm(request.POST, instance=client)
        if form.is_valid():
            form.save()
            return redirect('clients')
    else:
        form = ClientForm(instance=client)
    return render(request, 'forms/edit_client.html', {'form': form, 'client': client})

def delete_client(request, pk):
    client = get_object_or_404(Client, pk=pk)
    if request.method == 'POST':
        client.delete()
        return redirect('clients')
    return render(request, 'forms/delete_client.html', {'client': client})


from django.http import JsonResponse
from .models import Client
import json

def client_autocomplete(request):
    q = request.GET.get("q", "")
    results = []
    if q:
        qs = Client.objects.filter(
            first_name__icontains=q
        ) | Client.objects.filter(
            last_name__icontains=q
        ) | Client.objects.filter(
            contact_number__icontains=q
        )
        qs = qs.distinct()[:10]
        for client in qs:
            results.append({
                "id": client.id,
                "first_name": client.first_name,
                "middle_name": client.middle_name,
                "last_name": client.last_name,
                "contact_number": client.contact_number,
            })
    return JsonResponse({"results": results})

from django.views.decorators.csrf import csrf_exempt
@csrf_exempt
def create_client_ajax(request):
    if request.method == "POST":
        data = json.loads(request.body)
        if not data.get("first_name") or not data.get("last_name") or not data.get("contact_number"):
            return JsonResponse({"success": False, "error": "All fields required."})
        client = Client.objects.create(
            first_name=data["first_name"],
            middle_name=data.get("middle_name", ""),
            last_name=data["last_name"],
            contact_number=data["contact_number"],
        )
        return JsonResponse({"success": True, "client": {
            "id": client.id,
            "first_name": client.first_name,
            "middle_name": client.middle_name,
            "last_name": client.last_name,
            "contact_number": client.contact_number,
        }})
    return JsonResponse({"success": False, "error": "Invalid request."})
