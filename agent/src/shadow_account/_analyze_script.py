"""Standalone script called by shadow_analyze API endpoint."""
import argparse
import json
import sys

from src.shadow_account import (
    extract_shadow_profile,
    save_profile,
    run_shadow_backtest,
    render_shadow_report,
)
from src.shadow_account.backtester import load_cached_result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", required=True)
    args = parser.parse_args()

    profile = extract_shadow_profile(args.csv, min_support=3, max_rules=5)
    save_profile(profile)

    result = load_cached_result(profile.shadow_id)
    if result is None:
        try:
            result = run_shadow_backtest(
                profile,
                window_start="2026-01-01",
                window_end="2026-12-31",
                journal_path=args.csv,
            )
        except Exception:
            from src.shadow_account.models import (
                AttributionBreakdown,
                ShadowBacktestResult,
            )

            result = ShadowBacktestResult(
                shadow_id=profile.shadow_id,
                per_market={},
                combined={},
                equity_curves={},
                attribution=AttributionBreakdown(
                    missed_signals_pnl=0.0,
                    noise_trades_pnl=0.0,
                    early_exit_pnl=0.0,
                    late_exit_pnl=0.0,
                    overtrading_pnl=0.0,
                    counterfactual_trades=(),
                ),
                shadow_total_pnl=0.0,
                real_total_pnl=0.0,
                delta_pnl=0.0,
            )

    report = render_shadow_report(profile, result, today_signals=[])

    rules = [
        {
            "rule_id": r.rule_id,
            "human_text": r.human_text,
            "support_count": r.support_count,
            "coverage_rate": r.coverage_rate,
            "holding_days_range": list(r.holding_days_range),
        }
        for r in profile.rules
    ]

    summary = {
        "shadow_id": profile.shadow_id,
        "profitable_roundtrips": profile.profitable_roundtrips,
        "total_roundtrips": profile.total_roundtrips,
        "source_market": profile.source_market,
        "typical_holding_days": list(profile.typical_holding_days),
        "rules": rules,
        "shadow_pnl": result.shadow_total_pnl,
        "real_pnl": result.real_total_pnl,
        "delta_pnl": result.delta_pnl,
        "html_path": report["html_path"],
    }
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
