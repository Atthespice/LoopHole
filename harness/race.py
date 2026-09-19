"""Phase 0 go/no-go race. Run this BEFORE anyone forks off into their folder.

Three gates, per CONTRACT.md:
  1. The current model beats the previous model in the SAME loop -- the actual
     Breakthrough-track claim. If the old model also finds the bypass, stop.
  2. The current model beats a classic fuzzer (hypothesis) on speed and
     false-positive rate -- proves the loop itself is worth building.
  3. The model actually produces bypass candidates under our prompt framing,
     instead of refusing or hedging -- check this first, it's cheap.

If any gate doesn't clearly pass, stop per the CONTRACT.md stop rule and pick a
different guard case or a different idea. No arguments later.
"""

from shared.types import GuardCase


def check_model_cooperates(case: GuardCase) -> bool:
    """Gate 3: does the model actually attempt bypasses under our framing?"""
    # TODO: send one prompt (framed as authorized testing of our own guard
    # function), confirm we get a real candidate input back, not a refusal.
    raise NotImplementedError


def race_against_previous_model(case: GuardCase, budget: int) -> None:
    """Gate 1: current model vs previous model, same loop, same budget."""
    # TODO: run the same generate/run/observe/mutate loop with both models,
    # compare whether/how fast each finds a real bypass.
    raise NotImplementedError


def race_against_classic_fuzzer(case: GuardCase, budget: int) -> None:
    """Gate 2: current model vs hypothesis, same budget."""
    # TODO
    raise NotImplementedError


if __name__ == "__main__":
    # TODO: wire the three gates together, print a clear go/no-go verdict.
    pass
