"""One-time: set product material to Ink when PN starts with KR.

Rule: if Part.full_part_number() starts with ``KR`` (case-insensitive), e.g.
KRBK-1300T, set that revision's PartRevision.material to the org's
ProductType named "Ink" (code typically ``ink``).

Scope: products only (PartRevision.is_product). Does not create ProductType.

Dry-run by default; pass --apply to write.

Examples:
  python manage.py set_kr_products_to_ink
  python manage.py set_kr_products_to_ink --apply
  docker compose --env-file .env.prod exec -T web \\
    python manage.py set_kr_products_to_ink
  docker compose --env-file .env.prod exec -T web \\
    python manage.py set_kr_products_to_ink --apply
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from bom.models import Organization, PartRevision, ProductType


INK_NAME = "Ink"
PN_PREFIX = "KR"


def ink_types_by_org_id():
    """Map organization_id -> ProductType for name Ink (or code ink)."""
    qs = ProductType.objects.filter(
        Q(name__iexact=INK_NAME) | Q(code__iexact="ink")
    ).select_related("organization")
    by_org = {}
    for pt in qs:
        existing = by_org.get(pt.organization_id)
        if existing is None or (
            pt.name.lower() == INK_NAME.lower()
            and existing.name.lower() != INK_NAME.lower()
        ):
            by_org[pt.organization_id] = pt
    return by_org


def pn_starts_with_kr(part_number: str) -> bool:
    return part_number.upper().startswith(PN_PREFIX)


class Command(BaseCommand):
    help = (
        "Set PartRevision.material to Ink for product revisions whose "
        "part number starts with KR. Dry-run by default; use --apply to "
        "write. Does not create an Ink ProductType."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Actually update material (default is dry-run).",
        )
        parser.add_argument(
            "--organization-id",
            type=int,
            default=None,
            help="Limit to one Organization primary key (optional).",
        )

    def handle(self, *args, **options):
        apply = options["apply"]
        org_id = options["organization_id"]

        orgs = Organization.objects.all()
        if org_id is not None:
            orgs = orgs.filter(pk=org_id)
            if not orgs.exists():
                raise CommandError(f"Organization id={org_id} not found.")

        ink_by_org = ink_types_by_org_id()
        missing_ink = [o for o in orgs if o.pk not in ink_by_org]
        if missing_ink:
            names = ", ".join(f"{o.pk}:{o.name}" for o in missing_ink)
            self.stdout.write(
                self.style.WARNING(
                    f"No ProductType named '{INK_NAME}' (or code ink) "
                    f"for org(s): {names}. Matching parts in those orgs "
                    f"will be skipped (type not created)."
                )
            )
        if not ink_by_org and org_id is not None:
            raise CommandError(
                f"Organization id={org_id} has no ProductType named "
                f"'{INK_NAME}' (or code ink). Refusing to invent one."
            )
        if not ink_by_org and not Organization.objects.exists():
            raise CommandError("No organizations in database.")

        rev_qs = PartRevision.objects.select_related(
            "part__organization", "part__number_class"
        )
        if org_id is not None:
            rev_qs = rev_qs.filter(part__organization_id=org_id)

        matched = 0
        already_ink = 0
        to_update = []
        skipped_no_ink = 0
        skipped_not_product = 0
        skipped_pn_too_short = 0

        for rev in rev_qs.iterator(chunk_size=500):
            pn = rev.part.full_part_number() or ""
            if len(pn) < len(PN_PREFIX):
                skipped_pn_too_short += 1
                continue
            if not pn_starts_with_kr(pn):
                continue

            matched += 1
            if not rev.is_product:
                skipped_not_product += 1
                continue

            ink = ink_by_org.get(rev.part.organization_id)
            if ink is None:
                skipped_no_ink += 1
                continue

            if rev.material == ink.code:
                already_ink += 1
                continue

            to_update.append((rev, ink.code, pn, rev.material))

        would_or_did = "updated" if apply else "would-update"
        self.stdout.write(f"matched (PN starts with KR): {matched}")
        self.stdout.write(f"already Ink: {already_ink}")
        self.stdout.write(f"{would_or_did}: {len(to_update)}")
        self.stdout.write(f"skipped (not a product): {skipped_not_product}")
        self.stdout.write(f"skipped (no Ink type): {skipped_no_ink}")
        self.stdout.write(f"skipped (PN too short): {skipped_pn_too_short}")

        for rev, code, pn, old in to_update[:50]:
            self.stdout.write(
                f"  {'UPDATE' if apply else 'WOULD'} "
                f"rev={rev.pk} pn={pn!r} material {old!r} -> {code!r}"
            )
        if len(to_update) > 50:
            self.stdout.write(f"  ... and {len(to_update) - 50} more")

        if not apply:
            self.stdout.write(
                self.style.WARNING("Dry-run only. Re-run with --apply to write.")
            )
            return

        for rev, code, _pn, _old in to_update:
            rev.material = code
            rev.save()

        self.stdout.write(
            self.style.SUCCESS(f"Updated PartRevision.material -> Ink: {len(to_update)}")
        )
