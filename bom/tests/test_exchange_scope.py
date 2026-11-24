"""Manual FX reads must be bounded, non-mutating, and calculation-local."""

from decimal import Decimal

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from djmoney.contrib.exchange.models import ExchangeBackend
from djmoney.money import Money

from bom.exchange import (
    RATE_KIND_CUSTOMS,
    convert_to_org_currency,
    exchange_rate_scope,
    get_manual_backend,
    get_org_per_unit_rate,
    set_org_per_unit_rate,
)


class ExchangeRateScopeTests(TestCase):
    def setUp(self):
        set_org_per_unit_rate("USD", "IRR", "42000")
        set_org_per_unit_rate("USD", "IRR", "28000", kind=RATE_KIND_CUSTOMS)

    def test_established_backend_reads_do_not_write_or_change_timestamp(self):
        backend = get_manual_backend("IRR")
        last_update = backend.last_update
        with CaptureQueriesContext(connection) as queries:
            self.assertEqual(convert_to_org_currency(Money(2, "USD"), "IRR"), Money(84000, "IRR"))
        self.assertTrue(all(q["sql"].lstrip().upper().startswith("SELECT") for q in queries))
        backend.refresh_from_db()
        self.assertEqual(backend.last_update, last_update)
        self.assertFalse(any("UPDATE" in q["sql"] for q in queries))

    def test_backend_currency_change_is_saved(self):
        backend = get_manual_backend("EUR")
        backend.refresh_from_db()
        self.assertEqual(backend.base_currency, "EUR")

    def test_bulk_reads_and_nested_scopes_share_two_queries_per_kind(self):
        with CaptureQueriesContext(connection) as queries, exchange_rate_scope():
            for _ in range(20):
                with exchange_rate_scope():
                    self.assertEqual(get_org_per_unit_rate("USD", "IRR"), Decimal("42000"))
                    self.assertEqual(get_org_per_unit_rate("USD", "IRR", kind=RATE_KIND_CUSTOMS), Decimal("28000"))
                    self.assertIsNone(get_org_per_unit_rate("EUR", "IRR"))
        self.assertEqual(len(queries), 4)  # backend + all rates, for each kind

    def test_later_scope_observes_rate_edit_and_missing_rate_creation(self):
        with exchange_rate_scope():
            self.assertEqual(get_org_per_unit_rate("USD", "IRR"), Decimal("42000"))
            self.assertIsNone(get_org_per_unit_rate("EUR", "IRR"))
        set_org_per_unit_rate("USD", "IRR", "50000")
        set_org_per_unit_rate("EUR", "IRR", "60000")
        with exchange_rate_scope():
            self.assertEqual(get_org_per_unit_rate("USD", "IRR"), Decimal("50000"))
            self.assertEqual(get_org_per_unit_rate("EUR", "IRR"), Decimal("60000"))

    def test_edits_and_deletions_invalidate_active_scope(self):
        with exchange_rate_scope():
            self.assertEqual(get_org_per_unit_rate("USD", "IRR"), Decimal("42000"))
            set_org_per_unit_rate("USD", "IRR", "50000")
            self.assertEqual(get_org_per_unit_rate("USD", "IRR"), Decimal("50000"))
            set_org_per_unit_rate("USD", "IRR", None)
            self.assertIsNone(get_org_per_unit_rate("USD", "IRR"))

    def test_exception_resets_scope(self):
        with self.assertRaises(RuntimeError), exchange_rate_scope():
            self.assertEqual(get_org_per_unit_rate("USD", "IRR"), Decimal("42000"))
            raise RuntimeError("abort calculation")
        set_org_per_unit_rate("USD", "IRR", "50000")
        with self.assertNumQueries(2):
            self.assertEqual(get_org_per_unit_rate("USD", "IRR"), Decimal("50000"))

    def test_same_currency_needs_no_backend_or_rate_queries(self):
        with self.assertNumQueries(0), exchange_rate_scope():
            self.assertEqual(convert_to_org_currency(Money(2, "IRR"), "IRR"), Money(2, "IRR"))

    def test_scope_separates_base_currencies(self):
        with exchange_rate_scope():
            get_org_per_unit_rate("USD", "IRR")
            get_org_per_unit_rate("USD", "EUR")
        self.assertEqual(ExchangeBackend.objects.get(name="manual").base_currency, "EUR")
