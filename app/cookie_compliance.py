# SPDX-License-Identifier: AGPL-3.0-or-later
"""Cookie & privacy compliance — region inference, region-aware presets,
and one-click starter policy generators.

Three concerns:

1. **Region inference** — peek at common CDN country headers
   (``CF-IPCountry``, ``X-Country-Code``, etc.) and fall back to
   ``Accept-Language`` to pick a recommended consent mode per visitor.
   The admin's chosen ``cookie_compliance_mode`` is the floor;
   auto-region can only escalate to a stricter mode (so an admin who
   picked "notice" still sees GDPR-strict prompts surfaced to EU
   visitors when auto-region is on).

2. **Region presets** — a per-jurisdiction bundle of recommended
   settings (mode + banner copy) that an admin can apply with a
   single click. Encodes prevailing best practice as of 2026 for
   the most common regulatory regimes (GDPR/UK GDPR, CCPA/CPRA,
   PIPEDA, LGPD, generic). Not legal advice — these are sensible
   defaults the admin should still tailor.

3. **Starter policy templates** — pre-canned Page block JSON the
   admin can drop into a new Page to seed a privacy policy.
   Generic placeholders the admin then customises with their
   actual contact / hosting / cookies info.

Privacy: no IP, UA, or country code is persisted by this module.
Region detection runs per-request from request headers, never stored.
"""
from datetime import datetime
import json
import uuid

# ──────────────────────────────────────────────────────────────────────
# Region inference
# ──────────────────────────────────────────────────────────────────────

# ISO-3166-1 alpha-2 country codes that fall under GDPR / UK GDPR.
# Source: EU member states + EEA (Iceland, Liechtenstein, Norway) + UK.
_GDPR_COUNTRIES = frozenset({
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR",
    "DE", "GR", "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL",
    "PL", "PT", "RO", "SK", "SI", "ES", "SE",
    # EEA
    "IS", "LI", "NO",
    # UK (post-Brexit UK GDPR is functionally equivalent)
    "GB",
})

# Language tags that signal an EU/UK locale even when no country header
# is present. Conservative — overlapping languages spoken outside the
# EU (e.g. English, French, Spanish, Portuguese, German) require the
# country header to escalate. The list below is languages that are
# *near-exclusively* spoken in GDPR countries.
_GDPR_LANGUAGES = frozenset({
    "bg", "cs", "da", "et", "fi", "el", "hr", "hu", "is", "lv",
    "lt", "mt", "nl", "no", "pl", "ro", "sk", "sl", "sv",
})

# California, where CCPA / CPRA applies. (Country-level we treat US as
# "consent" since the strictest US state requirements de facto apply
# to any operator targeting US visitors.) Other US-state regimes
# (Colorado, Virginia, Utah, Connecticut) are CCPA-equivalent or
# weaker, so the "consent" preset covers them too.
_CCPA_REGION_HEADERS = ("US-CA", "USA-CA")

_MODE_PRIORITY = {"off": 0, "notice": 1, "consent": 2, "strict": 3}


def _strongest(a, b):
    """Return whichever of two modes is more restrictive."""
    return a if _MODE_PRIORITY.get(a, 0) >= _MODE_PRIORITY.get(b, 0) else b


def _country_from_headers(headers):
    """Try common CDN / proxy headers for an ISO-3166-1 alpha-2 country
    code. None when nothing matched. Header names are case-insensitive
    in Flask's request.headers (Werkzeug EnvironHeaders), but be
    explicit anyway. Order matters: Cloudflare wins because it's the
    most common CDN this app ships behind."""
    for name in ("CF-IPCountry",        # Cloudflare
                 "X-Country-Code",      # Generic / Fastly default
                 "X-Geo-Country",       # Some proxies
                 "X-Vercel-IP-Country", # Vercel
                 "Fastly-Geo-Country"): # Fastly explicit
        v = (headers.get(name) or "").strip().upper()
        if v and len(v) <= 3 and v != "XX":
            return v
    return None


def _primary_language(accept_language):
    """Return the primary language tag (e.g. 'de' from
    'de-DE,de;q=0.9,en;q=0.7') or None."""
    if not accept_language:
        return None
    primary = accept_language.split(",", 1)[0].strip().lower()
    if not primary:
        return None
    # Strip subtag (de-DE → de)
    return primary.split("-", 1)[0].split(";", 1)[0]


def infer_visitor_mode(headers, configured_mode="notice"):
    """Given request.headers + the admin's configured baseline mode,
    return the mode that should actually drive the banner for this
    visitor. Never relaxes — only escalates."""
    country = _country_from_headers(headers)
    inferred = configured_mode
    if country in _GDPR_COUNTRIES:
        inferred = "strict"
    elif country and country.startswith("US"):
        # Country-only US header → CCPA-equivalent consent.
        inferred = _strongest(inferred, "consent")
    # Specific region headers like "US-CA" for CCPA states.
    region = (headers.get("X-Region-Code") or "").strip().upper()
    if region in _CCPA_REGION_HEADERS:
        inferred = _strongest(inferred, "consent")
    if inferred == configured_mode:
        # No header gave us a strong signal — try Accept-Language.
        lang = _primary_language(headers.get("Accept-Language"))
        if lang in _GDPR_LANGUAGES:
            inferred = _strongest(inferred, "strict")
    return _strongest(inferred, configured_mode)


# ──────────────────────────────────────────────────────────────────────
# Region presets
# ──────────────────────────────────────────────────────────────────────

# Each preset = a dict of column values an admin can apply with one
# click on the admin page. Copy is intentionally plain-spoken — most
# studies find legalese banners reduce comprehension AND consent rate.
REGION_PRESETS = {
    "gdpr": {
        "label": "GDPR / UK GDPR (EU + United Kingdom)",
        "description": (
            "Strict opt-in: non-essential cookies are blocked until the visitor "
            "explicitly accepts. Both Accept and Reject are equally prominent — "
            "GDPR requires the choice to be genuinely free."
        ),
        "settings": {
            "cookie_compliance_mode": "strict",
            "cookie_compliance_auto_region": True,
            "cookie_compliance_title": "We respect your privacy",
            "cookie_compliance_body": (
                "We use cookies to make this site work and, with your permission, "
                "to understand how it's used. You can accept all cookies, reject "
                "the non-essential ones, or read our privacy policy first. You "
                "can change your mind at any time."
            ),
            "cookie_compliance_accept_label": "Accept all",
            "cookie_compliance_reject_label": "Reject non-essential",
            "cookie_compliance_more_label": "Privacy policy",
            "cookie_compliance_position": "bottom-bar",
        },
    },
    "ccpa": {
        "label": "CCPA / CPRA (California, USA)",
        "description": (
            "Opt-in with a clear reject path. Mirrors CCPA/CPRA's \"Do Not Sell "
            "or Share My Personal Information\" expectations: visitors can use "
            "the site freely either way, and rejecting is one click."
        ),
        "settings": {
            "cookie_compliance_mode": "consent",
            "cookie_compliance_auto_region": True,
            "cookie_compliance_title": "Your privacy choices",
            "cookie_compliance_body": (
                "We use cookies for essential site features and, optionally, to "
                "improve the site. Accept or reject non-essential cookies — "
                "either way, the site works."
            ),
            "cookie_compliance_accept_label": "Accept",
            "cookie_compliance_reject_label": "Do not share / sell",
            "cookie_compliance_more_label": "Your privacy rights",
            "cookie_compliance_position": "bottom-bar",
        },
    },
    "generic": {
        "label": "Generic notice (global / lowest-overhead)",
        "description": (
            "Informational only — a brief banner that the visitor can dismiss. "
            "Suitable when you don't collect personal data beyond what's needed "
            "to operate the site and you don't run third-party analytics or ads."
        ),
        "settings": {
            "cookie_compliance_mode": "notice",
            "cookie_compliance_auto_region": True,
            "cookie_compliance_title": "We use cookies",
            "cookie_compliance_body": (
                "This site uses cookies only to keep you signed in and remember "
                "your preferences. We don't use tracking or advertising cookies."
            ),
            "cookie_compliance_accept_label": "OK",
            "cookie_compliance_reject_label": "",
            "cookie_compliance_more_label": "Privacy policy",
            "cookie_compliance_position": "bottom-bar",
        },
    },
}


def get_preset(key):
    """Look up a region preset by key. Raises KeyError for unknown keys
    so the route can 400 instead of silently no-opping."""
    return REGION_PRESETS[key]


# ──────────────────────────────────────────────────────────────────────
# Starter privacy policy templates
# ──────────────────────────────────────────────────────────────────────

def _block(t, **data):
    """Build one block in the schema the page editor + _blocks.html
    macros expect: ``{id, type, data}``. Each id is a fresh uuid so
    the editor can address rows individually after generation."""
    return {"id": uuid.uuid4().hex[:12], "type": t, "data": data}


def _md(text):
    """Convenience: a paragraph block carrying Markdown body text."""
    return _block("paragraph", md=text)


def _h(text, level=2):
    """Convenience: a heading block."""
    return _block("heading", text=text, level=level)


def _build_policy_blocks(intro_paragraphs, sections):
    """Compose a one-section Page body from an intro paragraph list +
    a list of `(heading, [markdown, ...])` sections. Returns the
    JSON-serialisable structure that goes into Page.blocks_json."""
    blocks = []
    for p in intro_paragraphs:
        blocks.append(_md(p))
    for heading, paragraphs in sections:
        blocks.append(_h(heading, level=2))
        for p in paragraphs:
            blocks.append(_md(p))
    return [{"id": uuid.uuid4().hex[:12], "title": "", "blocks": blocks}]


# Each template returns: (page_title, page_slug_seed, page_blocks).
# Admins can rename the page after generation — slug_seed is just a
# starting point.

def _policy_gdpr(site_name):
    name = site_name or "this site"
    blocks = _build_policy_blocks(
        intro_paragraphs=[
            f"This policy explains what data {name} collects when you visit, "
            "why we collect it, how long we keep it, and the rights you have "
            "over your data under the **General Data Protection Regulation "
            "(GDPR)** and the **UK GDPR**.",
            f"_Last updated: {datetime.utcnow().strftime('%B %Y')}. "
            "Please review this draft and replace any placeholder text "
            "(in **bold italics**) with details specific to your operation._",
        ],
        sections=[
            ("Who we are", [
                f"{name} is operated by ***[Your organisation name]***, "
                "based in ***[country]***. You can reach the person "
                "responsible for data protection at ***[contact email]***.",
            ]),
            ("What we collect", [
                "**Essential cookies** — a session cookie so signed-in admins "
                "stay signed in, and a one-year `tsp_cookie_consent` cookie "
                "remembering your choice on this banner. These are required "
                "for the site to function and don't track you.",
                "**Aggregate visit metrics** — when you load a public page we "
                "record the path you viewed, a coarse browser/device family, "
                "and a daily-rotating one-way hash of your IP + browser used "
                "to approximate unique-visitor counts. The hash rotates at "
                "midnight UTC so it can't be linked back to you across days. "
                "We don't store your IP address or User-Agent string.",
                "**Form submissions** — when you submit a contact form, "
                "story, or similar, we store what you typed plus your IP "
                "and browser at submission time for abuse protection. "
                "We retain submissions for ***[retention period — typically "
                "12 months]*** unless you ask us to delete them sooner.",
            ]),
            ("Why we collect it", [
                "We collect the above on the basis of **legitimate interest** "
                "(operating the site and protecting it from abuse) and, where "
                "you've consented via the cookie banner, your **explicit "
                "consent**. You can withdraw consent at any time by clearing "
                "the `tsp_cookie_consent` cookie in your browser.",
            ]),
            ("Your rights", [
                "Under GDPR you have the right to: access the personal data "
                "we hold about you; request correction or deletion; object "
                "to processing; restrict processing; and request portability. "
                "You also have the right to lodge a complaint with your "
                "national supervisory authority.",
                "To exercise any of these rights, email ***[contact email]***. "
                "We'll respond within 30 days.",
            ]),
            ("Who we share it with", [
                "We don't sell your data. We share it only with: our hosting "
                "provider (***[provider name]***), and any sub-processor "
                "you can see listed at ***[sub-processor URL or N/A]***. "
                "All sub-processors are bound by GDPR-equivalent contracts.",
            ]),
            ("Cookies in detail", [
                "| Cookie | Purpose | Lifetime |",
                "|---|---|---|",
                "| `session` | Keeps signed-in admins signed in | Session |",
                "| `tsp_cookie_consent` | Remembers your choice on this banner | 1 year |",
                "| ***[any analytics cookie if you add one]*** | ***[purpose]*** | ***[lifetime]*** |",
            ]),
            ("Changes to this policy", [
                "We'll update the date at the top whenever the policy "
                "changes. Material changes (new categories of data, new "
                "sub-processors) will re-prompt the banner so you can "
                "review your choice.",
            ]),
        ],
    )
    return "Privacy Policy", "privacy-policy", blocks


def _policy_ccpa(site_name):
    name = site_name or "this site"
    blocks = _build_policy_blocks(
        intro_paragraphs=[
            f"This notice explains what personal information {name} collects "
            "from California residents, how we use it, and your rights under "
            "the **California Consumer Privacy Act (CCPA)** and the "
            "**California Privacy Rights Act (CPRA)**.",
            f"_Last updated: {datetime.utcnow().strftime('%B %Y')}. "
            "Please replace placeholder text (in **bold italics**) with "
            "details specific to your operation._",
        ],
        sections=[
            ("Categories of information we collect", [
                "**Identifiers** — when you submit a form, your name, email, "
                "and any other fields you fill in. Plus the IP address you "
                "submitted from (for abuse protection only — never sold).",
                "**Internet activity** — coarse aggregate visit metrics "
                "(pages viewed, browser family, device class). Tied only to "
                "a daily-rotating one-way hash that resets every midnight UTC.",
            ]),
            ("How we use it", [
                "Operating the site, responding to your messages, protecting "
                "against abuse, and understanding aggregate traffic patterns.",
                "We **do not sell or share** your personal information for "
                "cross-context behavioural advertising. If that ever changes "
                "we'll update this notice and re-prompt the cookie banner.",
            ]),
            ("Your rights as a California resident", [
                "You have the right to: **know** what we've collected about "
                "you; **delete** what we've collected; **correct** "
                "inaccurate information; and **opt out** of any sale or "
                "sharing. To exercise any of these, email "
                "***[contact email]***. We'll respond within 45 days.",
                "You can also designate an authorised agent to act on your "
                "behalf — we'll require proof of authorisation.",
            ]),
            ("Retention", [
                "Form submissions are kept for ***[retention period — "
                "typically 12 months]***. Aggregate metrics are kept for "
                "***[retention period — typically 24 months]***. After that "
                "they're permanently deleted.",
            ]),
            ("Changes to this notice", [
                "We'll update the date at the top whenever this notice "
                "changes. Material changes will re-prompt the cookie "
                "banner so you can review your choice.",
            ]),
        ],
    )
    return "Privacy Notice", "privacy-notice", blocks


def _policy_generic(site_name):
    name = site_name or "this site"
    blocks = _build_policy_blocks(
        intro_paragraphs=[
            f"This page explains what data {name} collects when you visit "
            "and what we do with it.",
            f"_Last updated: {datetime.utcnow().strftime('%B %Y')}. "
            "Please replace placeholder text (in **bold italics**) with "
            "details specific to your operation._",
        ],
        sections=[
            ("What we collect", [
                "Just what's needed to run the site: a session cookie for "
                "signed-in administrators, your choice on the cookie "
                "banner, and aggregate page-view counts (no IP or browser "
                "string stored — we use a daily-rotating one-way hash).",
                "If you submit a form, we keep what you typed plus your IP "
                "at submission time for abuse protection.",
            ]),
            ("What we don't do", [
                "We don't run third-party advertising or tracking, we don't "
                "share your data with marketers, and we don't build "
                "profiles on you across sessions.",
            ]),
            ("Contact us", [
                "Questions about this page? Email ***[contact email]***.",
            ]),
        ],
    )
    return "Privacy Policy", "privacy-policy", blocks


# Map of template key → (generator function, label).
POLICY_TEMPLATES = {
    "gdpr": (_policy_gdpr, "GDPR / UK GDPR starter"),
    "ccpa": (_policy_ccpa, "CCPA / CPRA starter"),
    "generic": (_policy_generic, "Generic / minimal starter"),
}


def generate_policy(key, site_name=None):
    """Build a starter policy. Returns (title, slug_seed, blocks_json_str).
    Slug uniqueness is the caller's responsibility — the admin route
    appends an integer suffix when the seed slug is already taken."""
    fn, _label = POLICY_TEMPLATES[key]
    title, slug_seed, blocks = fn(site_name)
    return title, slug_seed, json.dumps(blocks, ensure_ascii=False)
