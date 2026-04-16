from flask import Blueprint, render_template, redirect, url_for, request, flash, session
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import check_password_hash, generate_password_hash
from .models import db, User, ROLES

bp = Blueprint("auth", __name__, url_prefix="/auth")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.index"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            session.permanent = True
            login_user(user, remember=True)
            return redirect(request.args.get("next") or url_for("main.index"))
        flash("Invalid credentials", "danger")
    return render_template("login.html")


@bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))


@bp.route("/users")
@login_required
def users():
    if not current_user.is_admin():
        flash("Admins only", "danger")
        return redirect(url_for("main.index"))
    return render_template("users.html", users=User.query.order_by(User.username).all(), roles=ROLES)


@bp.route("/users/create", methods=["POST"])
@login_required
def users_create():
    if not current_user.is_admin():
        return redirect(url_for("main.index"))
    username = request.form["username"].strip()
    email = request.form["email"].strip()
    password = request.form["password"]
    role = request.form.get("role", "viewer")
    if role not in ROLES:
        role = "viewer"
    if User.query.filter((User.username == username) | (User.email == email)).first():
        flash("Username or email already exists", "danger")
        return redirect(url_for("auth.users", embed=1) if request.form.get("embed") == "1" else url_for("auth.users"))
    u = User(username=username, email=email,
             password_hash=generate_password_hash(password), role=role)
    db.session.add(u)
    db.session.commit()
    flash(f"User {username} created", "success")
    return redirect(url_for("auth.users", embed=1) if request.form.get("embed") == "1" else url_for("auth.users"))


@bp.route("/users/<int:uid>/update", methods=["POST"])
@login_required
def users_update(uid):
    if not current_user.is_admin():
        return redirect(url_for("main.index"))
    u = db.session.get(User, uid)
    if not u:
        flash("User not found", "danger")
        return redirect(url_for("auth.users", embed=1) if request.form.get("embed") == "1" else url_for("auth.users"))
    new_role = request.form.get("role")
    if new_role in ROLES:
        u.role = new_role
    new_pw = request.form.get("password", "").strip()
    if new_pw:
        u.password_hash = generate_password_hash(new_pw)
    db.session.commit()
    flash("User updated", "success")
    return redirect(url_for("auth.users", embed=1) if request.form.get("embed") == "1" else url_for("auth.users"))


@bp.route("/users/<int:uid>/delete", methods=["POST"])
@login_required
def users_delete(uid):
    if not current_user.is_admin():
        return redirect(url_for("main.index"))
    if uid == current_user.id:
        flash("Cannot delete yourself", "danger")
        return redirect(url_for("auth.users", embed=1) if request.form.get("embed") == "1" else url_for("auth.users"))
    u = db.session.get(User, uid)
    if u:
        db.session.delete(u)
        db.session.commit()
        flash("User deleted", "success")
    return redirect(url_for("auth.users", embed=1) if request.form.get("embed") == "1" else url_for("auth.users"))
