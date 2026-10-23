# Reference copy only — never mounted or imported at runtime. Each adopting
# app keeps its own verbatim copy in its own directory (no shared Python
# package exists across these isolated per-container apps). When you change
# this file, copy the change into every adopting app's copy by hand.
#
# Contract:
#   SettingField(key, label, type, sensitive, validate)
#     - type in {"text", "url", "secret", "boolean"}
#     - "boolean" values are stored/transmitted as the literal strings
#       "true"/"false" (same TEXT column as everything else) — the CList
#       renderer draws a checkbox for this type and the app treats the
#       string "false" as off, anything else as on.
#     - validate: optional str -> str|None (error message, or None if valid)
#   init_settings_table(db)                       — call from the app's init_db()
#   get_setting(db, key, default=None)             — call at point of use, every call
#   is_admin(username)                             — username in ADMIN_USERNAMES
#   register_admin_settings_routes(app, schema, get_db, verify_token)
#     — registers GET/PUT /admin/settings
#
# Adopting an app:
#   1. Copy this file into the app directory verbatim.
#   2. Call init_settings_table(db) inside the app's existing init_db().
#   3. Declare SETTINGS_SCHEMA and call register_admin_settings_routes(...).
#   4. Replace frozen constant reads at their point of use with
#      get_setting(get_db(), "KEY", default=os.environ.get("KEY", "...")).
#   5. Add ADMIN_USERNAMES=<comma-separated usernames> to .env.
#   6. Update that app's CLAUDE.md: new env var, new /admin/settings
#      endpoints, DB-override-falls-back-to-.env precedence.

import os
from collections import namedtuple

from flask import request, jsonify

SettingField = namedtuple("SettingField", ["key", "label", "type", "sensitive", "validate", "help"])
SettingField.__new__.__defaults__ = (None, None)  # validate, help are optional

ADMIN_USERNAMES = {
    u.strip() for u in os.environ.get("ADMIN_USERNAMES", "").split(",") if u.strip()
}


def is_admin(username):
    return bool(username) and username in ADMIN_USERNAMES


def init_settings_table(db):
    db.execute("""
        CREATE TABLE IF NOT EXISTS app_settings (
            key        TEXT PRIMARY KEY,
            value      TEXT,
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    db.commit()


def get_setting(db, key, default=None):
    row = db.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
    if row and row["value"]:
        return row["value"]
    return default


def _mask(value):
    # Fixed-length mask regardless of real length, so the mask itself never
    # leaks how long the underlying secret is.
    if not value:
        return None
    return "•" * 8 + value[-4:]


def register_admin_settings_routes(app, schema, get_db, verify_token, defaults=None):
    """Registers GET/PUT /admin/settings on `app`. `schema` is a list of
    SettingField. `get_db`/`verify_token` are the app's existing helpers.
    `defaults` is an optional {key: value} map of the .env-sourced fallback
    each field would resolve to if no admin override exists yet — the same
    value the app's own point-of-use get_setting(..., default=...) call
    uses. Without it, GET would show every unsaved field as empty even
    though the app is actually running on a real value from .env."""
    schema_by_key = {f.key: f for f in schema}
    defaults = defaults or {}

    def _schema_json():
        return [
            {"key": f.key, "label": f.label, "type": f.type, "sensitive": f.sensitive, "help": f.help}
            for f in schema
        ]

    def _masked_values(db):
        out = {}
        for f in schema:
            raw = get_setting(db, f.key, default=defaults.get(f.key))
            out[f.key] = _mask(raw) if f.sensitive else raw
        return out

    @app.route("/admin/settings", methods=["GET"])
    def admin_get_settings():
        username, err = verify_token()
        if err:
            return jsonify(err[0]), err[1]
        if not is_admin(username):
            return jsonify({"error": "Forbidden"}), 403
        db = get_db()
        return jsonify({"schema": _schema_json(), "values": _masked_values(db)})

    @app.route("/admin/settings", methods=["PUT"])
    def admin_put_settings():
        username, err = verify_token()
        if err:
            return jsonify(err[0]), err[1]
        if not is_admin(username):
            return jsonify({"error": "Forbidden"}), 403

        data = request.get_json(silent=True) or {}
        for key in data:
            if key not in schema_by_key:
                return jsonify({"error": f"Unknown setting: {key}"}), 400
        for key, value in data.items():
            validate = schema_by_key[key].validate
            if validate:
                error = validate(value)
                if error:
                    return jsonify({"error": f"{key}: {error}"}), 400

        # Validate-then-write: nothing is persisted unless every key in the
        # request passes, so a partial PUT never leaves settings half-applied.
        db = get_db()
        for key, value in data.items():
            db.execute(
                "INSERT INTO app_settings (key, value, updated_at) "
                "VALUES (?, ?, datetime('now')) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
                (key, value),
            )
        db.commit()
        return jsonify({"schema": _schema_json(), "values": _masked_values(db)})
