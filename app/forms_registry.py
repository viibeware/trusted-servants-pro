# SPDX-License-Identifier: AGPL-3.0-or-later
"""Single-source registry for the public frontend's interactive forms.

Each form has a ``key`` that's used in three places:

  1. The Forms admin page (``/tspro/frontend/forms``) lists every
     entry and links to its settings page.
  2. The Navigation admin lets admins point any nav item / mega-menu
     link at a registered form via a ``form_trigger`` field. When set,
     the rendered <a> on the public site gets a ``data-fe-form-trigger
     ="<key>"`` attribute that the public JS uses to open the matching
     modal instead of navigating.
  3. Each form's modal markup (in ``frontend/_*_modal.html``) carries a
     ``data-fe-form-modal="<key>"`` attribute that the public JS pairs
     with the trigger.

Adding a new form is three changes:

  * add an entry here describing it
  * include its modal partial from ``frontend/base.html`` so it lands
    on every public page
  * register a settings page (route + template) so the Forms admin
    has somewhere to send the admin

Future entries automatically populate the Forms admin list AND the
Navigation builder's "Triggers form" dropdown without any further
plumbing.
"""


def all_forms():
    """Return the list of registered form metadata dicts.

    Wrapped in a function (instead of a module-level constant) so
    callers always see the live state — the next refactor that loads
    form definitions from SiteSetting / a config file / a plugin
    won't have to chase down callers reading a stale tuple.
    """
    return [
        {
            "key": "submission",
            "name": "Submission Form",
            "description": (
                "Lets visitors submit events and announcements for "
                "admin review. Submissions land in a holding tank on "
                "the Announcements & Events admin page; an email goes "
                "to the configured recipients."
            ),
            "icon": "send",
            "settings_endpoint": "main.frontend_form_submission",
            "public_url_endpoint": "frontend.submission_form",
            # Name of the boolean SiteSetting column that gates this
            # form site-wide. The Forms admin index reads + writes
            # this column directly through its inline toggle, so a
            # future form just needs to declare its own column here.
            "enabled_setting": "submission_form_enabled",
        },
        {
            "key": "contact",
            "name": "Contact Form",
            "description": (
                "Public contact-us page at /contact. Visitor messages "
                "email the public information chair (with reply-to set "
                "to the visitor) and persist in the Contact Form admin "
                "section so nothing is lost when the email lands in spam."
            ),
            "icon": "mail",
            "settings_endpoint": "main.frontend_form_contact",
            "public_url_endpoint": "frontend.contact",
            "enabled_setting": "contact_form_enabled",
        },
    ]


def form_by_key(key):
    """Return the registry entry for ``key`` or None when unknown."""
    if not key:
        return None
    for f in all_forms():
        if f["key"] == key:
            return f
    return None


def form_keys():
    """Return the set of valid form keys for validation paths."""
    return {f["key"] for f in all_forms()}
