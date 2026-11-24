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

Contact and retention were filled in by the student on 2026-11-25 (they
replaced the earlier bracketed placeholders). The contact is the address
the student chose to give; an earlier note here suggested a university
address instead.
"""

PRIVACY_NOTICE_CONTROLLER = {
    # Controller line, exactly as decided by the student. If the
    # supervisor says the university may not be named, edit this one
    # string.
    "controller_line": (
        "Jakin Kipkorir, final-year BBIT project, Strathmore University "
        "School of Computing and Engineering Sciences"
    ),
    "contact": "jakin.kipkorir@gmail.com",
    "retention": "6 months after results are published",
}
