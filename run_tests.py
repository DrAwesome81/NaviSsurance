#!/usr/bin/env python3
"""
Test runner script for NaviSsurance application.
Run all tests with proper configuration and reporting.
"""
# Test runner covers Pulse private memory, Intel raising, CoS coordination, and 🛡️ Shield security (pillar test coordination)
# Pulse private memory + Shield (run tests surface)

import os
import sys
import subprocess

def run_tests():
    """Run all tests with pytest."""
    print("Running NaviSsurance Test Suite")
    print("=" * 50)
    pytest_args = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "--tb=short",
        "--color=yes",
        "--durations=10",
    ]
    
    # Run tests
    try:
        result = subprocess.run(pytest_args, check=True)
        print("\n" + "=" * 50)
        print("All tests passed! ✅")
        return True
    except subprocess.CalledProcessError as e:
        print("\n" + "=" * 50)
        print(f"Tests failed with exit code {e.returncode} ❌")
        return False
    except FileNotFoundError:
        print("pytest not found. Please install with: pip install pytest")
        return False

def run_specific_test(test_name):
    """Run a specific test by name."""
    pytest_args = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "--tb=short",
        str(test_name),
    ]
    
    try:
        subprocess.run(pytest_args, check=True)
        return True
    except subprocess.CalledProcessError:
        return False

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "user-smoke":
        pass  # special handling after the full def at bottom of file
    elif len(sys.argv) > 1:
        # Run specific test (pytest name)
        test_name = sys.argv[1]
        print(f"Running specific test: {test_name}")
        success = run_specific_test(test_name)
        sys.exit(0 if success else 1)
    else:
        # Run all tests
        success = run_tests()
        sys.exit(0 if success else 1)


# =============================================================================
# Automated "user-like" smoke harness (for "act as if it were me" + log capture)
# =============================================================================
# This is the practical way to automate a lot of "user" behavior without
# the flakiness of real Qt GUI clicking. It drives the same services, CoS,
# tasks, local API, etc. that the GUI uses.
#
# Run with: python run_tests.py user-smoke
#
# It exercises representative flows (CoS planning from calendar context,
# tasks with blockers/IDs, basic API), captures "terminal-like" output
# (stdout + in-harnes log buffer), and on failure dumps the captured
# messages + traceback (simulating "capture terminal message when it fails").
#
# Extend by adding more _run_scenario calls inside run_user_smoke() (use public
# core functions: cos_response for delegation/planning, db for tasks/blockers/IDs,
# ConsistencyChecker, workspace generation where non-GUI, etc.).
# For true "another app", use the local HTTP API (see tests/test_local_api.py
# for TestClient pattern) from any language.
#
# Full pixel-perfect GUI clicking as a live user would require additional
# desktop automation (pyautogui + screenshots or Qt test drivers) on top
# of this; that layer is intentionally kept minimal/manual per testing.md
# and AGENTS.md because of Windows PyQt stability and non-deterministic LLM
# responses.

import io
import logging
import traceback
from contextlib import redirect_stdout, redirect_stderr

def _setup_log_capture():
    """Capture log messages that would go to terminal/file during the harness."""
    log_capture = io.StringIO()
    handler = logging.StreamHandler(log_capture)
    handler.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    return log_capture, handler

def _teardown_log_capture(handler):
    root = logging.getLogger()
    root.removeHandler(handler)

def run_user_smoke():
    """Drive NaviSsurance 'as a user' via services + API, with failure log capture."""
    print("Running automated user-like smoke harness...")
    print("This exercises CoS, tasks (blockers/IDs), local API, etc. without full GUI.")
    print("On any failure it will dump captured 'terminal' output + logs.")
    print("=" * 60)

    log_capture, log_handler = _setup_log_capture()
    captured_stdout = io.StringIO()

    success = True
    temp_dir = None
    try:
        import tempfile
        temp_dir = tempfile.TemporaryDirectory()
        db_path = os.path.join(temp_dir.name, "smoke.db")

        def _run_scenario(name, func):
            nonlocal success
            print(f"[User smoke] {name}...")
            try:
                func(db_path)
            except Exception as e:
                success = False
                print(f"  FAILURE in {name}:")
                print(traceback.format_exc())
                captured = captured_stdout.getvalue() + log_capture.getvalue()
                print("\n--- CAPTURED TERMINAL / LOG OUTPUT ON FAILURE ---")
                print(captured[-2000:] if captured else "(no captured output)")
                print("--- END CAPTURE ---")

        with redirect_stdout(captured_stdout), redirect_stderr(captured_stdout):
            # --- Scenario 1: Basic local API health ( "another app" talking to Navi) ---
            def _scenario1(db_path):
                from core.db import DatabaseManager
                import importlib
                from fastapi.testclient import TestClient
                db = DatabaseManager(db_path)
                api_app = importlib.import_module("api.app")
                # Use TestClient pattern (headless, no GUI)
                client = TestClient(api_app.app)
                # Note: in full harness we'd monkey the db, but here just confirm loads
                print("  Local API app loads (TestClient ready for headless driving).")
            _run_scenario("Checking local API health (headless integration)", _scenario1)

            # --- Scenario 2: CoS day planning from calendar context (your exact question) ---
            def _scenario2(db_path):
                from core.db import DatabaseManager
                from core.chief_of_staff_service import cos_response
                db = DatabaseManager(db_path)
                result = cos_response(
                    db,
                    user_message="Help plan out my day based on my calendar blocks. Prioritize any open high-urgency work.",
                    conversation_history=[],
                    chat_id=None,
                )
                print(f"  CoS response length: {len(result or '')} chars (first 300): {(result or '')[:300]}...")
                if not result or "plan" not in (result or "").lower():
                    print("  Note: response did not contain obvious 'plan' language (acceptable, non-deterministic).")
            _run_scenario("Asking CoS to plan day based on calendar blocks", _scenario2)

            # --- Scenario 3: Tasks with blockers + ID references (your recent question) ---
            def _scenario3(db_path):
                from core.db import DatabaseManager
                db = DatabaseManager(db_path)
                tid = db.add_task(
                    session_id="user_smoke",
                    task_text="Review predicates for new device",
                    due_date="06-20-2026",
                    category="Business",
                    blockers="Waiting on clinical data from client (see task 42 for related work)",
                    priority=4,
                )
                print(f"  Created task numeric ID: {tid}")
                row = db.get_task_by_id(tid)
                print(f"  Retrieved task T-{tid:04d}, blockers field: {row.get('blockers')[:60] if row.get('blockers') else '(none)'}...")
                db.update_task_by_id(tid, blockers="Updated: depends on T-42 for the SE table section")
                print("  Successfully referenced/updated using task ID (numeric) as required.")
            _run_scenario("Creating task with blockers and using numeric task ID", _scenario3)

            # --- Scenario 4: Extended CoS delegation + consistency surface (Phase 4 tie-in) ---
            def _scenario4(db_path):
                from core.db import DatabaseManager
                from core.chief_of_staff_service import cos_response, _consistency_context
                from core.consistency_checker import ConsistencyChecker
                db = DatabaseManager(db_path)
                # Simulate user delegation prompt (triggers PROPOSE/APPROVE marker path internally)
                result = cos_response(
                    db,
                    user_message="I need to locate examples of a software design specification for an SaMD. Have Pulse look for this. You won't find anything in 510(k). Go ahead.",
                    conversation_history=[],
                    chat_id=None,
                )
                print(f"  CoS delegation response length: {len(result or '')} chars")
                # Check consistency context (now richer for reports)
                ctx = _consistency_context(db)
                print(f"  CoS consistency context (Phase 4 surface): {ctx[:150]}...")
                # Direct checker for single-doc (as enhanced)
                checker = ConsistencyChecker()
                rep = checker.check_related_set([{"title": "Sample Doc", "markdown": "Some content with refs."}], "", "single")
                print(f"  Direct single-doc consistency status: {rep.overall_status}")
            _run_scenario("CoS delegation flow + consistency report surface", _scenario4)

            print("\nUser smoke completed.")
            if success:
                print("No hard failures in exercised flows. ✅")
            else:
                print("One or more flows hit errors (see dumps above). ❌")

    except Exception as outer_e:
        success = False
        print("Unexpected top-level failure in harness:")
        print(traceback.format_exc())

    finally:
        _teardown_log_capture(log_handler)
        if temp_dir:
            try:
                temp_dir.cleanup()
            except Exception:
                pass  # best effort on Windows locks

    captured_all = captured_stdout.getvalue() + log_capture.getvalue()
    if not success and captured_all:
        print("\n[Final captured output on overall failure]")
        print(captured_all[-3000:])

    return success

# Allow: python run_tests.py user-smoke
if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "user-smoke":
    ok = run_user_smoke()
    sys.exit(0 if ok else 1)


