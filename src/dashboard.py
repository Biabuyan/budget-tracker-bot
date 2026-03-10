"""
dashboard.py — Generate spending dashboard image for Telegram
"""

import io
import logging
from datetime import datetime, timedelta
from typing import Optional
from collections import defaultdict

import numpy as np
import matplotlib
matplotlib.use("Agg")   # non-interactive backend
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.patches import FancyBboxPatch
import matplotlib.ticker as mticker

logger = logging.getLogger(__name__)

# ── Colour palette ────────────────────────────────────────────
PALETTE = [
    "#4F86C6", "#E8735A", "#5CB85C", "#F0AD4E",
    "#9B59B6", "#1ABC9C", "#E74C3C", "#3498DB",
    "#F39C12", "#2ECC71",
]
BG_COLOR   = "#0F1117"
CARD_COLOR = "#1C1F2E"
TEXT_COLOR = "#E8E8F0"
ACCENT     = "#4F86C6"
GREEN      = "#5CB85C"
RED        = "#E8735A"


def _fig_setup(title: str):
    fig = plt.figure(figsize=(14, 10), facecolor=BG_COLOR)
    fig.suptitle(title, color=TEXT_COLOR, fontsize=18, fontweight="bold",
                 y=0.97, fontfamily="DejaVu Sans")
    return fig


def generate_dashboard(
    category_totals: list,   # [{category, total, count}, ...]
    daily_totals: list,       # [{date, total}, ...]
    monthly_trend: list,      # [{month, total}, ...]
    monthly_budget: float,
    currency: str = "$",
    category_totals_by_currency: list = None,  # [{currency, category, total, count}, ...]
    daily_totals_by_currency: list = None,      # [{date, currency, total}, ...]
    monthly_trend_by_currency: list = None,     # [{month, currency, total}, ...]
) -> io.BytesIO:
    """Return a BytesIO PNG of the full dashboard."""

    now = datetime.now()
    title = f"Budget Dashboard  —  {now.strftime('%B %Y')}"
    fig = _fig_setup(title)

    # Determine how many currencies we have
    currencies = set()
    if category_totals_by_currency:
        for r in category_totals_by_currency:
            currencies.add(r["currency"])
    if not currencies:
        currencies = {currency}
    currencies = sorted(currencies)
    multi_currency = len(currencies) > 1

    total_spent = sum(r["total"] for r in category_totals)
    remaining   = monthly_budget - total_spent
    pct_used    = (total_spent / monthly_budget * 100) if monthly_budget else 0

    gs = gridspec.GridSpec(
        2, 3,
        figure=fig,
        hspace=0.45,
        wspace=0.35,
        top=0.91, bottom=0.07,
        left=0.07, right=0.97,
    )

    # ── 1. KPI header cards ────────────────────────────────────
    ax_kpi = fig.add_subplot(gs[0, :])
    ax_kpi.set_xlim(0, 1)
    ax_kpi.set_ylim(0, 1)
    ax_kpi.axis("off")

    if multi_currency and category_totals_by_currency:
        # Show per-currency totals in the "Total Spent" card
        cur_totals = defaultdict(float)
        for r in category_totals_by_currency:
            cur_totals[r["currency"]] += r["total"]
        spent_str = "\n".join(f"{c} {v:,.2f}" for c, v in sorted(cur_totals.items()))
        spent_color = ACCENT
    else:
        spent_str = f"{currency}{total_spent:,.2f}"
        spent_color = ACCENT

    cards = [
        ("Total Spent",     spent_str,                                spent_color,  10 if multi_currency else 14),
        ("Remaining",       f"{currency}{remaining:,.2f}",            GREEN if remaining >= 0 else RED, 14),
        ("Budget",          f"{currency}{monthly_budget:,.2f}",       TEXT_COLOR, 14),
        ("% Used",          f"{pct_used:.1f}%",                       GREEN if pct_used < 80 else RED, 14),
        ("Transactions",    str(sum(r["count"] for r in category_totals)), TEXT_COLOR, 14),
    ]

    card_w, card_h = 0.17, 0.75
    spacing = 0.19
    x_start = 0.025
    for i, (label, value, color, fsize) in enumerate(cards):
        x = x_start + i * spacing
        rect = FancyBboxPatch(
            (x, 0.1), card_w, card_h,
            boxstyle="round,pad=0.02",
            facecolor=CARD_COLOR, edgecolor=color, linewidth=1.5,
            transform=ax_kpi.transAxes
        )
        ax_kpi.add_patch(rect)
        ax_kpi.text(x + card_w / 2, 0.64, value, ha="center", va="center",
                    color=color, fontsize=fsize, fontweight="bold",
                    transform=ax_kpi.transAxes)
        ax_kpi.text(x + card_w / 2, 0.28, label, ha="center", va="center",
                    color="#9999AA", fontsize=8,
                    transform=ax_kpi.transAxes)

    # ── 2. Category pie chart (per currency if multi-currency) ─
    ax_pie = fig.add_subplot(gs[1, 0])
    ax_pie.set_facecolor(CARD_COLOR)

    if multi_currency and category_totals_by_currency:
        # Build labels as "Currency - Category"
        labels  = [f"{r['currency']} {r['category']}" for r in category_totals_by_currency]
        amounts = [r["total"] for r in category_totals_by_currency]
    elif category_totals:
        labels  = [r["category"] for r in category_totals]
        amounts = [r["total"]    for r in category_totals]
    else:
        labels, amounts = [], []

    if labels:
        colors  = PALETTE[:len(labels)] if len(labels) <= len(PALETTE) else (PALETTE * ((len(labels) // len(PALETTE)) + 1))[:len(labels)]
        wedges, _, autotexts = ax_pie.pie(
            amounts, labels=None, colors=colors,
            autopct="%1.1f%%", startangle=140,
            pctdistance=0.78,
            wedgeprops=dict(linewidth=1.5, edgecolor=BG_COLOR),
        )
        for at in autotexts:
            at.set_color(TEXT_COLOR)
            at.set_fontsize(7)

        legend_labels = [f"{l} ({a:,.0f})" for l, a in zip(labels, amounts)]
        ncol = 2 if len(labels) <= 8 else 3
        ax_pie.legend(
            wedges, legend_labels,
            loc="lower center", bbox_to_anchor=(0.5, -0.28),
            fontsize=6, ncol=ncol, framealpha=0,
            labelcolor=TEXT_COLOR,
        )
    else:
        ax_pie.text(0.5, 0.5, "No data", ha="center", va="center",
                    color=TEXT_COLOR, transform=ax_pie.transAxes)

    ax_pie.set_title("Spending by Category", color=TEXT_COLOR, fontsize=11, pad=8)

    # ── 3. Daily spending bar chart ───────────────────────────
    ax_daily = fig.add_subplot(gs[1, 1])
    ax_daily.set_facecolor(CARD_COLOR)

    if daily_totals:
        # Fill in all days of the month up to today with 0 for missing days
        first_day = 1
        last_day = now.day
        all_days = list(range(first_day, last_day + 1))

        if multi_currency and daily_totals_by_currency:
            # Stacked bars per currency
            day_cur_map = defaultdict(lambda: defaultdict(float))
            for r in daily_totals_by_currency:
                day_num = int(r["date"][-2:])
                day_cur_map[day_num][r["currency"]] += r["total"]

            x = np.array(all_days)
            bottom = np.zeros(len(all_days))
            bar_handles = []
            for ci, cur in enumerate(currencies):
                vals = np.array([day_cur_map[d].get(cur, 0) for d in all_days])
                color = PALETTE[ci % len(PALETTE)]
                bars = ax_daily.bar(x, vals, bottom=bottom, color=color, alpha=0.85,
                                    edgecolor=BG_COLOR, linewidth=0.5, label=cur)
                bar_handles.append(bars)
                bottom += vals
            ax_daily.legend(fontsize=7, framealpha=0, labelcolor=TEXT_COLOR)
        else:
            # Single-currency: simple bars with integer x-axis
            day_map = {int(r["date"][-2:]): r["total"] for r in daily_totals}
            x = np.array(all_days)
            amounts = np.array([day_map.get(d, 0) for d in all_days])
            bars = ax_daily.bar(x, amounts, color=ACCENT, alpha=0.85,
                                edgecolor=BG_COLOR, linewidth=0.8)
            today_num = now.day
            for bar, day in zip(bars, all_days):
                if day == today_num:
                    bar.set_color(GREEN)
            # avg line
            nonzero = amounts[amounts > 0]
            if len(nonzero) > 0:
                avg = float(nonzero.mean())
                ax_daily.axhline(avg, color=RED, linestyle="--", linewidth=1,
                                 label=f"Avg {currency}{avg:,.0f}")
                ax_daily.legend(fontsize=7, framealpha=0, labelcolor=TEXT_COLOR)

        ax_daily.set_xlabel("Day of month", color="#9999AA", fontsize=8)
        ax_daily.set_ylabel(f"Amount", color="#9999AA", fontsize=8)
        ax_daily.tick_params(colors="#9999AA", labelsize=7)
        ax_daily.yaxis.set_major_formatter(mticker.FuncFormatter(
            lambda v, _: f"{v:,.0f}"))
        ax_daily.spines[["top", "right"]].set_visible(False)
        for spine in ["bottom", "left"]:
            ax_daily.spines[spine].set_color("#333355")
        # Reduce x-tick clutter: show every Nth day
        if len(all_days) > 15:
            ax_daily.set_xticks(all_days[::2])
        else:
            ax_daily.set_xticks(all_days)
    else:
        ax_daily.text(0.5, 0.5, "No data", ha="center", va="center",
                      color=TEXT_COLOR, transform=ax_daily.transAxes)

    ax_daily.set_title("Daily Spending", color=TEXT_COLOR, fontsize=11, pad=8)

    # ── 4. Monthly trend line chart ───────────────────────────
    ax_trend = fig.add_subplot(gs[1, 2])
    ax_trend.set_facecolor(CARD_COLOR)

    if monthly_trend:
        if multi_currency and monthly_trend_by_currency:
            # Group by currency, plot one line per currency
            trend_data = defaultdict(dict)  # {currency: {month_str: total}}
            all_months_set = set()
            for r in monthly_trend_by_currency:
                trend_data[r["currency"]][r["month"]] = r["total"]
                all_months_set.add(r["month"])
            all_months = sorted(all_months_set)
            x = np.arange(len(all_months))

            for ci, cur in enumerate(sorted(trend_data.keys())):
                vals = [trend_data[cur].get(m, 0) for m in all_months]
                color = PALETTE[ci % len(PALETTE)]
                ax_trend.plot(x, vals, color=color, linewidth=2,
                              marker="o", markersize=5, label=cur)

            ax_trend.set_xticks(x)
            ax_trend.set_xticklabels([m[5:] for m in all_months])
            ax_trend.legend(fontsize=7, framealpha=0, labelcolor=TEXT_COLOR)
        else:
            trend = list(reversed(monthly_trend))   # oldest → newest
            month_labels = [r["month"][5:] for r in trend]  # "MM"
            amounts = [r["total"] for r in trend]
            x = np.arange(len(trend))

            ax_trend.plot(x, amounts, color=ACCENT, linewidth=2.5,
                          marker="o", markersize=6, markerfacecolor=GREEN)
            ax_trend.fill_between(x, amounts, alpha=0.15, color=ACCENT)
            ax_trend.axhline(monthly_budget, color=RED, linestyle="--",
                             linewidth=1, label=f"Budget {currency}{monthly_budget:,.0f}")
            ax_trend.set_xticks(x)
            ax_trend.set_xticklabels(month_labels)
            ax_trend.legend(fontsize=7, framealpha=0, labelcolor=TEXT_COLOR)

        ax_trend.set_xlabel("Month", color="#9999AA", fontsize=8)
        ax_trend.set_ylabel(f"Spent", color="#9999AA", fontsize=8)
        ax_trend.tick_params(colors="#9999AA", labelsize=7)
        ax_trend.yaxis.set_major_formatter(mticker.FuncFormatter(
            lambda v, _: f"{v:,.0f}"))
        ax_trend.spines[["top", "right"]].set_visible(False)
        for spine in ["bottom", "left"]:
            ax_trend.spines[spine].set_color("#333355")
    else:
        ax_trend.text(0.5, 0.5, "No data", ha="center", va="center",
                      color=TEXT_COLOR, transform=ax_trend.transAxes)

    ax_trend.set_title("Monthly Trend (6 mo.)", color=TEXT_COLOR, fontsize=11, pad=8)

    # ── Watermark ─────────────────────────────────────────────
    fig.text(0.99, 0.01, f"Generated {now.strftime('%d %b %Y %H:%M')}",
             ha="right", va="bottom", color="#444466", fontsize=7)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=140, bbox_inches="tight",
                facecolor=BG_COLOR)
    plt.close(fig)
    buf.seek(0)
    return buf
