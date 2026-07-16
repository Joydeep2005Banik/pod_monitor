import asyncio
import random
from datetime import datetime
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Header, Footer, RichLog, Static

# --- Mock Log Stream Generator ---
# Replace this generator with your actual SSH/API log streaming logic later.
MOCK_LOGS = [
    "INFO: User login successful",
    "INFO: API request processed in 45ms",
    "WARNING: High disk I/O detected on /dev/sda1",
    "ERROR: Database connection timeout (Host: 10.0.0.5)",
    "INFO: Cache synchronized successfully",
    "CRITICAL: Out of memory error in worker pool 4",
]

async def stream_logs():
    while True:
        await asyncio.sleep(random.uniform(0.5, 2.0))
        yield random.choice(MOCK_LOGS)


# --- Textual TUI Application ---
class PodMonitorApp(App):
    CSS = """
    Screen {
        background: #1e1e1e;
    }
    #left-panel {
        width: 60%;
        height: 100%;
        border: solid green;
    }
    #right-panel {
        width: 40%;
        height: 100%;
    }
    .metric-box {
        height: 40%;
        border: solid blue;
        content-align: center middle;
        text-style: bold;
    }
    .ai-box {
        height: 60%;
        border: solid magenta;
        padding: 1;
    }
    .warning-alert {
        background: maroon;
        color: white;
    }
    """
    
    BINDINGS = [("q", "quit", "Quit application")]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal():
            # Left side: Live log display
            with Container(id="left-panel"):
                yield RichLog(id="log-stream", highlight=True, markup=True)
            
            # Right side: Analytics & AI Insights
            with Vertical(id="right-panel"):
                yield Static("Errors Caught: 0", id="metric-panel", classes="metric-box")
                yield Static("🤖 [b]AI Log Insights[/b]\nWaiting for critical events...", id="ai-panel", classes="ai-box")
        yield Footer()

    def on_mount(self) -> None:
        """Triggered when the UI starts up."""
        self.error_count = 0
        self.log_widget = self.query_one("#log-stream", RichLog)
        self.metric_widget = self.query_one("#metric-panel", Static)
        self.ai_widget = self.query_one("#ai-panel", Static)
        
        # Start the background task to listen to the log stream
        self.run_worker(self.consume_logs())

    async def consume_logs(self):
        """Asynchronously listens to logs and updates the UI components."""
        async for log_line in stream_logs():
            timestamp = datetime.now().strftime("%H:%M:%S")
            formatted_line = f"[{timestamp}] {log_line}"
            
            # 1. Update Log Feed with highlighting
            if "ERROR" in log_line or "CRITICAL" in log_line:
                self.log_widget.write(f"[red]{formatted_line}[/red]")
                self.error_count += 1
                
                # 2. Update Metrics & trigger visual thresholds
                self.metric_widget.update(f"Errors Caught: {self.error_count}")
                if self.error_count >= 3:
                    self.metric_widget.set_classes("metric-box warning-alert")
                
                # 3. Simulate AI Triggering for critical issues
                self.trigger_ai_analysis(log_line)
            elif "WARNING" in log_line:
                self.log_widget.write(f"[yellow]{formatted_line}[/yellow]")
            else:
                self.log_widget.write(formatted_line)

    def trigger_ai_analysis(self, dynamic_log):
        """Simulates sending log context to an AI engine."""
        # Here you would typically use `requests` or `ollama` client asyncly
        mock_ai_responses = [
            "Root Cause: Resource exhaustion.\nFix: Check memory limits or scale pod replica count.",
            "Root Cause: Network partition or target DB down.\nFix: Validate DB security groups and connection strings.",
        ]
        chosen_insight = random.choice(mock_ai_responses)
        
        ai_display = (
            f"🤖 [b][magenta]AI Flagged Event![/magenta][/b]\n"
            f"[dim]Log line: {dynamic_log}[/dim]\n\n"
            f"{chosen_insight}"
        )
        self.ai_widget.update(ai_display)


if __name__ == "__main__":
    app = PodMonitorApp()
    app.run()