# SPDX-License-Identifier: AGPL-3.0-or-later
"""Display-only phone-number formatting for the public frontend.

Stored values are never touched — submitters can type whatever they like,
and we tidy it up only when rendering. The goals:

  * 10-digit North American numbers     ->  202-555-0100
  * 11-digit North American (leading 1) ->  1-202-555-0100
  * numbers carrying any other country  ->  formatted in that country's
    standard international style via libphonenumber (e.g. +44 20 7946 0958)

Anything we can't confidently parse is returned exactly as entered, so an
unusual or partial number is shown verbatim rather than mangled.
"""
import re


def _hyphenate_nanp(national_digits):
    """Format a 10-digit North American national number as XXX-XXX-XXXX."""
    d = national_digits
    return f"{d[0:3]}-{d[3:6]}-{d[6:]}"


def _format_intl(num):
    """Render a parsed libphonenumber object. NANP (country code 1) gets the
    hyphenated US/Canada style; everything else gets its international form."""
    import phonenumbers
    if num.country_code == 1:
        nat = str(num.national_number)
        if len(nat) == 10:
            return "1-" + _hyphenate_nanp(nat)
    return phonenumbers.format_number(
        num, phonenumbers.PhoneNumberFormat.INTERNATIONAL)


def format_phone(value):
    """Format a stored phone string for public display (see module docstring).
    Returns the input unchanged when it can't be confidently formatted."""
    if not value:
        return value
    s = str(value).strip()
    digits = re.sub(r"\D", "", s)
    if not digits:
        return s
    has_plus = s.lstrip().startswith("+")

    # Explicit international form (+CC …) — defer to libphonenumber.
    if has_plus:
        try:
            import phonenumbers
            num = phonenumbers.parse(s, None)
            if phonenumbers.is_possible_number(num):
                return _format_intl(num)
        except Exception:  # noqa: BLE001
            pass
        return s

    # No leading "+": this audience is overwhelmingly North American, so
    # treat bare 10/11-digit numbers as NANP and hyphenate them.
    if len(digits) == 10:
        return _hyphenate_nanp(digits)
    if len(digits) == 11 and digits[0] == "1":
        return "1-" + _hyphenate_nanp(digits[1:])

    # A longer bare digit string may be an international number typed
    # without the "+". Re-try with one prepended so the country code can
    # still be detected; fall back to the raw text if it doesn't parse.
    try:
        import phonenumbers
        num = phonenumbers.parse("+" + digits, None)
        if phonenumbers.is_valid_number(num):
            return _format_intl(num)
    except Exception:  # noqa: BLE001
        pass
    return s
