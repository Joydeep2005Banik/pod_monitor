"""
Configuration management for Pod Monitor.
Handles loading and validating YAML configuration files.
"""

import os
import yaml
from pathlib import Path
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

@dataclass
class SSHConfig:
    """SSH connection configuration."""
    user: str = "root"
    password: Optional[str] = None
    key_path: Optional[str] = None
    port: int = 22
    timeout: int = 30
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SSHConfig":
        return cls(
            user=data.get('user', 'root'),
            password=data.get('password'),
            key_path=data.get('key_path'),
            port=data.get('port', 22),
            timeout=data.get('timeout', 30)
        )

@dataclass
class AIConfig:
    """AI analysis configuration."""
    enabled: bool = True
    provider: str = "mock"  # "openai", "ollama", "mock"
    openai_token: Optional[str] = None
    openai_model: str = "gpt-3.5-turbo"
    ollama_url: Optional[str] = None
    ollama_model: str = "mistral"
    mock_mode: bool = True
    max_tokens: int = 500
    temperature: float = 0.3
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AIConfig":
        return cls(
            enabled=data.get('enabled', True),
            provider=data.get('provider', 'mock'),
            openai_token=data.get('openai_token') or os.getenv('OPENAI_API_KEY'),
            openai_model=data.get('openai_model', 'gpt-3.5-turbo'),
            ollama_url=data.get('ollama_url') or os.getenv('OLLAMA_URL', 'http://localhost:11434'),
            ollama_model=data.get('ollama_model', 'mistral'),
            mock_mode=data.get('mock_mode', True),
            max_tokens=data.get('max_tokens', 500),
            temperature=data.get('temperature', 0.3)
        )

@dataclass
class MonitorConfig:
    """Pod monitoring configuration."""
    pods: List[str] = field(default_factory=list)
    namespaces: List[str] = field(default_factory=lambda: ["default"])
    refresh_interval: int = 10
    log_lines_to_fetch: int = 100
    anomaly_threshold: int = 3
    max_logs_per_pod: int = 1000
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MonitorConfig":
        return cls(
            pods=data.get('pods', []),
            namespaces=data.get('namespaces', ["default"]),
            refresh_interval=data.get('refresh_interval', 10),
            log_lines_to_fetch=data.get('log_lines_to_fetch', 100),
            anomaly_threshold=data.get('anomaly_threshold', 3),
            max_logs_per_pod=data.get('max_logs_per_pod', 1000)
        )

@dataclass
class AlertConfig:
    """Alerting configuration."""
    enabled: bool = False
    slack_webhook: Optional[str] = None
    email: Optional[str] = None
    severity_threshold: str = "high"  # "low", "medium", "high", "critical"
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AlertConfig":
        return cls(
            enabled=data.get('enabled', False),
            slack_webhook=data.get('slack_webhook') or os.getenv('SLACK_WEBHOOK'),
            email=data.get('email') or os.getenv('ALERT_EMAIL'),
            severity_threshold=data.get('severity_threshold', 'high')
        )

@dataclass
class Config:
    """Main configuration class."""
    ssh: SSHConfig = field(default_factory=SSHConfig)
    ai: AIConfig = field(default_factory=AIConfig)
    monitor: MonitorConfig = field(default_factory=MonitorConfig)
    alerts: AlertConfig = field(default_factory=AlertConfig)
    
    def validate(self) -> bool:
        """Validate configuration."""
        if not self.monitor.pods:
            raise ValueError("At least one pod must be specified")
        
        if self.ai.provider == "openai" and not self.ai.openai_token:
            raise ValueError("OpenAI token required for OpenAI provider")
        
        if self.ai.provider == "ollama" and not self.ai.ollama_url:
            raise ValueError("Ollama URL required for Ollama provider")
        
        return True
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Config":
        return cls(
            ssh=SSHConfig.from_dict(data.get('ssh', {})),
            ai=AIConfig.from_dict(data.get('ai', {})),
            monitor=MonitorConfig.from_dict(data.get('monitor', {})),
            alerts=AlertConfig.from_dict(data.get('alerts', {}))
        )

def load_config(path: str = "config.yaml") -> Config:
    """
    Load configuration from YAML file.
    
    Args:
        path: Path to configuration file
        
    Returns:
        Config object
        
    Raises:
        FileNotFoundError: If config file doesn't exist
        yaml.YAMLError: If config file is invalid
    """
    config_path = Path(path)
    
    if not config_path.exists():
        # Try default locations
        default_paths = [
            Path("config.yaml"),
            Path.home() / ".pod-monitor" / "config.yaml",
            Path("/etc/pod-monitor/config.yaml")
        ]
        
        for default_path in default_paths:
            if default_path.exists():
                config_path = default_path
                break
        else:
            # Create default config if it doesn't exist
            create_default_config(path)
            print(f"Created default configuration at {path}")
            return get_default_config()
    
    try:
        with open(config_path, 'r') as f:
            data = yaml.safe_load(f)
        
        config = Config.from_dict(data)
        config.validate()
        return config
        
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML in config file: {e}")

def get_default_config() -> Config:
    """Get default configuration."""
    return Config()

def create_default_config(path: str = "config.yaml"):
    """Create a default configuration file."""
    default_config = {
        'ssh': {
            'user': 'root',
            'password': '',
            'key_path': '~/.ssh/id_rsa',
            'port': 22,
            'timeout': 30
        },
        'ai': {
            'enabled': True,
            'provider': 'mock',  # 'openai', 'ollama', 'mock'
            'openai_token': '',  # Or set OPENAI_API_KEY env var
            'openai_model': 'gpt-3.5-turbo',
            'ollama_url': 'http://localhost:11434',
            'ollama_model': 'mistral',
            'mock_mode': True,
            'max_tokens': 500,
            'temperature': 0.3
        },
        'monitor': {
            'pods': [
                '192.168.1.100',
                '192.168.1.101'
            ],
            'namespaces': ['default'],
            'refresh_interval': 10,
            'log_lines_to_fetch': 100,
            'anomaly_threshold': 3,
            'max_logs_per_pod': 1000
        },
        'alerts': {
            'enabled': False,
            'slack_webhook': '',  # Or set SLACK_WEBHOOK env var
            'email': '',  # Or set ALERT_EMAIL env var
            'severity_threshold': 'high'
        }
    }
    
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    
    with open(path, 'w') as f:
        yaml.dump(default_config, f, default_flow_style=False, indent=2)