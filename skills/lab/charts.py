import asyncio
import io
from dataclasses import dataclass
from typing import Literal

import aiohttp
import discord
from discord import app_commands

from skills.lab import data
from skills.lab.common import LabError, lab, note

QUICKCHART_URL = "https://quickchart.io/chart"
QUICKCHART_TIMEOUT = 15  # seconds

# Sized for a Discord embed; rendered at double density so it stays sharp on phones
WIDTH, HEIGHT, SCALE = 800, 380, 2

# Dark chart surface, to sit well in Discord's dark theme. One series per chart,
# each with its own fixed colour.
SURFACE = "#1a1a19"
INK = "#ffffff"
INK_SECONDARY = "#c3c2b7"
INK_MUTED = "#898781"
GRID = "#2c2c2a"
BASELINE = "#383835"
COLOUR_MESSAGES = "#3987e5"
COLOUR_COST = "#d95926"


@dataclass(frozen=True)
class ChartSpec:
    """One bar chart: a single series over consecutive days."""

    filename: str
    title: str
    subtitle: str
    labels: list[str]
    values: list[float]
    colour: str
    decimals: int  # 0 for counts, more for money

    def format(self, value: float) -> str:
        return f"{value:,.{self.decimals}f}"

    @property
    def peak(self) -> int | None:
        """Index of the highest bar (the one that gets a label), or None if all are zero."""
        if not self.values or max(self.values) <= 0:
            return None
        return self.values.index(max(self.values))


def build_specs(stats: list[data.DayStats]) -> list[ChartSpec]:
    """Two charts rather than one with two scales: messages per day and cost per day."""
    labels = [f"{day.day.day} {day.day:%b}" for day in stats]
    total_messages = sum(day.messages for day in stats)
    total_cost = sum(day.cost for day in stats)
    return [
        ChartSpec(
            filename="messages.png",
            title="Messages per day",
            subtitle=f"{total_messages:,} chat messages in the last {len(stats)} days",
            labels=labels,
            values=[day.messages for day in stats],
            colour=COLOUR_MESSAGES,
            decimals=0,
        ),
        ChartSpec(
            filename="cost.png",
            title="Cost per day (US$)",
            subtitle=f"US${total_cost:,.4f} estimated in the last {len(stats)} days",
            labels=labels,
            values=[round(day.cost, 4) for day in stats],
            colour=COLOUR_COST,
            decimals=4,
        ),
    ]


def _label_step(count: int) -> int:
    """Show every nth date so the axis never gets crowded."""
    return max(1, -(-count // 8))


# ---------------------------------------------------------------------------
# Renderer 1: QuickChart (a web service that draws a Chart.js config)
# ---------------------------------------------------------------------------
def quickchart_config(spec: ChartSpec) -> dict:
    step = _label_step(len(spec.labels))
    peak = spec.peak
    return {
        "version": "4",
        "width": WIDTH,
        "height": HEIGHT,
        "devicePixelRatio": SCALE,
        "format": "png",
        "backgroundColor": SURFACE,
        "chart": {
            "type": "bar",
            "data": {
                # Blank out the dates we don't want on the axis
                "labels": [
                    label if index % step == 0 else "" for index, label in enumerate(spec.labels)
                ],
                "datasets": [
                    {
                        "label": spec.title,
                        "data": spec.values,
                        "backgroundColor": spec.colour,
                        "borderRadius": 4,
                        "borderSkipped": "bottom",
                        "maxBarThickness": 28,
                        "categoryPercentage": 0.8,
                        "barPercentage": 0.9,
                    }
                ],
            },
            "options": {
                "layout": {"padding": {"top": 8, "right": 16, "bottom": 8, "left": 8}},
                "plugins": {
                    "legend": {"display": False},
                    "title": {
                        "display": True,
                        "text": spec.title,
                        "align": "start",
                        "color": INK,
                        "font": {"size": 18, "weight": "bold"},
                        "padding": {"bottom": 2},
                    },
                    "subtitle": {
                        "display": True,
                        "text": spec.subtitle,
                        "align": "start",
                        "color": INK_SECONDARY,
                        "font": {"size": 13},
                        "padding": {"bottom": 18},
                    },
                    # Label the highest bar only
                    "datalabels": {
                        "display": [index == peak for index in range(len(spec.values))],
                        "anchor": "end",
                        "align": "end",
                        "offset": 2,
                        "color": INK,
                        "font": {"size": 12, "weight": "bold"},
                    },
                },
                "scales": {
                    "x": {
                        "grid": {"display": False},
                        "border": {"color": BASELINE},
                        "ticks": {
                            "color": INK_MUTED,
                            "autoSkip": False,
                            "maxRotation": 0,
                            "font": {"size": 12},
                        },
                    },
                    "y": {
                        "beginAtZero": True,
                        "grace": "12%",
                        "grid": {"color": GRID},
                        "border": {"display": False},
                        "ticks": {
                            "color": INK_MUTED,
                            "maxTicksLimit": 5,
                            "precision": 0 if spec.decimals == 0 else spec.decimals,
                            "font": {"size": 12},
                        },
                    },
                },
            },
        },
    }


async def render_quickchart(spec: ChartSpec) -> bytes:
    """Send the chart description to quickchart.io and get a PNG back."""
    timeout = aiohttp.ClientTimeout(total=QUICKCHART_TIMEOUT)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(QUICKCHART_URL, json=quickchart_config(spec)) as response:
                body = await response.read()
                if response.status != 200 or not body.startswith(b"\x89PNG"):
                    raise LabError(
                        f"QuickChart couldn't draw the chart (HTTP {response.status}). "
                        "Try renderer: matplotlib."
                    )
                return body
    except (aiohttp.ClientError, asyncio.TimeoutError) as error:
        raise LabError(
            f"I couldn't reach QuickChart ({type(error).__name__}). Try renderer: matplotlib."
        )


# ---------------------------------------------------------------------------
# Renderer 2: matplotlib (drawn on this machine)
# ---------------------------------------------------------------------------
def _draw_matplotlib(spec: ChartSpec) -> bytes:
    """Blocking: call through render_matplotlib."""
    try:
        from matplotlib.figure import Figure
        from matplotlib.ticker import FuncFormatter, MaxNLocator
    except ImportError:
        raise LabError("matplotlib isn't installed. Run: pip install -r requirements.txt")

    # Figure() directly, not pyplot: pyplot keeps global state and isn't thread-safe
    figure = Figure(figsize=(WIDTH / 100, HEIGHT / 100), dpi=100 * SCALE, facecolor=SURFACE)
    axes = figure.add_axes((0.08, 0.13, 0.89, 0.62), facecolor=SURFACE)

    positions = range(len(spec.values))
    axes.bar(positions, spec.values, width=0.72, color=spec.colour, linewidth=0, zorder=2)

    figure.text(0.03, 0.93, spec.title, color=INK, fontsize=14, fontweight="bold", va="center")
    figure.text(0.03, 0.85, spec.subtitle, color=INK_SECONDARY, fontsize=10, va="center")

    # Quiet axes: horizontal hairlines and a baseline, nothing else
    for side in ("top", "right", "left"):
        axes.spines[side].set_visible(False)
    axes.spines["bottom"].set_color(BASELINE)
    axes.grid(axis="y", color=GRID, linewidth=0.8, zorder=0)
    axes.set_axisbelow(True)
    axes.tick_params(axis="both", colors=INK_MUTED, labelsize=9, length=0, pad=6)

    step = _label_step(len(spec.labels))
    shown = [index for index in positions if index % step == 0]
    axes.set_xticks(shown, [spec.labels[index] for index in shown])
    axes.set_xlim(-0.6, len(spec.values) - 0.4)

    top = max(spec.values, default=0)
    axes.set_ylim(0, top * 1.15 if top > 0 else 1)
    axes.yaxis.set_major_locator(MaxNLocator(nbins=4, integer=spec.decimals == 0))
    if spec.decimals:
        axes.yaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:g}"))

    # Label the highest bar only
    if spec.peak is not None:
        axes.annotate(
            spec.format(spec.values[spec.peak]),
            (spec.peak, spec.values[spec.peak]),
            xytext=(0, 4),
            textcoords="offset points",
            ha="center",
            va="bottom",
            color=INK,
            fontsize=9,
            fontweight="bold",
        )

    buffer = io.BytesIO()
    figure.savefig(buffer, format="png", facecolor=SURFACE)
    return buffer.getvalue()


async def render_matplotlib(spec: ChartSpec) -> bytes:
    # Drawing takes a moment, so keep it off the event loop
    return await asyncio.to_thread(_draw_matplotlib, spec)


RENDERERS = {
    "quickchart": render_quickchart,
    "matplotlib": render_matplotlib,
}


# ---------------------------------------------------------------------------
# /lab chart
# ---------------------------------------------------------------------------
@lab.command(name="chart", description="Messages per day and cost per day, as charts")
@app_commands.describe(
    renderer="QuickChart draws it on the web; matplotlib draws it on the server",
    days="How many days to show, ending today",
)
async def chart(
    interaction: discord.Interaction,
    renderer: Literal["quickchart", "matplotlib"] = "quickchart",
    days: app_commands.Range[int, 3, 90] = 14,
):
    await interaction.response.defer()
    specs = build_specs(await data.daily_stats(days))
    images = await asyncio.gather(*(RENDERERS[renderer](spec) for spec in specs))

    embeds, files = [], []
    for spec, image in zip(specs, images):
        embed = discord.Embed(
            title=spec.title, description=spec.subtitle, colour=discord.Colour.from_str(spec.colour)
        )
        embed.set_image(url=f"attachment://{spec.filename}")
        embed.set_footer(text=f"Drawn with {renderer} · /lab file has the numbers")
        embeds.append(embed)
        files.append(discord.File(io.BytesIO(image), filename=spec.filename))

    await interaction.followup.send(embeds=embeds, files=files)
    note(
        interaction,
        f"posted 2 charts for {days} days with {renderer} "
        f"({sum(len(image) for image in images) // 1024} KB)",
    )
