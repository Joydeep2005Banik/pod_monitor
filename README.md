# Pod Monitor 🚀

**Pod Monitor** is an advanced, terminal-based User Interface (TUI) for real-time Kubernetes pod monitoring, equipped with AI-powered anomaly detection.

Built with Python and [Textual](https://textual.textualize.io/), it provides a sleek, `btop`-style dashboard right in your terminal, allowing you to instantly visualize cluster health, resource metrics, and container logs without leaving your command line.

---

## 🌟 Features

- **Real-Time TUI Dashboard:** View all your pods in an interactive, responsive terminal UI.
- **Resource Monitoring:** High-density CPU and Memory sparklines/graphs dynamically calculated against Kubernetes limits and node capacity.
- **Robust Metrics Fetching:** Natively leverages the official `kubernetes` Python API with intelligent fallback caching for CrashLoop/Completed pods.
- **Live Log Tailing:** Tail container logs in real-time with automatic deduplication, log-level color coding, and UTC-to-Local timezone conversions.
- **AI Anomaly Detection:** Passively analyzes log streams to detect patterns, errors, and anomalies on the fly.
- **Flexible Connections:** Uses your local `KUBECONFIG` to connect to Kubernetes natively, with secondary SSH fallback capabilities.

## 🛠️ Installation

### Prerequisites
- Python 3.10+
- `kubectl` configured with access to your cluster (e.g., Minikube).

### Setup

1. **Clone the repository (or navigate to the directory):**
   ```bash
   cd pod_monitor
   ```

2. **Create and activate a virtual environment:**
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configuration (Optional):**
   Adjust settings in `config.yaml` to tweak refresh intervals, thresholds, or API connection details.

## 🚀 Usage

Ensure your virtual environment is activated and your Kubernetes cluster is running (e.g., `minikube start`), then run:

```bash
python -m pod_monitor
```

