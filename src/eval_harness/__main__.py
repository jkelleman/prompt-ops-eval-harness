"""Run the default evaluation suite: python -m eval_harness"""

from .scenarios import DEFAULT_SUITE, build_evaluator


def main() -> int:
    report = build_evaluator().run(DEFAULT_SUITE)
    print(report.scorecard())
    return 0 if report.pass_rate == 1.0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
