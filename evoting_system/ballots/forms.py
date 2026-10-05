from django import forms

from elections.models import Candidate


class BallotForm(forms.Form):
    """Candidate selection for the currently open election."""

    candidate = forms.ModelChoiceField(
        queryset=Candidate.objects.none(),
        widget=forms.RadioSelect,
        empty_label=None,
    )

    def __init__(self, *args, election=None, **kwargs):
        super().__init__(*args, **kwargs)
        if election is not None:
            self.fields["candidate"].queryset = election.candidates.all()
