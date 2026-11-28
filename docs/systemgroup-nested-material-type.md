# SystemGroup Nested Child BoM Material Type Selection

Implemented part-number-based product type inference (Option 3) with interactive per-child selection (Option 1) as the fallback for nested child BoMs imported from SystemGroup.

## Changes

### 1. Part-number inference & nested selection exception (`bom/systemgroup/importer.py`)
- Added `infer_product_type_code_from_part_number`, evaluated in order (first match wins):
  1. Starts with `KR` → Ink (`ink`)
  2. `^[0-9]{4}[A-Z][0-9]{3}$` (4 digits + 1 letter + 3 digits) → Frit (`with_loi`)
  3. `^[A-Z]P[A-Z][0-9]{4}$` (1 letter + `P` + 1 letter + 4 digits) → Powder (`powder`)
  4. `^[A-Z]{3}[0-9]{4}$` (3 letters + 4 digits) → Compound (`no_loi`)
- Updated `import_missing_child_boms` and `run_systemgroup_import` to accept `nested_materials` and `require_nested_material_selection`.
- When `require_nested_material_selection=True` (used by the Admin UI) and an organization has multiple `has_bom=True` product types, any missing nested child whose part number does not match the rules collects into `NestedMaterialSelectionRequired` and rolls back the transaction before any writes are committed. (CLI/non-interactive callers continue to fall back to `first_product_type_code(organization, has_bom=True)` with a warning.)

### 2. Admin UI fallback picker (`bom/views/views.py`, `bom/templates/bom/import-systemgroup-bom.html`)
- `import_systemgroup_bom` catches `NestedMaterialSelectionRequired` and renders `#sg-nested-material-picker` with a `Material Type` dropdown (filtered to `has_bom=True` types) for each unmatched nested child.
- Reuses cached offline uploads from session on re-POST and preserves submitted `nested_materials` across `ExistingBomConflict` prompts.

### 3. Tests (`bom/tests/test_systemgroup_bom_import.py`)
- Added unit and view tests covering rule precedence, automatic nested child material assignment, rollback + override via `NestedMaterialSelectionRequired`, and the UI picker flow.
- Verified with `.venv/bin/python manage.py test bom.tests.test_systemgroup_bom_import --verbosity=1`: 107 tests passed.
