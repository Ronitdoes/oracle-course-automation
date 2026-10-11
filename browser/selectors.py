"""Shared page-control lookups (one place so every part uses the same one).

Both the page reader and the clicker must find the *same* on-screen choice
for a given choice number, so the lookups live here.
Listed in page order; repeats are removed automatically.
"""

RADIO = "input[type='radio'], [role='radio']"
RADIO_IN_MAIN = "main input[type='radio'], main [role='radio'], input[type='radio'], [role='radio']"
# Multi-answer controls (Oracle APEX uses checkboxes or ARIA checkbox divs).
# CHOICE covers every selectable option element for both extraction and action.
# :visible keeps positional numbers stable: hidden questions from other quiz
# stages must never shift number N onto the wrong control.
CHECKBOX = "input[type='checkbox'], [role='checkbox']"
CHOICE = ("main input[type='radio']:visible, main [role='radio']:visible, "
          "main input[type='checkbox']:visible, main [role='checkbox']:visible, "
          "input[type='radio']:visible, [role='radio']:visible, "
          "input[type='checkbox']:visible, [role='checkbox']:visible")
TEXT_FIELD = "input[type='text'], input:not([type]), textarea, [role='textbox']"
SUBMIT = "[data-submit], button[type='submit']"

# Other wordings for the submit step. The planner asks for "Submit"; real
# sites word it "Submit Answer", "Complete Assessment", "Finish", ... Only
# used when the exact name is missing, and only for the submit click itself -
# never for other clicks.
SUBMIT_SYNONYMS = (
    "Submit Answer",
    "Submit Test",
    "Submit Assessment",
    "Complete Assessment",
    "Finish Assessment",
    "Finish",
)
