from urllib.parse import urlencode

from django import forms
from django.urls import reverse


class PartAutocompleteTextInput(forms.TextInput):
    """Shared remote part picker: descriptive labels, part-number values."""

    def __init__(self, *args, limit=15, submit=False, exclude_part_id=None, **kwargs):
        self.limit = limit
        self.submit = submit
        self.exclude_part_id = exclude_part_id
        super().__init__(*args, **kwargs)

    def render(self, name, value, attrs=None, renderer=None):
        params = {"limit": self.limit}
        if self.exclude_part_id is not None:
            params["exclude_part_id"] = self.exclude_part_id
        attrs = {
            **(attrs or {}),
            "autocomplete": "off",
            "data-part-autocomplete": reverse("bom:part-number-suggest")
            + "?"
            + urlencode(params),
            "data-autocomplete-limit": self.limit,
            "data-autocomplete-submit": "true" if self.submit else "false",
        }
        return super().render(name, value, attrs, renderer)
