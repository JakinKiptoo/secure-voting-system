"""
FR-DPA-01 (EXTENSIONS_ROADMAP.md): the ONE place the privacy notice's
controller, contact and retention wording lives.

Everything the student may need to change -- the controller line (the
student is confirming with the supervisor whether the university may be
named), the contact address, the retention period -- is in the single
dict below. voters/views.py::privacy_notice_view passes this dict to
templates/voters/privacy_notice.html as `controller`, and the template
reads every one of these values from it; none of them is written
anywhere else in the codebase. Change a value here and the page
changes, nothing else to edit.

PLACEHOLDERS (visible on the page until replaced -- both are wrapped in
square brackets on purpose so they cannot be mistaken for real values):
  - contact:   the student's UNIVERSITY email address, to be filled in.
               Do not put a personal email address here.
  - retention: the retention period, to be confirmed by the project team.
"""

PRIVACY_NOTICE_CONTROLLER = {
    # Controller line, exactly as decided by the student. If the
    # supervisor says the university may not be named, edit this one
    # string.
    "controller_line": (
        "Jakin Kipkorir, final-year BBIT project, Strathmore University "
        "School of Computing and Engineering Sciences"
    ),
    # PLACEHOLDER -- replace with the university email address.
    "contact": "[UNIVERSITY EMAIL: to be filled in by the student]",
    # PLACEHOLDER -- replace once the project team has confirmed it.
    "retention": "[TO BE CONFIRMED BY THE PROJECT TEAM]",
}
