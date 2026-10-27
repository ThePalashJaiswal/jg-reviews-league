"""Login, password hashing and first-run admin bootstrap."""
from __future__ import annotations

import os
import secrets
import time

import bcrypt
import streamlit as st

import db


def secret(key: str, default: str = "") -> str:
    try:
        return st.secrets.get(key, "") or os.environ.get(key, default)
    except Exception:  # no secrets.toml locally
        return os.environ.get(key, default)


def hash_pw(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()


def check_pw(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode(), hashed.encode())
    except ValueError:
        return False


def new_password() -> str:
    # readable one-time password, e.g. "kite-4821-mango"
    words = ["amber", "cedar", "delta", "ember", "falcon", "harbor", "indigo", "jasper", "kite", "lotus",
             "mango", "nova", "orbit", "pearl", "quartz", "river", "saffron", "tiger", "umber", "violet"]
    return f"{secrets.choice(words)}-{secrets.randbelow(9000) + 1000}-{secrets.choice(words)}"


def bootstrap_admin() -> None:
    """Create the first admin from secrets, once. No admin, no universal default password."""
    if db.count_admins() > 0:
        return
    u, p = secret("ADMIN_USERNAME"), secret("ADMIN_PASSWORD")
    if not u or not p or len(p) < 10:
        st.error("First run: set ADMIN_USERNAME and ADMIN_PASSWORD (10+ characters) in the app's secrets, then reload.")
        st.stop()
    db.create_user("system", u, hash_pw(p), "admin", None, must_change=True)


def login_screen() -> None:
    st.markdown("<div class='jg-brand'>JG Reviews League</div>", unsafe_allow_html=True)
    st.caption("Judiciary Gold · Google review streaks across seven centres")
    tries = st.session_state.get("tries", 0)
    wait = st.session_state.get("locked_until", 0) - time.time()
    with st.form("login", clear_on_submit=False):
        u = st.text_input("Username")
        p = st.text_input("Password", type="password")
        go = st.form_submit_button("Sign in", type="primary", width="stretch")
    if go:
        if wait > 0:
            st.error(f"Too many attempts. Try again in {int(wait)} seconds.")
            return
        user = db.get_user(u)
        if user and user["active"] and check_pw(p, user["password_hash"]):
            st.session_state.update(user=user, tries=0)
            st.rerun()
        st.session_state["tries"] = tries + 1
        if tries + 1 >= 5:
            st.session_state.update(locked_until=time.time() + 60, tries=0)
        st.error("Username or password is wrong, or the account is disabled. Ask the admin to reset it.")
    st.caption("Forgot your password? The admin can reset it from User management.")


def current_user() -> dict | None:
    u = st.session_state.get("user")
    if not u:
        return None
    fresh = db.get_user(u["username"])  # re-check every run so disabling takes effect immediately
    if not fresh or not fresh["active"]:
        st.session_state.pop("user", None)
        return None
    st.session_state["user"] = fresh
    return fresh


def change_password_form(user: dict, forced: bool = False) -> None:
    if forced:
        st.info("Set your own password before continuing.")
    with st.form("chpw"):
        a = st.text_input("New password (10+ characters)", type="password")
        b = st.text_input("Repeat new password", type="password")
        ok = st.form_submit_button("Save password", type="primary")
    if ok:
        if len(a) < 10:
            st.error("Use at least 10 characters.")
        elif a != b:
            st.error("The two passwords don't match.")
        else:
            db.update_user(user["username"], user["id"], password_hash=hash_pw(a), must_change=False)
            st.success("Password saved.")
            st.rerun()
