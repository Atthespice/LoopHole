"""Owned by: demo/ (see CONTRACT.md).

Tails runs/<case_name>.jsonl and renders attempts live with rich. Never imports
loop/ or verdict/ directly -- read the log file only.
"""

import sys


def watch(log_path: str) -> None:
    # TODO: tail log_path, render Attempt/Candidate/Verdict events live with
    # rich, and highlight the confirmed bypass + fix when it lands.
    raise NotImplementedError


if __name__ == "__main__":
    watch(sys.argv[1])
