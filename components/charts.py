"""Plotly figure builders for the dashboard (the batch-card zones are built in main.py)."""
import plotly.graph_objects as go

PALETTE = ["#0ea5e9", "#f97316", "#22c55e", "#a855f7", "#ef4444", "#14b8a6"]

# Plotly draws its own SVG text and does not inherit the page font, so every figure names the
# family itself. Keep this stack in sync with `--font-sans` in assets/input.pcss.
FONT_FAMILY = '"IBM XGA-AI 12x20", ui-monospace, "SFMono-Regular", Menlo, Consolas, monospace'

# The data points the chart can draw, in the order the checkboxes list them. One table drives the
# checkbox list (`main.py`), the traces and the y-axis titles here. Field = the key of a series
# point (the SQL alias in `main.py`); label = the checkbox name, kept to **two characters** because
# the control row is narrow; dash distinguishes the metrics that share an experiment's colour.
METRICS = {
    "gravity":     ("°P", "gravity_plato", "%{y:.1f} °P",  "solid"),
    "temperature": ("°C", "temp_c",        "%{y:.1f} °C",  "dot"),
    "tilt":        ("°",  "tilt_deg",      "%{y:.1f} °",   "dash"),
    "battery":     ("V",  "battery_v",     "%{y:.2f} V",   "dashdot"),
    "interval":    ("s",  "interval_s",    "%{y:.0f} s",   "longdash"),
    "rssi":        ("dB", "rssi_dbm",      "%{y:.0f} dBm", "longdashdot"),
}
DEFAULT_METRICS = ("gravity", "temperature")

# More than this many transmission intervals without data is a **gap** - the same "more than three
# intervals" rule FR-19 uses to call a device stale. The line is broken there instead of being
# interpolated over (Plotly does not connect across a `None`), so an iSpindel that was silent for
# hours or days does not read as a smooth fermentation.
GAP_INTERVALS = 3


def gap_breaks(points):
    """The indices whose point follows a gap, so the line is broken before it.

    The reference interval is the one the iSpindels report (`interval_s`, FR-11 - it may differ per
    device: 1 min, 15 min, 30 min), so the same rule fits every device. Without a reported interval
    the median distance between the points is used. Fewer than two points -> no break.
    """
    if len(points) < 2:
        return set()
    intervals = sorted(p["interval_s"] for p in points if p.get("interval_s"))
    if intervals:
        reference = intervals[len(intervals) // 2]
    else:
        deltas = sorted((points[i]["recorded_at"] - points[i - 1]["recorded_at"]).total_seconds()
                        for i in range(1, len(points)))
        reference = deltas[len(deltas) // 2]
    if not reference:
        return set()
    limit = GAP_INTERVALS * reference
    return {i for i in range(1, len(points))
            if (points[i]["recorded_at"] - points[i - 1]["recorded_at"]).total_seconds() > limit}


def padded(values, breaks):
    """`values` with a `None` inserted before every index in `breaks` - that `None` is the break."""
    out = []
    for i, value in enumerate(values):
        if i in breaks:
            out.append(None)
        out.append(value)
    return out


def fermentation_figure(series, relative=False, height=460, legend=True, mobile=False,
                        x_range=None, metrics=DEFAULT_METRICS):
    """The selected data points over time - gravity, temperature, tilt, battery, interval, signal.

    series = [{"label": str, "points": [{"recorded_at", "gravity_plato", "temp_c", "tilt_deg",
    "battery_v", "interval_s", "rssi_dbm"}]}]. `metrics` are the keys of METRICS to draw (any
    combination; the default is gravity + temperature). The units differ - °P, °C, °, V, s, dBm - so
    every metric gets its **own y axis**: the first on the left, the others stacked on the right.
    The **colour** still identifies the experiment (FR-15/FR-17), the **line style** the metric.

    relative=True counts hours since the start of each experiment (FR-18). height=None autosizes
    to the container. `legend`/`mobile` hide the legend; mobile also shortens the axis titles
    (NFR-06). x_range = (start, end) pins the x axis to the selected time range (FR-16) so the
    empty time before an experiment's first measurement stays visible; ignored when `relative`.

    The hover readout is Plotly's **built-in** unified tooltip: with `hovermode="x"` it prints every
    trace at the hovered timepoint in one box, so no second callback has to follow the pointer.
    """
    selected = [m for m in METRICS if m in (metrics or ())]   # METRICS order, unknown keys dropped
    if mobile:
        legend = False
    if relative:
        xaxis_title = "hours" if mobile else "hours since start"
    else:
        xaxis_title = "time" if mobile else "time (local)"

    fig = go.Figure()
    for i, s in enumerate(series):
        points = s["points"]
        color = PALETTE[i % len(PALETTE)]
        if relative and points:
            t0 = points[0]["recorded_at"]
            x = [(p["recorded_at"] - t0).total_seconds() / 3600 for p in points]
        else:
            x = [p["recorded_at"] for p in points]
        # a data gap breaks the line instead of being interpolated over
        breaks = gap_breaks(points)
        x = padded(x, breaks)
        # markers turn a dense series into a fat band - draw them on the first metric only, and
        # only while they stay readable
        markers = len(points) <= 200
        # the tooltip prints the **value and its unit** only: no x (date/time) and no series name
        # (`<extra></extra>` closes Plotly's secondary name box). Its background is the colour of
        # the group, so the label belongs to the curve under the pointer at a glance.
        tip = dict(bgcolor=color, bordercolor=color, font=dict(color="#ffffff", size=11))
        for k, metric in enumerate(selected):
            label, field, hover, dash = METRICS[metric]
            fig.add_trace(go.Scatter(
                x=x, y=padded([p.get(field) for p in points], breaks),
                yaxis="y" if k == 0 else f"y{k + 1}",
                name=f"{s['label']} ({label})", hovertemplate=hover + "<extra></extra>",
                hoverlabel=tip,
                mode="lines+markers" if (markers and k == 0) else "lines",
                line=dict(color=color, dash=dash),
                marker=dict(size=5, color=color, line=dict(width=1, color="white"))))

    if not series:
        fig.add_annotation(text="no measurements yet", showarrow=False,
                           font=dict(color="#94a3b8"))

    fig.update_layout(
        height=height,
        # autosize stays True even with a fixed height: Plotly then takes the **width** from the
        # container and only keeps `height`. With `autosize=height is None` the main chart (height
        # 460) fell back to Plotly's ~700 px default width and covered only half of a wide card.
        autosize=True,
        # automargin on the axes grows these only as far as the tick labels and titles
        # need - that keeps the plot area as large as possible on a phone
        margin=dict(l=2 if mobile else 6, r=2 if mobile else 6,
                    t=28 if legend else 4, b=6),
        showlegend=legend,
        font=dict(family=FONT_FAMILY, size=10 if mobile else 12),
        # built-in tooltip, one label per trace at the hovered x (the px / hovermode="x" recipe)
        hovermode="x",
        hoverlabel=dict(bgcolor="#0f172a", bordercolor="#0f172a", namelength=-1,
                        font=dict(color="#f8fafc", size=11)),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        # transparent so the card's background (and its hover colour) shows through
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    # the spike marks the hovered point on the x axis; range=None means Plotly autoscale (FR-16)
    fig.update_xaxes(title_text=xaxis_title, automargin=True,
                     showspikes=True, spikemode="across", spikesnap="data",
                     spikethickness=1.5, spikecolor="#0f172a", spikedash="solid",
                     range=[x_range[0], x_range[1]] if (x_range and not relative) else None)
    # one y axis per metric (their units differ): the first on the left, the others **overlaid** on
    # the right. Plotly requires an overlaid axis' `position` to stay inside [0, 1], so with more
    # than two metrics the further axes step inward from the right edge - the classic Plotly
    # multi-axis look the "Show" boxes are for.
    step = 0.07 if not mobile else 0.11
    for k, metric in enumerate(selected):
        if k == 0:
            fig.update_yaxes(title_text=METRICS[metric][0], automargin=True)
        else:
            fig.update_layout(**{f"yaxis{k + 1}": dict(
                title_text=METRICS[metric][0], overlaying="y", side="right", anchor="free",
                position=1 - step * (k - 1), automargin=True, showgrid=False,
                tickfont=dict(size=10 if mobile else 11))})
    return fig
