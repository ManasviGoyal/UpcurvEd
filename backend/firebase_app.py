"""Firebase Admin initialization for Firestore and Auth.

Uses Application Default Credentials (ADC) in production (e.g. Cloud Run with
attached service account). Locally you can set GOOGLE_APPLICATION_CREDENTIALS
to point to a service account JSON. We lazy-initialize the app so importing
backend.firebase_app is cheap.
"""

from __future__ import annotations

import os

import firebase_admin
from firebase_admin import credentials, firestore

# Guard repeated initialization by name to prevent multi-init in hot reload
_APP_NAME = "ac215-core"

_app: firebase_admin.App | None = None
_db: firestore.Client | None = None


def init_firebase() -> firestore.Client:
    global _app, _db
    if _db is not None:
        return _db
    # Initialize a DEFAULT app if none exists so firebase_admin.auth.* functions work.
    try:
        default_app = firebase_admin.get_app()
        _app = default_app
    except ValueError:
        # No default app yet; create one (without a custom name) so Auth APIs use it.
        cred: credentials.Base = credentials.ApplicationDefault()
        json_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        if json_path and os.path.isfile(json_path):
            cred = credentials.Certificate(json_path)
        _app = firebase_admin.initialize_app(cred)
    # Optionally also register a named app if not present (harmless); but primary usage is default.
    if _APP_NAME not in firebase_admin._apps:
        try:
            firebase_admin.initialize_app(_app.credential, name=_APP_NAME)
        except Exception:
            pass
    _db = firestore.client()
    return _db


def get_db() -> firestore.Client:
    return init_firebase()
