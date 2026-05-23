# SPDX-License-Identifier: AGPL-3.0-or-later
"""Product marketing site + demo entry flow.

Registered (and its ``/`` gate installed) only when ``TSP_DEMO_MODE`` is on —
see :func:`register`. Routing model:

  * ``/``             → the TSP Pro product marketing homepage (always).
  * ``/welcome``      → the same marketing page (stable alias).
  * ``/demo``         → enters the live demo: renders the fellowship homepage.
                        The first hit provisions the visitor's private session.
  * ``/demo/login-admin`` → one-click sign-in as the demo admin → ``/tspro``.
  * ``/demo/reset``   → wipe this session's private DB + uploads, back to ``/demo``.

The live demo keeps the app's real URLs (``/meetings``, ``/library``, ``/tspro``,
``/pub/…``) so all existing links and admin JS keep working; only the front door
moved. The frontend header's brand link falls back to ``/demo`` via the
``home_url`` Jinja global (set in demo.install) so "home" stays inside the demo.
"""
from datetime import datetime

from flask import Blueprint, render_template, redirect, request
from flask_login import login_user

from . import demo as _demo
from .models import User

bp = Blueprint("product", __name__)


def _landing():
    return render_template("product/landing.html", year=datetime.utcnow().year)


@bp.route("/welcome")
def welcome():
    """The product marketing page (stable alias of ``/``)."""
    return _landing()


@bp.route("/demo")
def demo_home():
    """Front door to the live demo — the fellowship homepage. The demo
    before_request provisions this visitor's private session on first hit."""
    from .frontend import index as _frontend_index
    return _frontend_index()


@bp.route("/demo/login-admin")
def login_admin():
    """One-click sign-in as the seeded demo admin → straight to the backend."""
    u = User.query.filter_by(username="admin").first()
    if u is not None and not getattr(u, "disabled", False):
        login_user(u)
    return redirect("/tspro")


@bp.route("/demo/reset")
def reset():
    """Wipe this session's private DB + uploads and start fresh from golden."""
    _demo.reset_session()
    return redirect("/demo")


def _splash():
    """The product marketing page owns ``/`` in demo mode."""
    if request.method == "GET" and request.path == "/":
        return _landing()
    return None


def register(app):
    app.register_blueprint(bp)
    app.before_request(_splash)
    from . import docs as _docs
    _docs.register(app)
    from . import feature_request as _fr
    _fr.register(app)
