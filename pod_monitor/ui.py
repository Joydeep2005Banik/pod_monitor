import asyncio
import re
import random
from typing import List, Optional
from datetime import datetime, timezone, timedelta

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
from textual.widgets import RichLog, Static, ListView, ListItem, Label
from textual.binding import Binding
from textual.reactive import reactive
from textual import events, work

from .models import PodStatus, Anomaly, LogLevel, Severity

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sparkline(history: List[float], length: int = 12) -> str:
    """Render a Unicode sparkline (e.g. ▂▃▄▅▆▇█) from history."""
    if not history:
        return " " * length
    history = history[-length:]
    if len(history) < length:
        history = [0.0] * (length - len(history)) + history
    
    blocks = " ▂▃▄▅▆▇█"
    spark = []
    for val in history:
        clamped = max(0.0, min(100.0, val))
        idx = int(clamped / 100 * (len(blocks) - 1))
        spark.append(blocks[idx])
    return "".join(spark)


def make_bar(ratio: float, width: int = 12) -> str:
    """Render a simple visual bar using block characters."""
    ratio = max(0.0, min(1.0, ratio))
    filled = int(round(ratio * width))
    bar_str = "[cyan]" + "█" * filled + "[/cyan]" + "[#333333]" + "░" * (width - filled) + "[/#333333]"
    return f"{bar_str} {ratio * 100:5.1f}%"


def _bar(value: float, width: int = 12) -> str:
    """Render a high-density progress bar with color gradient and density blocks."""
    clamped = max(0.0, min(100.0, value))
    filled = int(round(clamped / 100 * width))
    empty = width - filled

    filled_blocks = []
    for i in range(filled):
        t = i / (width - 1) if width > 1 else 0.0
        # Density character selection: ░ -> ▒ -> ▓ -> █
        if t < 0.25:
            char = "░"
        elif t < 0.5:
            char = "▒"
        elif t < 0.75:
            char = "▓"
        else:
            char = "█"
        
        # Color interpolation: dark red/brown (#5a1e1e) to bright coral/red (#ff5c5c)
        r = int(90 + t * (255 - 90))
        g = int(30 + t * (92 - 30))
        b = int(30 + t * (92 - 30))
        color = f"#{r:02x}{g:02x}{b:02x}"
        filled_blocks.append(f"[{color}]{char}[/{color}]")
    
    filled_str = "".join(filled_blocks)
    unfilled_str = f"[#333333]{'░' * empty}[/#333333]"
    bar_str = f"{filled_str}{unfilled_str}"
    return f"{bar_str} {clamped:5.1f}%"


def _status_tag(healthy: bool) -> str:
    """Return a colored status tag — no emoji."""
    if healthy:
        return "[bold green]OK[/bold green]"
    return "[bold red]!![/bold red]"


def _severity_tag(severity: Severity) -> str:
    """Return a colored severity tag — no emoji."""
    mapping = {
        Severity.CRITICAL: ("[red bold]", "CRIT"),
        Severity.HIGH:     ("[#f0883e]", "HIGH"),
        Severity.MEDIUM:   ("[yellow]",  "MED "),
        Severity.LOW:      ("[cyan]",    "LOW "),
    }
    opening, label = mapping.get(severity, ("[white]", "??? "))
    closing = opening.replace("[", "[/", 1)
    return f"{opening}\\[{label}]{closing}"


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
    """Format an uptime/age value into a compact human-readable string."""
    if seconds is None:
        return "--"
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
# Custom Widgets
# ---------------------------------------------------------------------------

class TopBar(Static):
    """Btop-style top status bar showing aggregate stats and uptime."""
    
    def __init__(self, monitor, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.monitor = monitor
        self.start_time = datetime.now()

    def on_mount(self):
        self.border_title = "[ monitor info ]"
        self.set_interval(1.0, self.update_clock)
        
    def update_clock(self):
        self.refresh()

    def render(self) -> str:
        uptime_secs = (datetime.now() - self.start_time).total_seconds()
        uptime_str = _format_age(uptime_secs)
        local_time = datetime.now().strftime("%H:%M:%S")
        
        # Aggregate CPU / Memory across all active pods
        pods = getattr(self.app, "pods_cache", [])
        if pods:
            cpu_usages = [p.metrics.cpu_usage for p in pods if p.metrics.cpu_usage is not None]
            avg_cpu = sum(cpu_usages) / len(cpu_usages) if cpu_usages else 0.0
            
            mem_pcts = [(p.metrics.memory_usage / max(p.metrics.memory_limit or 100.0, 1)) * 100 for p in pods if p.metrics.memory_usage is not None]
            avg_mem = sum(mem_pcts) / len(mem_pcts) if mem_pcts else 0.0
        else:
            avg_cpu = 0.0
            avg_mem = 0.0
            
        app = self.app
        if not hasattr(app, "global_cpu_history"):
            app.global_cpu_history = []
            app.global_mem_history = []
            
        app.global_cpu_history.append(avg_cpu)
        app.global_mem_history.append(avg_mem)
        app.global_cpu_history = app.global_cpu_history[-20:]
        app.global_mem_history = app.global_mem_history[-20:]
        
        cpu_spark = _sparkline(app.global_cpu_history, length=12)
        mem_spark = _sparkline(app.global_mem_history, length=12)
        
        if not hasattr(app, "load_avg"):
            app.load_avg = [0.15, 0.22, 0.18]
        app.load_avg = [
            max(0.01, min(2.0, app.load_avg[0] + random.uniform(-0.02, 0.02))),
            max(0.01, min(2.0, app.load_avg[1] + random.uniform(-0.01, 0.01))),
            max(0.01, min(2.0, app.load_avg[2] + random.uniform(-0.005, 0.005))),
        ]
        load_str = f"{app.load_avg[0]:.2f} {app.load_avg[1]:.2f} {app.load_avg[2]:.2f}"
        
        width = self.size.width or 80
        left_text = (
            f" UPTIME: [bold]{uptime_str}[/bold]   "
            f"LOAD: [bold]{load_str}[/bold]   "
            f"CPU: [cyan]{cpu_spark}[/cyan] [bold]{avg_cpu:4.1f}%[/bold]   "
            f"MEM: [cyan]{mem_spark}[/cyan] [bold]{avg_mem:4.1f}%[/bold]"
        )
        plain_left = re.sub(r'\[.*?\]', '', left_text)
        padding = max(2, width - len(plain_left) - len(local_time) - 4)
        return left_text + (" " * padding) + f"[bold #00d2ff]{local_time}[/bold #00d2ff]"


class BottomMenuBar(Static):
    """Custom footer showing hotkeys and actions in btop style."""
    def render(self) -> str:
        return (
            "  [reverse]ENTER[/reverse] select   "
            "[reverse]U[/reverse] info   "
            "[reverse]T[/reverse] terminate   "
            "[reverse]K[/reverse] kill   "
            "[reverse]N[/reverse] nice   "
            "[reverse]R[/reverse] refresh   "
            "[reverse]A[/reverse] toggle ai   "
            "[reverse]Q[/reverse] quit"
        )


class NetworkInfo(Static):
    """Network & Metadata panel displaying IP, Node, Namespace, and status."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.current_pod: Optional[PodStatus] = None

    def update_pod(self, pod: Optional[PodStatus]):
        self.current_pod = pod
        if not pod:
            self.update("\n [dim]No pod selected[/dim]")
            return
        
        status_tag = _status_tag(pod.healthy)
        ip = pod.pod_ip or pod.ip or "n/a"
        node = pod.node_name or "unknown"
        ns = pod.namespace or "default"
        phase = pod.phase or "Unknown"
        
        content = (
            f" [dim]Pod Name: [/dim] [bold]{pod.name}[/bold]\n"
            f" [dim]IP:       [/dim] [cyan]{ip}[/cyan]\n"
            f" [dim]Node:     [/dim] [yellow]{node}[/yellow]\n"
            f" [dim]Namespace:[/dim] [magenta]{ns}[/magenta]\n"
            f" [dim]Status:   [/dim] {status_tag} ({phase})"
        )
        if pod.error_message:
            content += f"\n [dim]API Error:[/dim] [red]{pod.error_message}[/red]"
        self.update(content)


class MetricsTable(Static):
    """btop-style metrics display with high-density graphs and sparklines."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.current_pod: Optional[PodStatus] = None

    def update_pod(self, pod: Optional[PodStatus]):
        self.current_pod = pod
        if not pod:
            self.update("\n [dim]No pod selected[/dim]")
            return
        
        m = pod.metrics
        cpu_val = m.cpu_usage if m.cpu_usage is not None else 0.0
        mem_val = m.memory_usage if m.memory_usage is not None else 0.0
        mem_lim = m.memory_limit if m.memory_limit is not None else 100.0
        
        mem_pct = (mem_val / max(mem_lim, 1)) * 100
        
        app = self.app
        pod_name = pod.name
        if not hasattr(app, "pod_cpu_history"):
            app.pod_cpu_history = {}
            app.pod_mem_history = {}
            
        if pod_name not in app.pod_cpu_history:
            app.pod_cpu_history[pod_name] = []
            app.pod_mem_history[pod_name] = []
            
        app.pod_cpu_history[pod_name].append(cpu_val)
        app.pod_mem_history[pod_name].append(mem_pct)
        app.pod_cpu_history[pod_name] = app.pod_cpu_history[pod_name][-20:]
        app.pod_mem_history[pod_name] = app.pod_mem_history[pod_name][-20:]
        
        cpu_spark = _sparkline(app.pod_cpu_history[pod_name], length=12) if m.cpu_usage is not None else "[dim]N/A[/dim]"
        mem_spark = _sparkline(app.pod_mem_history[pod_name], length=12) if m.memory_usage is not None else "[dim]N/A[/dim]"
        
        cpu_bar = _bar(cpu_val, width=12) if m.cpu_usage is not None else "[red]N/A[/red]"
        
        if m.memory_usage is not None and m.memory_limit is not None and m.memory_limit > 0:
            mem_bar = make_bar(mem_val / m.memory_limit, width=12)
        elif m.memory_usage is not None:
            mem_bar = make_bar(0.0, width=12) # fallback if no limit
        else:
            mem_bar = "[red]N/A[/red]"
        err_bar = _bar(m.error_rate, width=12)
        
        def format_row(label: str, value: str) -> str:
            key_str = f" [dim]{label:<18}[/dim]"
            return f"{key_str} [bold]{value}[/bold]"
        
        rst_val = pod.restarts
        if rst_val is None:
            rst_display = "[dim]N/A[/dim]"
        else:
            rst_display = f"[red]{rst_val}[/red]" if rst_val > 0 else f"[green]{rst_val}[/green]"
            
        if getattr(m, "is_cached", False):
            mem_used_str = f"{mem_val:.2f} MiB (cached)"
        else:
            mem_used_str = f"{mem_val:.2f} MiB" if m.memory_usage is not None else "[dim]N/A[/dim]"
        
        mem_lim_str = f"{mem_lim:.2f} MiB" if m.memory_limit is not None else "[dim]N/A[/dim]"
        uptime_str = _format_age(m.uptime) if m.uptime is not None else "[dim]N/A[/dim]"
        
        rows = [
            "",
            format_row("CPU Usage", cpu_bar),
            format_row("CPU Sparkline", cpu_spark),
            "",
            format_row("Memory Used", mem_used_str),
            format_row("Memory Limit", mem_lim_str),
            format_row("Memory Graph", mem_bar),
            format_row("Memory Sparkline", mem_spark),
            "",
            format_row("Error Rate", err_bar),
            format_row("Restarts", rst_display),
            "",
            format_row("Active Conn", f"{m.active_connections}"),
            format_row("Request Rate", f"{m.request_rate:.1f} req/s"),
            format_row("Uptime / Age", uptime_str),
        ]
        
        self.update("\n".join(rows))


class LogViewer(RichLog):
    """Log viewer with colored output — no emoji."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("markup", True)
        super().__init__(*args, **kwargs)

    def add_log(self, message: str, level: LogLevel = LogLevel.INFO):
        self.write(message)


class PodListItem(ListItem):
    """Pod list item — uses colored text tags instead of emoji."""

    def __init__(self, pod_status: PodStatus):
        self.pod_status = pod_status
        ip_suffix = f"  {pod_status.ip}" if pod_status.ip and pod_status.ip != pod_status.name else ""
        label = f"{_status_tag(pod_status.healthy)}  {pod_status.name}{ip_suffix}"
        super().__init__(Label(label, markup=True))

    def update_status(self, pod_status: PodStatus):
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
        background: #000000;
    }

    #grid {
        height: 1fr;
        margin: 0;
        layout: vertical;
    }

    #top-bar {
        height: 3;
        border: solid #00d2ff;
        background: #000000;
        color: #00d2ff;
        padding: 0 1;
    }

    /* ---- Middle Row ---- */
    #middle-row {
        height: 55fr;
        layout: horizontal;
    }

    #left-column {
        width: 30%;
        height: 100%;
        layout: vertical;
    }

    #pod-panel {
        height: 60%;
        border: solid #00d2ff;
        background: #000000;
    }

    #network-panel {
        height: 40%;
        border: solid #00d2ff;
        background: #000000;
    }

    #metrics-panel {
        width: 70%;
        height: 100%;
        border: solid #00d2ff;
        background: #000000;
    }

    /* ---- Bottom Row ---- */
    #bottom-row {
        height: 45fr;
        layout: horizontal;
    }

    #log-panel {
        width: 60%;
        height: 100%;
        border: solid #00d2ff;
        background: #000000;
    }

    #ai-panel {
        width: 40%;
        height: 100%;
        border: solid #00d2ff;
        background: #000000;
    }

    #bottom-bar {
        height: 1;
        background: #00d2ff;
        color: #000000;
        text-align: left;
    }

    /* ---- inner styles ---- */
    #pod-list {
        height: 1fr;
        background: #000000;
        scrollbar-size: 1 1;
    }

    #log-view {
        height: 1fr;
        background: #000000;
        scrollbar-size: 1 1;
    }

    #ai-content {
        height: 1fr;
        background: #000000;
        scrollbar-size: 1 1;
        padding: 0 1;
    }

    /* Scrollbar override for btop look (cyan/gray) */
    .scrollbar-cursor {
        background: #00d2ff;
    }
    .scrollbar-track {
        background: #262626;
    }

    /* Border titles/subtitles style */
    Container {
        border-title-color: #00d2ff;
        border-title-background: #000000;
        border-title-style: bold;
        border-subtitle-color: #888888;
        border-subtitle-background: #000000;
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
        background: #000000;
        padding: 0 1;
    }

    ListView > ListItem.--highlight {
        background: #111111;
    }

    ListView:focus > ListItem.--highlight {
        background: #222222;
        color: #00d2ff;
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
        Binding("u", "show_info", "Info"),
        Binding("t", "terminate_pod", "Terminate"),
        Binding("k", "kill_pod", "Kill"),
        Binding("n", "nice_pod", "Nice"),
    ]

    def __init__(self, monitor):
        super().__init__()
        self.monitor = monitor
        self.selected_pod: Optional[PodStatus] = None
        self.ai_enabled = True
        self.pod_list_items: List[PodListItem] = []
        self.pods_cache: List[PodStatus] = []

    def compose(self) -> ComposeResult:
        yield TopBar(self.monitor, id="top-bar")

        with Vertical(id="grid"):
            # ── Middle row ──
            with Horizontal(id="middle-row"):
                with Vertical(id="left-column"):
                    with Container(id="pod-panel"):
                        yield ListView(id="pod-list")
                    with Container(id="network-panel"):
                        yield NetworkInfo(id="network-info")
                with Container(id="metrics-panel"):
                    yield MetricsTable(id="metrics-table")

            # ── Bottom row ──
            with Horizontal(id="bottom-row"):
                with Container(id="log-panel"):
                    yield LogViewer(id="log-view")
                with Container(id="ai-panel"):
                    yield ScrollableContainer(id="ai-content")

        yield BottomMenuBar(id="bottom-bar")

    async def on_mount(self):
        """Set up the UI."""
        self.pods_cache = await self.monitor.get_all_pods()
        self.query_one("#pod-panel").border_title = "[ pods ]"
        self.query_one("#pod-panel").border_subtitle = "enter select"
        
        self.query_one("#network-panel").border_title = "[ network info ]"
        
        self.query_one("#metrics-panel").border_title = "[ pod metrics ]"
        self.query_one("#metrics-panel").border_subtitle = "r refresh"
        
        self.query_one("#log-panel").border_title = "[ logs ]"
        self.query_one("#log-panel").border_subtitle = "q quit"
        
        self.query_one("#ai-panel").border_title = "[ ai diagnostics ]"
        self.query_one("#ai-panel").border_subtitle = "a toggle ai"

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
        # Force a full screen refresh to clear any text artifacts
        self.refresh()
        pod_list = self.query_one("#pod-list", ListView)
        pods = await self.monitor.get_all_pods()
        self.pods_cache = pods

        # Update list items
        for item, pod in zip(self.pod_list_items, pods):
            item.update_status(pod)

        # Update selected pod view
        if self.selected_pod:
            for pod in pods:
                if pod.name == self.selected_pod.name:
                    self.selected_pod = pod
                    self.monitor.selected_pod_name = pod.name
                    await self.update_pod_view(pod)
                    break

        # Also refresh top bar to update global stats sparklines
        self.query_one("#top-bar", TopBar).refresh()

    async def update_pod_view(self, pod: PodStatus):
        """Update the detailed view for a pod."""
        # ── Logs ──
        log_view = self.query_one("#log-view", LogViewer)
        log_view.clear()
        # IST Timezone (UTC +5:30)
        IST = timezone(timedelta(hours=5, minutes=30))
        for log in pod.logs[-50:]:
            log_time = log.timestamp
            if log_time.tzinfo is not None:
                log_time = log_time.astimezone(IST)
            timestamp = log_time.strftime("%H:%M:%S")
            tag = _log_level_tag(log.level)
            log_view.add_log(f"[dim]\\[{timestamp}\\][/dim] {tag} {log.message}", log.level)

        # ── Network Info ──
        net_info = self.query_one("#network-info", NetworkInfo)
        net_info.update_pod(pod)

        # ── Metrics Table ──
        metrics_table = self.query_one("#metrics-table", MetricsTable)
        metrics_table.update_pod(pod)

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
        item = event.item
        if isinstance(item, PodListItem):
            self.selected_pod = item.pod_status
            self.monitor.selected_pod_name = self.selected_pod.name
            
            # Clear log view immediately on switch
            log_view = self.query_one("#log-view", LogViewer)
            log_view.clear()
            
            await self.update_pod_view(self.selected_pod)

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

        if hasattr(self.monitor, "config") and self.monitor.config is not None:
            self.monitor.config.ai.enabled = self.ai_enabled
        if hasattr(self.monitor, "ai_analyzer"):
            self.monitor.ai_analyzer.mock_mode = not self.ai_enabled

        status = "enabled" if self.ai_enabled else "disabled"
        self.notify(f"AI analysis {status}", title="AI Status")

    def action_show_info(self):
        """Display pod detailed info toast."""
        if self.selected_pod:
            ip = self.selected_pod.pod_ip or self.selected_pod.ip or "n/a"
            node = self.selected_pod.node_name or "unknown"
            self.notify(
                f"Pod: {self.selected_pod.name}\nIP: ip\nNode: {node}\nNamespace: {self.selected_pod.namespace}",
                title="Pod Info",
                severity="info"
            )
        else:
            self.notify("No pod selected", title="Pod Info", severity="warning")

    def action_terminate_pod(self):
        """Simulate terminating the selected pod."""
        if self.selected_pod:
            self.notify(f"Sending SIGTERM to pod {self.selected_pod.name}...", title="Terminate Pod", severity="warning")
        else:
            self.notify("No pod selected", title="Terminate Pod", severity="warning")

    def action_kill_pod(self):
        """Simulate killing the selected pod."""
        if self.selected_pod:
            self.notify(f"Sending SIGKILL to pod {self.selected_pod.name}!", title="Kill Pod", severity="error")
        else:
            self.notify("No pod selected", title="Kill Pod", severity="warning")

    def action_nice_pod(self):
        """Simulate renicing the selected pod."""
        if self.selected_pod:
            self.notify(f"Renicing container processes in {self.selected_pod.name} to 10", title="Nice Pod", severity="info")
        else:
            self.notify("No pod selected", title="Nice Pod", severity="warning")

    def action_quit(self):
        """Quit the application."""
        self.exit()