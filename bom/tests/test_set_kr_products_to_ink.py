"""Minimal check for set_kr_products_to_ink management command."""

from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from bom import constants
from bom.helpers import create_user_and_organization
from bom.models import Part, PartRevision, ProductType


class SetKrProductsToInkTests(TestCase):
    def setUp(self):
        # Intelligent scheme: full_part_number() == number_item (e.g. KRBK-1300T).
        self.user, self.organization = create_user_and_organization(
            number_scheme=constants.NUMBER_SCHEME_INTELLIGENT
        )
        self.ink = ProductType.objects.get(
            organization=self.organization, code="ink"
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
        target = self._rev("KRBK-1300T", "with_loi")
        already = self._rev("KRalready", "ink")
        raw_kr = self._rev("KRRAW1", "no_bom")
        no_match = self._rev("CPT1195", "with_loi")
        short = self._rev("K", "with_loi")

        out = StringIO()
        call_command("set_kr_products_to_ink", stdout=out)
        text = out.getvalue()
        self.assertIn("Dry-run", text)
        self.assertIn("would-update: 1", text)
        self.assertIn("already Ink: 1", text)
        self.assertIn("skipped (not a product): 1", text)
        self.assertIn("skipped (PN too short): 1", text)
        target.refresh_from_db()
        self.assertEqual(target.material, "with_loi")

        out = StringIO()
        call_command("set_kr_products_to_ink", "--apply", stdout=out)
        target.refresh_from_db()
        already.refresh_from_db()
        raw_kr.refresh_from_db()
        no_match.refresh_from_db()
        self.assertEqual(target.material, self.ink.code)
        self.assertEqual(already.material, "ink")
        self.assertEqual(raw_kr.material, "no_bom")
        self.assertEqual(no_match.material, "with_loi")
        self.assertEqual(short.material, "with_loi")

        out = StringIO()
        call_command("set_kr_products_to_ink", "--apply", stdout=out)
        self.assertIn("updated: 0", out.getvalue())
        self.assertIn("already Ink: 2", out.getvalue())
