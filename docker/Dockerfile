# Dockerfile — AI Employee Cloud Agent (Platinum Tier)
# Base: python:3.13-slim + git + ssh
# Entry point: cloud/orchestrator_cloud.py

FROM python:3.13-slim

# System dependencies: git, openssh-client, build tools
RUN apt-get update && apt-get install -y --no-install-recommends \
        git \
        openssh-client \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user for security
RUN useradd -m -u 1000 aiemployee

WORKDIR /app

# Copy dependency files first for layer caching
COPY pyproject.toml ./
COPY README.md ./

# Install Python dependencies (platinum extras)
RUN pip install --no-cache-dir -e ".[platinum]" || \
    pip install --no-cache-dir \
        watchdog>=4.0.2 \
        python-dotenv>=1.0.0 \
        schedule>=1.2.0 \
        pyyaml>=6.0.1 \
        gitpython>=3.1.40 \
        psutil>=5.9.8 \
        requests>=2.31.0

# Copy application code
COPY watchers/ ./watchers/
COPY cloud/ ./cloud/
COPY sync/ ./sync/
COPY recovery/ ./recovery/
COPY orchestrator.py ./

# SSH directory for git authentication
RUN mkdir -p /home/aiemployee/.ssh && \
    chown -R aiemployee:aiemployee /home/aiemployee/.ssh && \
    chmod 700 /home/aiemployee/.ssh

# Vault directory (mounted at runtime via docker-compose volume)
RUN mkdir -p /vault && chown aiemployee:aiemployee /vault

# Switch to non-root user
USER aiemployee

# Environment defaults (override via --env-file .env.cloud)
ENV VAULT_PATH=/vault/AI_Employee_Vault
ENV AGENT_ROLE=cloud
ENV DOMAIN=cloud
ENV DRY_RUN=true
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python cloud/health_monitor.py --once || exit 1

ENTRYPOINT ["python", "cloud/orchestrator_cloud.py"]
CMD ["--watchers", "gmail,fs"]
