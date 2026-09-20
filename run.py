"""One command to run LoopHole end to end.

    .venv/bin/python run.py <case_name>        # attack a case, judge it, open browser
    .venv/bin/python run.py --fixture          # no API key: replay the bundled demo
    .venv/bin/python run.py <case> --budget 8  # fewer model calls (cheaper)
    .venv/bin/python run.py <case> --no-web     # terminal only, skip the browser

It does the three steps for you:
  1. loop    -- Fable attacks the guard, writes runs/<case>.jsonl
  2. verdict -- confirms real bypasses, appends the rulings
  3. web     -- serves the finished run at http://127.0.0.1:<port>

The only thing you write is the GuardCase in harness/cases.py (see the template
there, or harness/oracles.make_case for common categories).
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import webbrowser

REPO = os.path.dirname(os.path.abspath(__file__))
FIXTURE = "demo/fixtures/path_traversal.jsonl"


def _load_dotenv() -> None:
    if os.environ.get("ANTHROPIC_API_KEY"):
        return
    path = os.path.join(REPO, ".env")
    if not os.path.isfile(path):
        return
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip("'\""))


def _find_case(name: str):
    from harness.cases import CASES

    for case in CASES:
        if case.name == name:
            return case
    names = ", ".join(c.name for c in CASES)
    sys.exit(f"No case named {name!r}. Available: {names}")


def _free_port(preferred: int) -> int:
    """Use `preferred` if it's open, otherwise pick any free port. Avoids the
    'browser opens someone else's server on 8000' trap on a busy machine."""
    import socket

    for candidate in (preferred, 0):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("127.0.0.1", candidate))
            chosen = s.getsockname()[1]
            s.close()
            if candidate != preferred:
                print(f"(port {preferred} was busy — using {chosen} instead)")
            return chosen
        except OSError:
            s.close()
    return preferred


def _serve(log_rel: str, port: int) -> None:
    port = _free_port(port)
    url = f"http://127.0.0.1:{port}/?log={log_rel}"
    print(f"\nOpening {url}\n(Ctrl-C to stop the server.)")
    proc = subprocess.Popen([sys.executable, os.path.join(REPO, "web", "server.py"), str(port)])
    try:
        webbrowser.open(url)
    except Exception:
        pass
    try:
        proc.wait()
    except KeyboardInterrupt:
        proc.terminate()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run LoopHole end to end.")
    parser.add_argument("case", nargs="?", help="GuardCase.name from harness/cases.py")
    parser.add_argument("--fixture", action="store_true", help="replay the bundled demo, no API key")
    parser.add_argument("--budget", type=int, default=15, help="max attempts (default 15)")
    parser.add_argument("--port", type=int, default=8000, help="web port (default 8000)")
    parser.add_argument("--no-web", action="store_true", help="terminal only")
    parser.add_argument("--show-refusal", action="store_true",
                        help="before attacking, show Fable 5.1 refuse the same task live")
    args = parser.parse_args()

    if args.fixture:
        print("Replaying the bundled demo (no API calls).")
        _serve(FIXTURE, args.port)
        return

    if not args.case:
        parser.error("give a case name, or use --fixture")

    _load_dotenv()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("No ANTHROPIC_API_KEY. Put it in a .env file, or use --fixture.")

    case = _find_case(args.case)
    log_rel = f"runs/{case.name}.jsonl"
    log_abs = os.path.join(REPO, log_rel)
    os.makedirs(os.path.dirname(log_abs), exist_ok=True)
    open(log_abs, "w").close()  # fresh run

    if args.show_refusal:
        from harness.fable_check import print_report

        print("[0/3] checking the newest model first…")
        print_report(case)
        print()

    from loop.run_loop import run_loop
    from verdict.judge import tail_and_judge

    print(f"[1/3] loop: attacking {case.name} (budget {args.budget})…")
    run_loop(case, args.budget, log_abs)

    print("[2/3] verdict: confirming real bypasses…")
    result = tail_and_judge(case, log_abs)
    real = [v for v in getattr(result, "verdicts", []) if getattr(v, "is_real_bypass", False)]
    print(f"      {len(real)} real bypass(es) confirmed.")

    if args.no_web:
        print(f"[3/3] done. Log: {log_rel} (view with: python web/server.py, or demo/main.py {log_rel})")
        return
    print("[3/3] serving the result in the browser…")
    _serve(log_rel, args.port)


if __name__ == "__main__":
    main()
