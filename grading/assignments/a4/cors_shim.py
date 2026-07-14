"""Run-time CORS wrapper for launching a student's A2 backend during A4 inspection.

The A2 backends in the class repo working tree don't carry the CORS middleware students
added for A4 (that change lives on their own branches), so a browser on :5173 gets blocked
even though the server returns 200. This shim imports the student's app and wraps it with a
permissive CORSMiddleware so the app actually renders. It does NOT touch student files.

CORS presence/absence is a grading matter handled elsewhere — this is purely so the running
app can be viewed.

Usage (set by run_student.sh):
    A4_APP=main:app  PYTHONPATH=<backend_dir>:<this_dir>  uvicorn cors_shim:app
"""
import os
from importlib import import_module

from starlette.middleware.cors import CORSMiddleware

_spec = os.environ.get("A4_APP", "main:app")
_mod_name, _attr = _spec.split(":", 1)
app = getattr(import_module(_mod_name), _attr)

# Only inject CORS if the student's own app didn't already register it — wrapping an app that
# already has CORSMiddleware would emit duplicate Access-Control-Allow-Origin headers, which
# the browser rejects. So this respects a student's real CORS config and only fills the gap.
_has_cors = any(getattr(m, "cls", None) is CORSMiddleware for m in app.user_middleware)
if _has_cors:
    print("[cors_shim] student app already registers CORSMiddleware -> leaving it as-is")
else:
    print("[cors_shim] no CORS in student app -> injecting permissive CORS for viewing")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["*"],
    )
