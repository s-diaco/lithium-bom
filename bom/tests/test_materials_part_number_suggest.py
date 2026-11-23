"""Shared part-number + description typeahead and materials-page wiring."""

from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import Client, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from bom import constants
from bom.helpers import (
    create_performance_dataset,
    create_some_fake_parts,
    create_user_and_organization,
    suggest_parts,
)
from bom.models import Organization, Part, PartRevision


User = get_user_model()


@override_settings(BOM_CONFIG=settings.BOM_CONFIG_DEFAULT)
class MaterialsPartNumberSuggestTests(TransactionTestCase):
    def setUp(self):
        self.client = Client()
        self.user, self.organization = create_user_and_organization()
        self.profile = self.user.bom_profile(organization=self.organization)
        self.profile.role = "A"
        self.profile.save()
        self.parts = create_some_fake_parts(organization=self.organization)
        self.url = reverse("bom:part-number-suggest")

    def login(self):
        self.client.force_login(self.user)

    def test_requires_login(self):
        response = self.client.get(self.url, {"q": "200"})
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.url)

    def test_missing_organization_returns_no_suggestions(self):
        self.profile.organization = None
        self.profile.save()
        self.login()
        response = self.client.get(self.url, {"q": "200"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"results": []})

    def test_suggests_labels_with_part_number_values(self):
        self.login()
        target = next(p for p in self.parts if p.full_part_number().startswith("200"))
        pn = target.full_part_number()
        PartRevision.objects.filter(part=target).update(description="Informative description")
        response = self.client.get(self.url, {"q": pn[:3]})
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            {"value": pn, "label": f"{pn} ┆ Informative description"},
            response.json()["results"],
        )

    def test_empty_query_returns_empty_without_catalog_query(self):
        with self.assertNumQueries(0):
            self.assertEqual(suggest_parts(self.organization, "  "), [])
            self.assertEqual(suggest_parts(None, "200"), [])
            self.assertEqual(suggest_parts(self.organization, "200", limit=0), [])
        self.login()
        self.assertEqual(self.client.get(self.url, {"q": ""}).json()["results"], [])

    def test_single_char_query_allowed(self):
        self.login()
        results = self.client.get(self.url, {"q": "2"}).json()["results"]
        self.assertTrue(any("2" in item["value"] for item in results))

    def test_respects_and_clamps_limits(self):
        target = self.parts[0]
        Part.objects.bulk_create([
            Part(
                organization=self.organization,
                number_class=target.number_class,
                number_item=str(8000 + i),
                number_variation="00",
            )
            for i in range(60)
        ])
        self.login()
        query = str(target.number_class.code)
        for requested, expected in [(1, 1), (9999, 50), (0, 1), (-1, 1), ("bad", 15)]:
            with self.subTest(limit=requested):
                response = self.client.get(self.url, {"q": query, "limit": requested})
                self.assertEqual(len(response.json()["results"]), expected)
        with CaptureQueriesContext(connection) as ctx:
            self.assertEqual(len(suggest_parts(self.organization, query, limit=9999)), 50)
        self.assertEqual(len(ctx), 1)
        self.assertIn("LIMIT 50", ctx[0]["sql"])

    def test_org_scoped_even_when_part_numbers_overlap(self):
        other_user = User.objects.create_user("other", "other@example.com", "ghostpassword")
        other_org = Organization.objects.create(
            name="Other Org",
            subscription=constants.SUBSCRIPTION_TYPE_PRO,
            number_scheme=constants.NUMBER_SCHEME_SEMI_INTELLIGENT,
            number_item_len=4,
            number_variation_len=constants.NUMBER_VARIATION_LEN_DEFAULT,
            owner=other_user,
        )
        other_parts = create_some_fake_parts(organization=other_org)
        PartRevision.objects.filter(part__in=other_parts).update(description="PRIVATE_OTHER_ORG")
        self.login()
        response = self.client.get(self.url, {"q": "200"})
        self.assertTrue(response.json()["results"])
        self.assertNotContains(response, "PRIVATE_OTHER_ORG")
        self.assertEqual(
            self.client.get(self.url, {"q": "PRIVATE_OTHER_ORG"}).json()["results"], []
        )

    def test_description_search_and_highest_id_revision_policy(self):
        target = self.parts[0]
        PartRevision.objects.filter(part=target).update(description="Old description")
        PartRevision.objects.create(part=target, revision="Z", description="Old description")
        PartRevision.objects.create(part=target, revision="A", description="New searchable description")
        with self.assertNumQueries(1):
            results = suggest_parts(self.organization, "SEARCHABLE")
        self.assertEqual(results, [{
            "value": target.full_part_number(),
            "label": f"{target.full_part_number()} ┆ New searchable description",
        }])
        self.assertEqual(suggest_parts(self.organization, "Old description"), [])
        self.assertEqual(suggest_parts(self.organization, "STM32"), [])

    def test_exclude_current_part_and_invalid_exclusion(self):
        self.login()
        target = self.parts[0]
        pn = target.full_part_number()
        response = self.client.get(self.url, {"q": pn, "exclude_part_id": target.pk})
        self.assertEqual(response.json()["results"], [])
        response = self.client.get(self.url, {"q": pn, "exclude_part_id": "bad"})
        self.assertIn(pn, [item["value"] for item in response.json()["results"]])

    def test_one_bounded_query_without_revision_resolution_or_bom_walks(self):
        dataset = create_performance_dataset()
        with patch.object(Part, "verbose_str", side_effect=AssertionError("verbose_str")), patch.object(
            Part, "latest", side_effect=AssertionError("latest")
        ), patch.object(PartRevision, "indented", side_effect=AssertionError("BOM traversal")):
            with CaptureQueriesContext(connection) as ctx:
                results = suggest_parts(dataset["organization"], "100", limit=2)
        self.assertEqual(len(results), 2)
        self.assertIn("rev 2", results[0]["label"])
        self.assertEqual(len(ctx), 1)
        self.assertIn("LIMIT 2", ctx[0]["sql"])

    def test_intelligent_part_numbers_and_parts_without_revisions(self):
        self.organization.number_scheme = constants.NUMBER_SCHEME_INTELLIGENT
        self.organization.save()
        target = Part.objects.create(organization=self.organization, number_item="ABC-123")
        with self.assertNumQueries(1):
            self.assertEqual(suggest_parts(self.organization, "abc"), [
                {"value": target.full_part_number(), "label": f"{target.full_part_number()} ┆ "},
            ])

    def test_legacy_materials_route_uses_same_results(self):
        self.login()
        params = {"q": "200"}
        self.assertEqual(
            self.client.get(self.url, params).json(),
            self.client.get(reverse("bom:materials-part-number-suggest"), params).json(),
        )

    def test_materials_page_wires_shared_remote_typeahead(self):
        self.login()
        response = self.client.get(reverse("bom:materials"))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode("utf-8")
        self.assertIn(self.url, html)
        self.assertIn("minLength: 1", html)
        self.assertIn("debounce: 200", html)
        search_script_start = html.index("$('input.autocomplete').autocomplete({")
        search_script = html[search_script_start:search_script_start + 500]
        self.assertIn("source:", search_script)
        self.assertNotIn("data:", search_script)
        self.assertNotIn("JSON.parse", search_script)
        self.assertIn('input.value = `"${val}"`', search_script)

    def test_free_text_search_still_works(self):
        self.login()
        pn = self.parts[0].full_part_number()
        response = self.client.get(reverse("bom:materials"), {"q": pn})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, pn)
