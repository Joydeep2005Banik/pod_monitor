#!/bin/bash
# Script to generate test logs

while true; do
    # Generate random log entries
    messages=(
        "INFO: User login successful"
        "INFO: API request processed in 45ms"
        "WARNING: High disk I/O detected"
        "ERROR: Database connection timeout"
        "INFO: Cache synchronized successfully"
        "CRITICAL: Out of memory error"
        "INFO: Health check passed"
        "WARNING: Slow response time detected"
        "ERROR: Authentication failed"
    )
    
    # Randomly select and append to log
    echo "$(date '+%Y-%m-%d %H:%M:%S') ${messages[$RANDOM % ${#messages[@]}]}" >> /var/log/app.log
    
    sleep $((RANDOM % 5 + 1))
done