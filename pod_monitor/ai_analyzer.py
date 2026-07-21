import asyncio
import json
import random
from typing import List, Optional
from datetime import datetime
import logging

from .models import LogEntry, LogLevel, Anomaly, Severity, PodStatus

logger = logging.getLogger(__name__)

class AIAnalyzer:
    def __init__(self, api_token: Optional[str] = None, 
                 ollama_url: Optional[str] = None,
                 mock_mode: bool = True):
        self.api_token = api_token
        self.ollama_url = ollama_url
        self.mock_mode = mock_mode or not (api_token or ollama_url)
        self.context_window = 50  # Number of logs to keep for context

    async def analyze_logs(self, logs: List[LogEntry], pod_status: PodStatus) -> List[Anomaly]:
        """Analyze logs for anomalies using AI."""
        if not logs:
            return []

        if self.mock_mode:
            return self._mock_analysis(logs, pod_status)

        # Use OpenAI or Ollama based on config
        if self.api_token:
            return await self._analyze_with_openai(logs, pod_status)
        elif self.ollama_url:
            return await self._analyze_with_ollama(logs, pod_status)
        else:
            return self._rule_based_analysis(logs, pod_status)

    def _mock_analysis(self, logs: List[LogEntry], pod_status: PodStatus) -> List[Anomaly]:
        """Mock AI analysis for demonstration."""
        anomalies = []
        
        # Simulate AI detection based on patterns
        error_logs = [log for log in logs if log.level in (LogLevel.ERROR, LogLevel.CRITICAL)]
        
        if error_logs:
            # Generate mock anomalies
            error_messages = [
                "High error rate detected in service",
                "Database connection failures",
                "Memory pressure detected",
                "Network timeout errors",
                "Authentication failures"
            ]
            
            # Randomly select some errors to flag
            if len(error_logs) > 3 and random.random() > 0.5:
                anomaly = Anomaly(
                    id=f"ai-{datetime.now().timestamp()}",
                    timestamp=datetime.now(),
                    severity=Severity.HIGH,
                    description=f"AI detected pattern: {random.choice(error_messages)}",
                    pod_ip=pod_status.ip,
                    pod_name=pod_status.name,
                    log_context=[log.message for log in error_logs[:5]],
                    suggestion=self._generate_suggestion(random.choice(error_messages)),
                    detected_by="ai"
                )
                anomalies.append(anomaly)

        # Check for high error rate
        if pod_status.error_count > 10 and pod_status.total_logs > 0:
            error_rate = (pod_status.error_count / pod_status.total_logs) * 100
            if error_rate > 20:
                anomaly = Anomaly(
                    id=f"rate-{datetime.now().timestamp()}",
                    timestamp=datetime.now(),
                    severity=Severity.CRITICAL,
                    description=f"Critical error rate: {error_rate:.1f}%",
                    pod_ip=pod_status.ip,
                    pod_name=pod_status.name,
                    suggestion="Immediate investigation required. Check service health.",
                    detected_by="rule"
                )
                anomalies.append(anomaly)

        return anomalies

    async def _analyze_with_openai(self, logs: List[LogEntry], pod_status: PodStatus) -> List[Anomaly]:
        """Analyze logs using OpenAI API."""
        try:
            import openai
            
            openai.api_key = self.api_token
            
            # Prepare prompt
            log_text = "\n".join([f"[{log.level.value}] {log.message}" for log in logs[-20:]])
            prompt = f"""
            Analyze these pod logs and identify any anomalies, errors, or potential issues.
            
            Pod: {pod_status.name} ({pod_status.ip})
            Error count: {pod_status.error_count}
            Total logs: {pod_status.total_logs}
            
            Logs:
            {log_text}
            
            Return a JSON array of anomalies with:
            - severity: (low/medium/high/critical)
            - description: brief description of the issue
            - suggestion: recommended action
            
            If no anomalies, return empty array.
            """
            
            response = await openai.ChatCompletion.acreate(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are a Kubernetes log analysis expert."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=500
            )
            
            # Parse response
            content = response.choices[0].message.content
            return self._parse_ai_response(content, pod_status)
            
        except Exception as e:
            logger.error(f"OpenAI analysis failed: {e}")
            return []

    async def _analyze_with_ollama(self, logs: List[LogEntry], pod_status: PodStatus) -> List[Anomaly]:
        """Analyze logs using Ollama local AI."""
        try:
            import aiohttp
            
            # Prepare prompt similar to OpenAI
            log_text = "\n".join([f"[{log.level.value}] {log.message}" for log in logs[-20:]])
            prompt = f"""
            Analyze these pod logs and identify anomalies.
            
            Logs:
            {log_text}
            
            Return JSON array of anomalies with severity, description, and suggestion.
            """
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.ollama_url}/api/generate",
                    json={
                        "model": "mistral",
                        "prompt": prompt,
                        "stream": False
                    }
                ) as response:
                    result = await response.json()
                    content = result.get("response", "")
                    return self._parse_ai_response(content, pod_status)
                    
        except Exception as e:
            logger.error(f"Ollama analysis failed: {e}")
            return []

    def _rule_based_analysis(self, logs: List[LogEntry], pod_status: PodStatus) -> List[Anomaly]:
        """Simple rule-based analysis as fallback."""
        anomalies = []
        
        # Rule: Critical errors
        critical_logs = [log for log in logs if log.level == LogLevel.CRITICAL]
        if critical_logs:
            anomalies.append(Anomaly(
                id=f"rule-{datetime.now().timestamp()}",
                timestamp=datetime.now(),
                severity=Severity.CRITICAL,
                description=f"CRITICAL logs found: {critical_logs[0].message[:100]}",
                pod_ip=pod_status.ip,
                pod_name=pod_status.name,
                log_context=[log.message for log in critical_logs[:3]],
                suggestion="Immediate attention required. Check pod status and logs.",
                detected_by="rule"
            ))
        
        # Rule: Multiple errors in short period
        error_logs = [log for log in logs if log.level == LogLevel.ERROR]
        if len(error_logs) > 5:
            anomalies.append(Anomaly(
                id=f"rate-{datetime.now().timestamp()}",
                timestamp=datetime.now(),
                severity=Severity.HIGH,
                description=f"High error frequency: {len(error_logs)} errors in last batch",
                pod_ip=pod_status.ip,
                pod_name=pod_status.name,
                suggestion="Check service health and dependencies.",
                detected_by="rule"
            ))
        
        return anomalies

    def _parse_ai_response(self, content: str, pod_status: PodStatus) -> List[Anomaly]:
        """Parse AI response into Anomaly objects."""
        anomalies = []
        try:
            data = json.loads(content)
            if isinstance(data, list):
                for item in data:
                    anomaly = Anomaly(
                        id=f"ai-{datetime.now().timestamp()}-{random.randint(1000, 9999)}",
                        timestamp=datetime.now(),
                        severity=Severity(item.get("severity", "medium")),
                        description=item.get("description", "AI detected anomaly"),
                        pod_ip=pod_status.ip,
                        pod_name=pod_status.name,
                        suggestion=item.get("suggestion", ""),
                        detected_by="ai"
                    )
                    anomalies.append(anomaly)
        except json.JSONDecodeError:
            # Fallback: extract from text
            logger.warning("Failed to parse AI response as JSON")
            
        return anomalies

    def _generate_suggestion(self, error_type: str) -> str:
        """Generate suggestions based on error type."""
        suggestions = {
            "database": "Check database connectivity, connection pool, and query performance.",
            "memory": "Increase memory limits, check for memory leaks, optimize code.",
            "network": "Verify network policies, check DNS resolution, ensure proper load balancing.",
            "authentication": "Validate credentials, check RBAC, renew service account tokens.",
            "timeout": "Increase timeout values, optimize slow operations, add retry logic."
        }
        
        for key, suggestion in suggestions.items():
            if key in error_type.lower():
                return suggestion
        
        return "Investigate logs and metrics, check pod status and events."

    def generate_summary(self, anomalies: List[Anomaly]) -> str:
        """Generate a human-readable summary of anomalies."""
        if not anomalies:
            return "✅ No anomalies detected. Pod is healthy."
        
        summary = f"⚠️ {len(anomalies)} anomalies detected:\n\n"
        for i, anomaly in enumerate(anomalies[:5], 1):
            summary += f"{i}. [{anomaly.severity.value.upper()}] {anomaly.description}\n"
            if anomaly.suggestion:
                summary += f"   💡 {anomaly.suggestion}\n"
        
        if len(anomalies) > 5:
            summary += f"\n... and {len(anomalies) - 5} more anomalies"
        
        return summary