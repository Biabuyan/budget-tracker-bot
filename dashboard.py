"""
dashboard.py — Generate spending dashboard image for Telegram
"""

import io
import logging
from datetime import datetime
from typing import Optional

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


def _fig_setup(rows: int, cols: int, title: str):
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
) -> io.BytesIO:
    """Return a BytesIO PNG of the full dashboard."""

    now = datetime.now()
    title = f"💰  Budget Dashboard — {now.strftime('%B %Y')}"
    fig = _fig_setup(2, 2, title)

    gs = gridspec.GridSpec(
        2, 3,
        figure=fig,
        hspace=0.45,
        wspace=0.35,
        top=0.91, bottom=0.07,
        left=0.07, right=0.97,
    )

    total_spent = sum(r["total"] for r in category_totals)
    remaining   = monthly_budget - total_spent
    pct_used    = (total_spent / monthly_budget * 100) if monthly_budget else 0

    # ── 1. KPI header cards ────────────────────────────────────
    ax_kpi = fig.add_subplot(gs[0, :])
    ax_kpi.set_xlim(0, 1)
    ax_kpi.set_ylim(0, 1)
    ax_kpi.axis("off")

    cards = [
        ("Total Spent",     f"{currency}{total_spent:,.2f}",  ACCENT),
        ("Remaining",       f"{currency}{remaining:,.2f}",    GREEN if remaining >= 0 else RED),
        ("Budget",          f"{currency}{monthly_budget:,.2f}", TEXT_COLOR),
        ("% Used",          f"{pct_used:.1f}%",               GREEN if pct_used < 80 else RED),
        ("Transactions",    str(sum(r["count"] for r in category_totals)), TEXT_COLOR),
    ]

    card_w, card_h = 0.17, 0.75
    spacing = 0.19
    x_start = 0.025
    for i, (label, value, color) in enumerate(cards):
        x = x_start + i * spacing
        rect = FancyBboxPatch(
            (x, 0.1), card_w, card_h,
            boxstyle="round,pad=0.02",
            facecolor=CARD_COLOR, edgecolor=color, linewidth=1.5,
            transform=ax_kpi.transAxes
        )
        ax_kpi.add_patch(rect)
        ax_kpi.text(x + card_w / 2, 0.64, value, ha="center", va="center",
                    color=color, fontsize=14, fontweight="bold",
                    transform=ax_kpi.transAxes)
        ax_kpi.text(x + card_w / 2, 0.28, label, ha="center", va="center",
                    color="#9999AA", fontsize=8,
                    transform=ax_kpi.transAxes)

    # ── 2. Category pie chart ─────────────────────────────────
    ax_pie = fig.add_subplot(gs[1, 0])
    ax_pie.set_facecolor(CARD_COLOR)

    if category_totals:
        labels  = [r["category"] for r in category_totals]
        amounts = [r["total"]    for r in category_totals]
        colors  = PALETTE[:len(labels)]
        wedges, _, autotexts = ax_pie.pie(
            amounts, labels=None, colors=colors,
            autopct="%1.1f%%", startangle=140,
            pctdistance=0.78,
            wedgeprops=dict(linewidth=1.5, edgecolor=BG_COLOR),
        )
        for at in autotexts:
            at.set_color(TEXT_COLOR)
            at.set_fontsize(7)
        ax_pie.legend(
            wedges, [f"{l} ({currency}{a:,.0f})" for l, a in zip(labels, amounts)],
            loc="lower center", bbox_to_anchor=(0.5, -0.28),
            fontsize=6.5, ncol=2, framealpha=0,
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
        days    = [r["date"][-2:] for r in daily_totals]   # day number
        amounts = [r["total"]     for r in daily_totals]
        bars = ax_daily.bar(days, amounts, color=ACCENT, alpha=0.85,
                            edgecolor=BG_COLOR, linewidth=0.8)
        today_day = str(now.day)
        for bar, day in zip(bars, days):
            if day == today_day.zfill(2) or day == today_day:
                bar.set_color(GREEN)
        ax_daily.set_xlabel("Day of month", color="#9999AA", fontsize=8)
        ax_daily.set_ylabel(f"Amount ({currency})", color="#9999AA", fontsize=8)
        ax_daily.tick_params(colors="#9999AA", labelsize=7)
        ax_daily.yaxis.set_major_formatter(mticker.FuncFormatter(
            lambda v, _: f"{currency}{v:,.0f}"))
        ax_daily.spines[["top", "right"]].set_visible(False)
        for spine in ["bottom", "left"]:
            ax_daily.spines[spine].set_color("#333355")
        ax_daily.set_facecolor(CARD_COLOR)
        # avg line
        avg = sum(amounts) / len(amounts)
        ax_daily.axhline(avg, color=RED, linestyle="--", linewidth=1,
                         label=f"Avg {currency}{avg:,.0f}")
        ax_daily.legend(fontsize=7, framealpha=0, labelcolor=TEXT_COLOR)
    else:
        ax_daily.text(0.5, 0.5, "No data", ha="center", va="center",
                      color=TEXT_COLOR, transform=ax_daily.transAxes)

    ax_daily.set_title("Daily Spending", color=TEXT_COLOR, fontsize=11, pad=8)

    # ── 4. Monthly trend line chart ───────────────────────────
    ax_trend = fig.add_subplot(gs[1, 2])
    ax_trend.set_facecolor(CARD_COLOR)

    if monthly_trend:
        trend = list(reversed(monthly_trend))   # oldest → newest
        months  = [r["month"][5:]  for r in trend]  # MM
        amounts = [r["total"]      for r in trend]
        ax_trend.plot(months, amounts, color=ACCENT, linewidth=2.5,
                      marker="o", markersize=6, markerfacecolor=GREEN)
        ax_trend.fill_between(months, amounts, alpha=0.15, color=ACCENT)
        ax_trend.axhline(monthly_budget, color=RED, linestyle="--",
                         linewidth=1, label=f"Budget {currency}{monthly_budget:,.0f}")
        ax_trend.set_xlabel("Month", color="#9999AA", fontsize=8)
        ax_trend.set_ylabel(f"Spent ({currency})", color="#9999AA", fontsize=8)
        ax_trend.tick_params(colors="#9999AA", labelsize=7)
        ax_trend.yaxis.set_major_formatter(mticker.FuncFormatter(
            lambda v, _: f"{currency}{v:,.0f}"))
        ax_trend.spines[["top", "right"]].set_visible(False)
        for spine in ["bottom", "left"]:
            ax_trend.spines[spine].set_color("#333355")
        ax_trend.legend(fontsize=7, framealpha=0, labelcolor=TEXT_COLOR)
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
