from django import forms

from scraper.models import SearchQuery


class SearchQueryForm(forms.ModelForm):
    class Meta:
        model = SearchQuery
        fields = ("query", "country")
        widgets = {
            "query": forms.TextInput(attrs={"placeholder": "Input vacancy title, e.g. Python Developer"}),
            "country": forms.TextInput(attrs={"placeholder": "Input country, e.g. USA"}),
        }
