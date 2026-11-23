"""One-time: set product material to Powder when PN's 2nd char is P or X.

Rule: if Part.full_part_number()[1] is P or X (case-insensitive), e.g.
CPT1195 / CXK2581, set that revision's PartRevision.material to the org's
ProductType named "Powder" (code typically ``powder``).

Scope: products only (PartRevision.is_product). Does not create ProductType.

Dry-run by default; pass --apply to write.

Examples:
  python manage.py set_px_products_to_powder
  python manage.py set_px_products_to_powder --apply
  docker compose --env-file .env.prod exec -T web \\
    python manage.py set_px_products_to_powder
  docker compose --env-file .env.prod exec -T web \\
    python manage.py set_px_products_to_powder --apply
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from bom.models import Organization, PartRevision, ProductType


POWDER_NAME = "Powder"


def powder_types_by_org_id():
    """Map organization_id -> ProductType for name Powder (or code powder)."""
    qs = ProductType.objects.filter(
        Q(name__iexact=POWDER_NAME) | Q(code__iexact="powder")
    ).select_related("organization")
    by_org = {}
    for pt in qs:
        # Prefer exact name match if both somehow exist.
        existing = by_org.get(pt.organization_id)
        if existing is None or (
            pt.name.lower() == POWDER_NAME.lower()
            and existing.name.lower() != POWDER_NAME.lower()
        ):
            by_org[pt.organization_id] = pt
    return by_org


def second_char_is_p_or_x(part_number: str) -> bool:
    if len(part_number) < 2:
        return False
    return part_number[1].upper() in ("P", "X")


class Command(BaseCommand):
    help = (
        "Set PartRevision.material to Powder for product revisions whose "
        "part number has P or X as the second character. Dry-run by default; "
        "use --apply to write. Does not create a Powder ProductType."
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

        powder_by_org = powder_types_by_org_id()
        missing_powder = [o for o in orgs if o.pk not in powder_by_org]
        if missing_powder:
            names = ", ".join(f"{o.pk}:{o.name}" for o in missing_powder)
            self.stdout.write(
                self.style.WARNING(
                    f"No ProductType named '{POWDER_NAME}' (or code powder) "
                    f"for org(s): {names}. Matching parts in those orgs "
                    f"will be skipped (type not created)."
                )
            )
        if not powder_by_org and org_id is not None:
            raise CommandError(
                f"Organization id={org_id} has no ProductType named "
                f"'{POWDER_NAME}' (or code powder). Refusing to invent one."
            )
        if not powder_by_org and not Organization.objects.exists():
            raise CommandError("No organizations in database.")

        rev_qs = PartRevision.objects.select_related(
            "part__organization", "part__number_class"
        )
        if org_id is not None:
            rev_qs = rev_qs.filter(part__organization_id=org_id)

        matched = 0
        already_powder = 0
        to_update = []
        skipped_no_powder = 0
        skipped_not_product = 0
        skipped_pn_too_short = 0

        for rev in rev_qs.iterator(chunk_size=500):
            pn = rev.part.full_part_number() or ""
            if len(pn) < 2:
                skipped_pn_too_short += 1
                continue
            if not second_char_is_p_or_x(pn):
                continue

            matched += 1
            if not rev.is_product:
                skipped_not_product += 1
                continue

            powder = powder_by_org.get(rev.part.organization_id)
            if powder is None:
                skipped_no_powder += 1
                continue

            if rev.material == powder.code:
                already_powder += 1
                continue

            to_update.append((rev, powder.code, pn, rev.material))

        would_or_did = "updated" if apply else "would-update"
        self.stdout.write(f"matched (2nd char P/X): {matched}")
        self.stdout.write(f"already Powder: {already_powder}")
        self.stdout.write(f"{would_or_did}: {len(to_update)}")
        self.stdout.write(f"skipped (not a product): {skipped_not_product}")
        self.stdout.write(f"skipped (no Powder type): {skipped_no_powder}")
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
            self.style.SUCCESS(f"Updated PartRevision.material -> Powder: {len(to_update)}")
        )
