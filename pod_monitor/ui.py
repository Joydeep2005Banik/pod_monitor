import asyncio
from typing import List, Optional
from datetime import datetime

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
from textual.widgets import Header, Footer, RichLog, Static, ListView, ListItem, Label
from textual.binding import Binding
from textual.reactive import reactive
from textual import events, work

from .models import PodStatus, Anomaly, LogLevel, Severity


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bar(value: float, width: int = 12) -> str:
    """Render an ASCII bar like  [||||||       ] 48.2%"""
    clamped = max(0.0, min(100.0, value))
    filled = int(round(clamped / 100 * width))
    empty = width - filled

    # Color the filled portion based on utilisation
    if clamped >= 80:
        color = "red"
    elif clamped >= 60:
        color = "yellow"
    else:
        color = "green"

    bar_str = f"[{color}]{'|' * filled}[/{color}]{' ' * empty}"
    return f"\\[{bar_str}] {clamped:5.1f}%"


def _status_tag(healthy: bool) -> str:
    """Return a colored status tag — no emoji."""
    if healthy:
        return "[green]\\[OK][/green]"
    return "[red]\\[!!][/red]"


def _severity_tag(severity: Severity) -> str:
    """Return a colored severity tag — no emoji."""
    mapping = {
        Severity.CRITICAL: ("[red bold]", "\\[CRIT]"),
        Severity.HIGH:     ("[#f0883e]", "\\[HIGH]"),
        Severity.MEDIUM:   ("[yellow]",  "\\[MED]"),
        Severity.LOW:      ("[cyan]",    "\\[LOW]"),
    }
    opening, label = mapping.get(severity, ("[white]", "\\[???]"))
    closing = opening.replace("[", "[/", 1)
    return f"{opening}{label}{closing}"


def _log_level_tag(level: LogLevel) -> str:
    """Return a colored log-level tag — no emoji."""
    mapping = {
        LogLevel.CRITICAL: ("[red bold]",  "CRIT"),
        LogLevel.ERROR:    ("[red]",       "ERR "),
        LogLevel.WARNING:  ("[yellow]",    "WARN"),
        LogLevel.INFO:     ("[white]",     "INFO"),
        LogLevel.DEBUG:    ("[dim]",       "DBG "),
    }
    opening, label = mapping.get(level, ("[white]", "INFO"))
    closing = opening.replace("[", "[/", 1)
    return f"{opening}{label}{closing}"


def _format_age(seconds: float) -> str:
    """Format an uptime/age value into a compact human-readable string.

    Examples: ``3d 4h``, ``2h 15m``, ``45m``, ``12s``.
    """
    if seconds <= 0:
        return "--"
    days, rem = divmod(int(seconds), 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


# ---------------------------------------------------------------------------
# Widgets
# ---------------------------------------------------------------------------

class LogViewer(RichLog):
    """Log viewer with colored output — no emoji."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("markup", True)
        super().__init__(*args, **kwargs)

    def add_log(self, message: str, level: LogLevel = LogLevel.INFO):
        """Add a colored log message.

        The *message* is expected to contain Rich markup already
        (e.g. from ``_log_level_tag``), so we write it directly.
        """
        self.write(message)


class PodListItem(ListItem):
    """Pod list item — uses colored text tags instead of emoji."""

    def __init__(self, pod_status: PodStatus):
        self.pod_status = pod_status
        ip_suffix = f"  {pod_status.ip}" if pod_status.ip and pod_status.ip != pod_status.name else ""
        label = f"{_status_tag(pod_status.healthy)}  {pod_status.name}{ip_suffix}"
        super().__init__(Label(label, markup=True))

    def update_status(self, pod_status: PodStatus):
        """Update the displayed status."""
        self.pod_status = pod_status
        ip_suffix = f"  {pod_status.ip}" if pod_status.ip and pod_status.ip != pod_status.name else ""
        label = f"{_status_tag(pod_status.healthy)}  {pod_status.name}{ip_suffix}"
        self.children[0].update(label)


# ---------------------------------------------------------------------------
# Main Application
# ---------------------------------------------------------------------------

class PodMonitorUI(App):
    CSS = """
    Screen {
        background: #0d1117;
    }

    Header {
        background: #161b22;
        color: #c9d1d9;
    }

    Footer {
        background: #161b22;
        color: #8b949e;
    }

    #grid {
        height: 1fr;
        margin: 0 1;
    }

    /* ---- top row ---- */
    #top-row {
        height: 55%;
    }

    #pod-panel {
        width: 55%;
        background: #0d1117;
        border: round #30363d;
        margin: 0 1 0 0;
    }

    #metrics-panel {
        width: 45%;
        background: #0d1117;
        border: round #30363d;
    }

    /* ---- bottom row ---- */
    #bottom-row {
        height: 45%;
        margin-top: 1;
    }

    #log-panel {
        width: 55%;
        background: #0d1117;
        border: round #30363d;
        margin: 0 1 0 0;
    }

    #ai-panel {
        width: 45%;
        background: #0d1117;
        border: round #30363d;
    }

    /* ---- inner content ---- */
    .panel-title {
        color: #58a6ff;
        text-style: bold;
        padding: 0 1;
    }

    #pod-list {
        height: 1fr;
        background: #0d1117;
        scrollbar-size: 1 1;
    }

    #log-view {
        height: 1fr;
        background: #0d1117;
        scrollbar-size: 1 1;
    }

    #metrics-content {
        height: 1fr;
        padding: 0 1;
        overflow-y: auto;
    }

    #ai-content {
        height: 1fr;
        padding: 0 1;
        overflow-y: auto;
    }

    .metric-row {
        color: #c9d1d9;
    }

    .anomaly-entry {
        margin-bottom: 1;
    }

    .suggestion {
        color: #8b949e;
        padding-left: 2;
    }

    .no-anomalies {
        color: #3fb950;
        text-style: italic;
        margin: 1;
    }

    ListView > ListItem {
        background: #0d1117;
        padding: 0 1;
    }

    ListView > ListItem.--highlight {
        background: #161b22;
    }

    ListView:focus > ListItem.--highlight {
        background: #1f2937;
    }
    """

    TITLE = "Pod Monitor"

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("up", "cursor_up", "Up", show=False),
        Binding("down", "cursor_down", "Down", show=False),
        Binding("enter", "select_pod", "Select"),
        Binding("r", "refresh", "Refresh"),
        Binding("a", "toggle_ai", "Toggle AI"),
    ]

    def __init__(self, monitor):
        super().__init__()
        self.monitor = monitor
        self.selected_pod: Optional[PodStatus] = None
        self.ai_enabled = True
        self.pod_list_items: List[PodListItem] = []

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)

        with Vertical(id="grid"):
            # ── Top row ──
            with Horizontal(id="top-row"):
                with Container(id="pod-panel"):
                    yield Static("[ Pods ]", classes="panel-title")
                    yield ListView(id="pod-list")
                with Container(id="metrics-panel"):
                    yield Static("[ Metrics ]", classes="panel-title")
                    yield ScrollableContainer(id="metrics-content")

            # ── Bottom row ──
            with Horizontal(id="bottom-row"):
                with Container(id="log-panel"):
                    yield Static("[ Logs ]", classes="panel-title")
                    yield LogViewer(id="log-view")
                with Container(id="ai-panel"):
                    yield Static("[ AI Insights ]", classes="panel-title")
                    yield ScrollableContainer(id="ai-content")

        yield Footer()

    async def on_mount(self):
        """Set up the UI."""
        pod_list = self.query_one("#pod-list", ListView)

        for pod in await self.monitor.get_all_pods():
            item = PodListItem(pod)
            self.pod_list_items.append(item)
            await pod_list.append(item)

        # Select first pod
        if self.pod_list_items:
            pod_list.index = 0
            await self.select_pod(self.pod_list_items[0])

        # Start background updates
        self.set_interval(2, self.update_ui)

    async def update_ui(self):
        """Update all UI components."""
        pod_list = self.query_one("#pod-list", ListView)
        pods = await self.monitor.get_all_pods()

        # Update list items
        for item, pod in zip(self.pod_list_items, pods):
            item.update_status(pod)

        # Update selected pod view
        if self.selected_pod:
            for pod in pods:
                if pod.ip == self.selected_pod.ip:
                    self.selected_pod = pod
                    await self.update_pod_view(pod)
                    break

    async def update_pod_view(self, pod: PodStatus):
        """Update the detailed view for a pod."""
        # ── Logs ──
        log_view = self.query_one("#log-view", LogViewer)
        log_view.clear()
        for log in pod.logs[-50:]:
            timestamp = log.timestamp.strftime("%H:%M:%S")
            tag = _log_level_tag(log.level)
            log_view.add_log(f"[dim]{timestamp}[/dim] {tag} {log.message}", log.level)

        # ── Metrics ──
        metrics_panel = self.query_one("#metrics-content", ScrollableContainer)
        metrics_panel.remove_children()

        m = pod.metrics

        # Restart count — highlight in red when non-zero
        rst_val = pod.restarts
        if rst_val > 0:
            rst_display = f"[red]{rst_val}[/red]"
        else:
            rst_display = f"[green]{rst_val}[/green]"

        node_display = pod.node_name or "[dim]unknown[/dim]"
        age_display = _format_age(m.uptime)

        # Phase color
        phase_raw = pod.phase or "Unknown"
        phase_colors = {
            "Running": "green", "Succeeded": "green",
            "Pending": "yellow", "ContainerCreating": "yellow",
            "Failed": "red", "CrashLoopBackOff": "red",
            "Unknown": "dim",
        }
        pc = phase_colors.get(phase_raw, "white")
        phase_display = f"[{pc}]{phase_raw}[/{pc}]"

        # Pod IP
        ip_display = pod.pod_ip or "[dim]n/a[/dim]"

        # Image — strip registry prefix for brevity
        img = pod.image or ""
        if "/" in img:
            img = img.rsplit("/", 1)[-1]
        img_display = img or "[dim]n/a[/dim]"

        # Labels
        lbl_display = pod.labels or "[dim]none[/dim]"

        mem_pct = m.memory_usage / max(m.memory_limit, 1) * 100

        metrics_panel.mount(
            Static(f"CPU  {_bar(m.cpu_usage)}", classes="metric-row", markup=True),
            Static(f"MEM  {_bar(mem_pct)}", classes="metric-row", markup=True),
            Static(f"ERR  {_bar(m.error_rate)}", classes="metric-row", markup=True),
            Static(f"CONN {m.active_connections}  REQ {m.request_rate:.1f}/s", classes="metric-row", markup=True),
            Static(f"RST  {rst_display}  NODE {node_display}", classes="metric-row", markup=True),
            Static(f"AGE  {age_display}  STS {phase_display}", classes="metric-row", markup=True),
            Static(f"IP   {ip_display}", classes="metric-row", markup=True),
            Static(f"IMG  {img_display}", classes="metric-row", markup=True),
            Static(f"APP  {lbl_display}", classes="metric-row", markup=True),
        )

        # ── AI Insights ──
        ai_panel = self.query_one("#ai-content", ScrollableContainer)
        ai_panel.remove_children()

        if pod.anomalies:
            for anomaly in pod.anomalies[:5]:
                tag = _severity_tag(anomaly.severity)
                ai_panel.mount(
                    Static(
                        f"{tag} {anomaly.description}",
                        classes="anomaly-entry",
                        markup=True,
                    ),
                )
                if anomaly.suggestion:
                    ai_panel.mount(
                        Static(
                            f"  > {anomaly.suggestion}",
                            classes="suggestion",
                        ),
                    )
        else:
            ai_panel.mount(
                Static("-- No anomalies detected --", classes="no-anomalies")
            )

    async def on_list_view_selected(self, event: ListView.Selected):
        """Handle pod selection."""
        await self.select_pod(event.item)

    async def select_pod(self, item):
        """Select a pod and update the view."""
        if hasattr(item, "pod_status"):
            self.selected_pod = item.pod_status
            await self.update_pod_view(self.selected_pod)

    def action_select_pod(self):
        """Select the currently highlighted pod."""
        list_view = self.query_one("#pod-list", ListView)
        if list_view.children:
            list_view.index = (list_view.index + 1) % len(list_view.children)

    def action_cursor_up(self):
        """Move cursor up in pod list."""
        list_view = self.query_one("#pod-list", ListView)
        if list_view.index > 0:
            list_view.index -= 1

    def action_cursor_down(self):
        """Move cursor down in pod list."""
        list_view = self.query_one("#pod-list", ListView)
        if list_view.index < len(list_view.children) - 1:
            list_view.index += 1

    def action_refresh(self):
        """Manually refresh the view."""
        self.update_ui()

    def action_toggle_ai(self):
        """Toggle AI analysis on/off."""
        self.ai_enabled = not self.ai_enabled

        # Guard against mock monitor with no config
        if hasattr(self.monitor, "config") and self.monitor.config is not None:
            self.monitor.config.ai.enabled = self.ai_enabled
        if hasattr(self.monitor, "ai_analyzer"):
            self.monitor.ai_analyzer.mock_mode = not self.ai_enabled

        status = "enabled" if self.ai_enabled else "disabled"
        self.notify(f"AI analysis {status}", title="AI Status")

    def action_quit(self):
        """Quit the application."""
        self.exit()