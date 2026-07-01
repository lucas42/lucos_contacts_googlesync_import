"""Unit tests for import.py — schedule_tracker emit path.

Two suites:

1. Mock-schedule-tracker suite (fast path) — stubs the whole schedule_tracker
   module and verifies the Python call args on the error path (Google credentials
   stub raises, triggering the except block).

2. Real-transport suite — uses the real v2 schedule_tracker client but patches
   its HTTP transport so no network call is made. Verifies the HTTP POST body
   contains the required fields. A broken call signature (missing job_name,
   wrong system, missing frequency) would fail here because the client sends
   the exact payload we pass.

Run from the repo root: python3 test_import.py
"""
import importlib.util
import os
import pathlib
import sys
import types
import unittest.mock as mock

# Required env vars — force-set (not setdefault) so test isolation isn't broken
# by ambient shell vars like SYSTEM=lucos_agent in the agent environment.
os.environ["SYSTEM"] = "lucos_contacts_googlesync_import"
os.environ["SCHEDULE_TRACKER_ENDPOINT"] = "http://stub/v2/report-status"
os.environ.setdefault("USER_EMAIL", "test@example.com")
os.environ.setdefault("GROUP", "contactGroups/test")
os.environ.setdefault("DEAD_GROUP", "contactGroups/dead")
os.environ.setdefault("PRIVATE_KEY", "stub-key")
os.environ.setdefault("CLIENT_EMAIL", "stub@stub.iam.gserviceaccount.com")
os.environ.setdefault("LUCOS_CONTACTS", "http://stub-contacts/")
os.environ.setdefault("KEY_LUCOS_CONTACTS", "stub-bearer-key")

_script_path = pathlib.Path(__file__).parent / "import.py"

# The Google credential stub raises to trigger the except block in import.py —
# the simplest way to exercise the schedule_tracker emit path without needing
# to mock the full Google People API call chain.
_GOOGLE_ERROR = ValueError("Stub Google credential error — triggers error path in import.py")


def _make_google_stubs():
    """Return sys.modules stubs for all Google API packages imported by import.py."""
    google_pkg = types.ModuleType("google")
    google_oauth2 = types.ModuleType("google.oauth2")
    google_oauth2_creds = types.ModuleType("google.oauth2.credentials")
    google_oauth2_creds.Credentials = mock.MagicMock()
    google_oauth2_sa = types.ModuleType("google.oauth2.service_account")
    mock_sa_creds = mock.MagicMock()
    mock_sa_creds.from_service_account_info = mock.Mock(side_effect=_GOOGLE_ERROR)
    google_oauth2_sa.Credentials = mock_sa_creds
    googleapiclient = types.ModuleType("googleapiclient")
    googleapiclient_discovery = types.ModuleType("googleapiclient.discovery")
    googleapiclient_discovery.build = mock.Mock()
    googleapiclient_errors = types.ModuleType("googleapiclient.errors")
    googleapiclient_errors.HttpError = Exception
    requests_stub = types.ModuleType("requests")
    requests_stub.post = mock.Mock(return_value=mock.MagicMock(raise_for_status=lambda: None))
    return {
        "google": google_pkg,
        "google.oauth2": google_oauth2,
        "google.oauth2.credentials": google_oauth2_creds,
        "google.oauth2.service_account": google_oauth2_sa,
        "googleapiclient": googleapiclient,
        "googleapiclient.discovery": googleapiclient_discovery,
        "googleapiclient.errors": googleapiclient_errors,
        "requests": requests_stub,
    }


_GOOGLE_STUB_MOD_NAMES = list(_make_google_stubs().keys())

# ---------------------------------------------------------------------------
# Suite 1: mock schedule_tracker — verify Python call args
# ---------------------------------------------------------------------------

mock_update_schedule_tracker = mock.Mock()

suite1_stubs = _make_google_stubs()
suite1_stubs["schedule_tracker"] = types.ModuleType("schedule_tracker")
suite1_stubs["schedule_tracker"].updateScheduleTracker = mock_update_schedule_tracker
for mod_name, stub in suite1_stubs.items():
    sys.modules[mod_name] = stub

spec = importlib.util.spec_from_file_location("import_script", _script_path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

# Clean up stubs so the real-transport suite can import the real schedule_tracker
for mod_name in list(suite1_stubs.keys()):
    sys.modules.pop(mod_name, None)

failures = 0


def test(comment, passed):
    global failures
    if not passed:
        print(f"\033[91mFailed\033[0m {comment}")
        failures += 1


test("updateScheduleTracker called at least once", mock_update_schedule_tracker.call_count >= 1)
test(
    "updateScheduleTracker called with success=False on error path",
    any(c.kwargs.get("success") is False for c in mock_update_schedule_tracker.call_args_list),
)
test(
    "updateScheduleTracker called with job_name='googlesync_import'",
    any(c.kwargs.get("job_name") == "googlesync_import" for c in mock_update_schedule_tracker.call_args_list),
)
test(
    "updateScheduleTracker called with frequency=300",
    any(c.kwargs.get("frequency") == 300 for c in mock_update_schedule_tracker.call_args_list),
)

# ---------------------------------------------------------------------------
# Suite 2: real-transport — drive the real schedule_tracker v2 client against
# a patched HTTP transport. Verifies the HTTP POST body has the required fields.
# ---------------------------------------------------------------------------

import schedule_tracker as _real_schedule_tracker  # noqa: E402

captured_payloads = []


def _fake_post(url, **kwargs):
    captured_payloads.append({"url": url, "json": kwargs.get("json", {})})
    resp = mock.MagicMock()
    resp.raise_for_status = lambda: None
    return resp


suite2_stubs = _make_google_stubs()
for mod_name, stub in suite2_stubs.items():
    sys.modules[mod_name] = stub

# Patch the session object used internally by the schedule_tracker v2.0.5+ client.
# v2.0.5 changed from requests.post() to session.post() (where session is a
# module-level requests.Session instance) so that the User-Agent header is set.
# Patching `session` intercepts the call regardless of whether requests.post is used.
with mock.patch.object(_real_schedule_tracker, "session") as mock_session:
    mock_session.post = _fake_post
    spec2 = importlib.util.spec_from_file_location("import_script_real", _script_path)
    module2 = importlib.util.module_from_spec(spec2)
    spec2.loader.exec_module(module2)

for mod_name in list(suite2_stubs.keys()):
    sys.modules.pop(mod_name, None)

googlesync_payloads = [
    p for p in captured_payloads
    if p["json"].get("job_name") == "googlesync_import"
]

test(
    "real schedule_tracker client POSTed to SCHEDULE_TRACKER_ENDPOINT",
    any(p["url"] == os.environ["SCHEDULE_TRACKER_ENDPOINT"] for p in captured_payloads),
)
test(
    "real schedule_tracker HTTP payload includes job_name='googlesync_import'",
    any(p["json"].get("job_name") == "googlesync_import" for p in googlesync_payloads),
)
test(
    "real schedule_tracker HTTP payload includes correct system",
    any(p["json"].get("system") == "lucos_contacts_googlesync_import" for p in googlesync_payloads),
)
test(
    "real schedule_tracker HTTP payload includes frequency=300",
    any(p["json"].get("frequency") == 300 for p in googlesync_payloads),
)

total = 8
if failures > 0:
    print(f"\033[91m{failures} failures\033[0m in {total} tests.")
    sys.exit(1)
else:
    print(f"All {total} import tests passed.")
