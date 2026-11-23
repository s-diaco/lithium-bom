"""Minimal check for set_px_products_to_powder management command."""

from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from bom import constants
from bom.helpers import create_user_and_organization
from bom.models import Part, PartRevision, ProductType


class SetPxProductsToPowderTests(TestCase):
    def setUp(self):
        # Intelligent scheme: full_part_number() == number_item (e.g. CPT1195).
        self.user, self.organization = create_user_and_organization(
            number_scheme=constants.NUMBER_SCHEME_INTELLIGENT
        )
        self.powder = ProductType.objects.get(
            organization=self.organization, code="powder"
        )

    def _rev(self, number, material):
        part = Part.objects.create(
            organization=self.organization,
            number_item=number,
        )
        return PartRevision.objects.create(
            part=part,
            revision="1",
            description=number,
            material=material,
        )

    def test_dry_run_then_apply_idempotent(self):
        # CPT… / CXK… → 2nd char P/X; Cxx… is not.
        target_p = self._rev("CPT1195", "with_loi")
        target_x = self._rev("CXK2581", "ink")
        already = self._rev("CPALREADY", "powder")
        raw_px = self._rev("CPRAW1", "no_bom")
        no_match = self._rev("CAT9999", "with_loi")
        short = self._rev("C", "with_loi")

        out = StringIO()
        call_command("set_px_products_to_powder", stdout=out)
        text = out.getvalue()
        self.assertIn("Dry-run", text)
        self.assertIn("would-update: 2", text)
        self.assertIn("already Powder: 1", text)
        self.assertIn("skipped (not a product): 1", text)
        self.assertIn("skipped (PN too short): 1", text)
        target_p.refresh_from_db()
        self.assertEqual(target_p.material, "with_loi")

        out = StringIO()
        call_command("set_px_products_to_powder", "--apply", stdout=out)
        target_p.refresh_from_db()
        target_x.refresh_from_db()
        already.refresh_from_db()
        raw_px.refresh_from_db()
        no_match.refresh_from_db()
        self.assertEqual(target_p.material, self.powder.code)
        self.assertEqual(target_x.material, self.powder.code)
        self.assertEqual(already.material, "powder")
        self.assertEqual(raw_px.material, "no_bom")
        self.assertEqual(no_match.material, "with_loi")
        self.assertEqual(short.material, "with_loi")

        # Idempotent: second apply updates nothing.
        out = StringIO()
        call_command("set_px_products_to_powder", "--apply", stdout=out)
        self.assertIn("updated: 0", out.getvalue())
        self.assertIn("already Powder: 3", out.getvalue())
