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

class LogViewer(RichLog):
    """Custom log viewer with color coding."""
    
    def add_log(self, message: str, level: LogLevel = LogLevel.INFO):
        """Add a colored log message."""
        colors = {
            LogLevel.CRITICAL: "red bold",
            LogLevel.ERROR: "red",
            LogLevel.WARNING: "yellow",
            LogLevel.INFO: "white",
            LogLevel.DEBUG: "dim"
        }
        color = colors.get(level, "white")
        self.write(f"[{color}]{message}[/{color}]")

class PodListItem(ListItem):
    """Custom list item for pods."""
    
    def __init__(self, pod_status: PodStatus):
        self.pod_status = pod_status
        status_icon = "✅" if pod_status.healthy else "❌"
        label = f"{status_icon} {pod_status.name} ({pod_status.ip})"
        super().__init__(Label(label))
    
    def update_status(self, pod_status: PodStatus):
        """Update the displayed status."""
        self.pod_status = pod_status
        status_icon = "✅" if pod_status.healthy else "❌"
        self.children[0].update(f"{status_icon} {pod_status.name} ({pod_status.ip})")

class PodMonitorUI(App):
    CSS = """
    Screen {
        background: #1a1a2e;
    }
    
    #main-container {
        height: 100%;
        margin: 1;
    }
    
    #left-panel {
        width: 60%;
        height: 100%;
        background: #16213e;
        border: solid #0f3460;
        margin-right: 1;
    }
    
    #right-panel {
        width: 40%;
        height: 100%;
    }
    
    #pod-list {
        height: 30%;
        background: #16213e;
        border: solid #0f3460;
        margin-bottom: 1;
        padding: 1;
    }
    
    #log-view {
        height: 70%;
        background: #16213e;
        border: solid #0f3460;
        padding: 1;
    }
    
    #metrics-panel {
        height: 40%;
        background: #16213e;
        border: solid #0f3460;
        margin-bottom: 1;
        padding: 1;
    }
    
    #ai-panel {
        height: 60%;
        background: #16213e;
        border: solid #0f3460;
        padding: 1;
    }
    
    .metric-box {
        background: #1a1a2e;
        padding: 1;
        margin: 1;
        border: solid #0f3460;
    }
    
    .metric-label {
        color: #a8b2d1;
        text-style: bold;
    }
    
    .metric-value {
        color: #64ffda;
        text-style: bold;
    }
    
    .anomaly-critical {
        color: #ff6b6b;
        background: #2d1b1b;
    }
    
    .anomaly-high {
        color: #ffa94d;
        background: #2d241b;
    }
    
    .anomaly-medium {
        color: #ffd93d;
        background: #2d2a1b;
    }
    
    .anomaly-low {
        color: #6bcbff;
        background: #1b2d36;
    }
    
    .title {
        color: #64ffda;
        text-style: bold;
        padding: 1;
    }
    """
    
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
        
        with Container(id="main-container"):
            with Horizontal():
                # Left Panel
                with Container(id="left-panel"):
                    yield Static("📊 Pods", id="pod-title", classes="title")
                    yield ListView(id="pod-list")
                    yield Static("📝 Logs", id="log-title", classes="title")
                    yield LogViewer(id="log-view")
                
                # Right Panel
                with Container(id="right-panel"):
                    yield Static("📈 Metrics", id="metrics-title", classes="title")
                    yield Container(id="metrics-panel")
                    yield Static("🤖 AI Insights", id="ai-title", classes="title")
                    yield Container(id="ai-panel")
        
        yield Footer()
    
    async def on_mount(self):
        """Set up the UI."""
        # Initialize pod list
        pod_list = self.query_one("#pod-list", ListView)
        
        for pod in await self.monitor.get_all_pods():
            item = PodListItem(pod)
            self.pod_list_items.append(item)
            await pod_list.append(item)
        
        # Select first pod
        if self.pod_list_items:
            pod_list.index = 0
            await self.select_pod(pod_list.children[0])
        
        # Start background updates
        self.set_interval(2, self.update_ui)
    
    async def update_ui(self):
        """Update all UI components."""
        # Update pod list
        pod_list = self.query_one("#pod-list", ListView)
        pods = await self.monitor.get_all_pods()
        
        # Update list items
        for item, pod in zip(self.pod_list_items, pods):
            item.update_status(pod)
        
        # Update selected pod view
        if self.selected_pod:
            # Find updated version
            for pod in pods:
                if pod.ip == self.selected_pod.ip:
                    self.selected_pod = pod
                    await self.update_pod_view(pod)
                    break
    
    async def update_pod_view(self, pod: PodStatus):
        """Update the detailed view for a pod."""
        # Update logs
        log_view = self.query_one("#log-view", LogViewer)
        log_view.clear()
        for log in pod.logs[-50:]:  # Show last 50 logs
            timestamp = log.timestamp.strftime("%H:%M:%S")
            log_view.add_log(f"[{timestamp}] {log.message}", log.level)
        
        # Update metrics
        metrics_panel = self.query_one("#metrics-panel", Container)
        metrics_panel.remove_children()
        
        metrics = pod.metrics
        metrics_panel.mount(
            Static(f"CPU: {metrics.cpu_usage:.1f}%", classes="metric-box"),
            Static(f"Memory: {metrics.memory_usage:.1f} MiB", classes="metric-box"),
            Static(f"Error Rate: {metrics.error_rate:.1f}%", classes="metric-box"),
            Static(f"Active Connections: {metrics.active_connections}", classes="metric-box"),
        )
        
        # Update AI insights
        ai_panel = self.query_one("#ai-panel", Container)
        ai_panel.remove_children()
        
        if pod.anomalies:
            for anomaly in pod.anomalies[:3]:  # Show top 3 anomalies
                severity_class = f"anomaly-{anomaly.severity.value}"
                ai_panel.mount(
                    Static(
                        f"[{anomaly.severity.value.upper()}] {anomaly.description}",
                        classes=f"metric-box {severity_class}"
                    ),
                    Static(f"💡 {anomaly.suggestion}", classes="metric-box")
                )
        else:
            ai_panel.mount(
                Static("✅ No anomalies detected", classes="metric-box")
            )
    
    async def on_list_view_selected(self, event: ListView.Selected):
        """Handle pod selection."""
        await self.select_pod(event.item)
    
    async def select_pod(self, item: PodListItem):
        """Select a pod and update the view."""
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
        # Update config
        self.monitor.config.ai.enabled = self.ai_enabled
        self.monitor.ai_analyzer.mock_mode = not self.ai_enabled
        
        status = "enabled" if self.ai_enabled else "disabled"
        self.notify(f"AI analysis {status}", title="AI Status")
    
    def action_quit(self):
        """Quit the application."""
        self.exit()