"""Absolute filesystem paths used across the app.

Resolved from this file's location, so the server works no matter which
directory it is started from.
"""
import os

APP_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(APP_DIR, "templates")
STATIC_DIR = os.path.join(APP_DIR, "static")
UPLOAD_DIR = os.path.join(STATIC_DIR, "htmlfotos")  # property & profile photos
