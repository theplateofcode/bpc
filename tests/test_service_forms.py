"""Rendered-HTML snapshot for the seven service create/edit/delete forms.

The golden master covers the reports and the bookings list, but nothing covered
these fourteen form templates -- which is a problem, because they are the most
duplicated files in the project and therefore the ones most worth merging.

This pins what they render so a merge can be shown not to change the output.
Whitespace runs are collapsed before comparing: indentation moves around when
templates are combined, and it changes nothing a browser sees. Any difference
in tags, attributes, field names or text still fails.

    python manage.py test tests --settings=main.settings_test
    UPDATE_GOLDEN=1 python manage.py test tests --settings=main.settings_test
"""
import json
import os
import re
from pathlib import Path

from django.contrib.auth.models import Group
from django.test import Client as HttpClient, TestCase

from services.models import (
    Hotel, Insurance, Passport, SightSeeing, Ticket, Transfer, Visa,
)

from . import seed

SNAPSHOT_PATH = Path(__file__).parent / "service_forms.json"

# service key -> (url name for create, url name for edit, model, related name)
SERVICES = {
    "ticket": ("create_ticket", "edit_ticket", Ticket, "tickets"),
    "passport": ("create_passport", "edit_passport", Passport, "passports"),
    "visa": ("create_visa", "edit_visa", Visa, "visas"),
    "insurance": ("create_insurance", "edit_insurance", Insurance, "insurances"),
    "hotel": ("create_hotel", "edit_hotel", Hotel, "hotels"),
    "sightseeing": ("create_sightseeing", "edit_sightseeing", SightSeeing, "sightseeings"),
    "transfer": ("create_transfer", "edit_transfer", Transfer, "transfers"),
}

# CSRF tokens and form ids are regenerated per request; blanking them keeps the
# snapshot stable without hiding anything structural.
VOLATILE = [
    (re.compile(r'name="csrfmiddlewaretoken" value="[^"]*"'),
     'name="csrfmiddlewaretoken" value="CSRF"'),
    (re.compile(r'value="[0-9a-fA-F]{32,}"'), 'value="HEX"'),
]


def normalise(html):
    for pattern, replacement in VOLATILE:
        html = pattern.sub(replacement, html)
    # Drop HTML comments. The old templates labelled the same field
    # "<!-- Date -->", "<!-- Date Field -->" and
    # "<!-- Date (rendered by Django form) -->"; none of it reaches a user, and
    # keeping it would block merging files that render identically.
    html = re.sub(r"<!--.*?-->", "", html, flags=re.S)
    # Collapse whitespace runs and tidy space before a closing bracket: merging
    # templates moves indentation around, and no browser cares. Tag, attribute
    # and text changes still show up.
    html = re.sub(r"\s+", " ", html)
    html = re.sub(r">\s+<", "><", html)
    html = re.sub(r"\s+(/?)>", r"\1>", html)
    return html.strip()


class ServiceFormTemplateTests(TestCase):
    """Pin the rendered output of every service form template."""

    @classmethod
    def setUpTestData(cls):
        cls.fixture = seed.build()
        # The views are gated by group_required(...); a superuser passes every
        # gate, which keeps this focused on the templates rather than on auth.
        for name in ("Ticket_Dept", "Passport_Dept", "Visa_Dept", "Insurance_Dept",
                     "Hotel_Dept", "Sightseeing_Dept", "Transfer_Dept"):
            Group.objects.get_or_create(name=name)

    def setUp(self):
        self.http = HttpClient(raise_request_exception=False)
        self.http.force_login(self.fixture.users["owner"])

    def build_snapshot(self):
        from django.urls import reverse

        # Booking 1 in the fixture has a row in all seven service tables.
        booking = self.fixture.bookings[0]
        snapshot = {}

        for key, (create_name, edit_name, model, related) in SERVICES.items():
            create_url = reverse(create_name, args=[booking.id])
            response = self.http.get(create_url)
            snapshot[f"{key}.create"] = {
                "status": response.status_code,
                "html": normalise(response.content.decode()) if response.status_code == 200 else "",
            }

            row = getattr(booking, related).order_by("id").first()
            self.assertIsNotNone(row, f"fixture has no {key} row to edit")
            edit_url = reverse(edit_name, args=[row.id])
            response = self.http.get(edit_url)
            snapshot[f"{key}.edit"] = {
                "status": response.status_code,
                "html": normalise(response.content.decode()) if response.status_code == 200 else "",
            }

        return snapshot

    def test_service_forms_match_snapshot(self):
        current = self.build_snapshot()

        if os.environ.get("UPDATE_GOLDEN") or not SNAPSHOT_PATH.exists():
            SNAPSHOT_PATH.write_text(
                json.dumps(current, indent=2, sort_keys=True), encoding="utf-8"
            )
            self.skipTest(f"Snapshot written to {SNAPSHOT_PATH.name} -- rerun to compare.")

        expected = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))

        self.assertEqual(
            sorted(expected), sorted(current),
            "the set of rendered forms changed",
        )
        for key in sorted(expected):
            with self.subTest(form=key):
                self.assertEqual(
                    expected[key]["status"], current[key]["status"],
                    f"{key} status changed",
                )
                self.assertEqual(
                    expected[key]["html"], current[key]["html"],
                    f"{key} rendered differently",
                )
