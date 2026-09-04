#!/bin/bash

# User Data script - Base version
# Used for Spot Instance initialization, install GitHub Actions Runner
# Docker installation will be done using Actions in workflow
# This script will be automatically executed when instance starts

set -euo pipefail

# Log output
exec > >(tee /var/log/user-data.log)
exec 2>&1

echo "=== User Data Script Started ==="
echo "Timestamp: $(date -u +%Y-%m-%dT%H:%M:%SZ)"

# Variable definitions (passed via environment variables or parameters)
RUNNER_REGISTRATION_TOKEN="${RUNNER_REGISTRATION_TOKEN:-}"
GITHUB_REPOSITORY="${GITHUB_REPOSITORY:-}"
RUNNER_NAME="${RUNNER_NAME:-}"
RUNNER_LABELS="${RUNNER_LABELS:-}"
RUNNER_VERSION="${RUNNER_VERSION:-2.311.0}"  # Configurable Runner version, default to stable version

# Proxy configuration (optional)
HTTP_PROXY="${HTTP_PROXY:-}"
HTTPS_PROXY="${HTTPS_PROXY:-}"
NO_PROXY="${NO_PROXY:-localhost,127.0.0.1,::1,100.100.100.200,192.168.0.0/16,10.0.0.0/8,172.16.0.0/12,mirrors.tuna.tsinghua.edu.cn,mirrors.aliyun.com,.aliyun.com,.aliyuncs.com,.alicdn.com}"

# Instance self-destruct configuration (required)
# Use instance role (ECS Self-Destruct Role Name) to get permissions for instance self-destruct
ALIYUN_ECS_SELF_DESTRUCT_ROLE_NAME="${ALIYUN_ECS_SELF_DESTRUCT_ROLE_NAME:-}"

# Validate required parameters
if [[ -z "${RUNNER_REGISTRATION_TOKEN}" ]]; then
  echo "Error: RUNNER_REGISTRATION_TOKEN is required" >&2
  exit 1
fi

if [[ -z "${GITHUB_REPOSITORY}" ]]; then
  echo "Error: GITHUB_REPOSITORY is required" >&2
  exit 1
fi

if [[ -z "${RUNNER_NAME}" ]]; then
  echo "Error: RUNNER_NAME is required" >&2
  exit 1
fi

echo "Repository: ${GITHUB_REPOSITORY}"
echo "Runner Name: ${RUNNER_NAME}"
echo "Runner Labels: ${RUNNER_LABELS:-default}"

# Configure proxy (must be done before Runner registration)
echo "=== Configuring proxy ==="
if [[ -n "${HTTP_PROXY}" ]]; then
  echo "Setting HTTP_PROXY: ${HTTP_PROXY}"
  export HTTP_PROXY="${HTTP_PROXY}"
  # /etc/environment format: KEY=VALUE (no export keyword, systemd compatible)
  echo "HTTP_PROXY=\"${HTTP_PROXY}\"" >> /etc/environment
  # Also set lowercase variable to ensure curl and other tools work
  export http_proxy="${HTTP_PROXY}"
  echo "http_proxy=\"${HTTP_PROXY}\"" >> /etc/environment
fi

if [[ -n "${HTTPS_PROXY}" ]]; then
  echo "Setting HTTPS_PROXY: ${HTTPS_PROXY}"
  export HTTPS_PROXY="${HTTPS_PROXY}"
  # /etc/environment format: KEY=VALUE (no export keyword, systemd compatible)
  echo "HTTPS_PROXY=\"${HTTPS_PROXY}\"" >> /etc/environment
  # Also set lowercase variable to ensure curl and other tools work
  export https_proxy="${HTTPS_PROXY}"
  echo "https_proxy=\"${HTTPS_PROXY}\"" >> /etc/environment
fi

if [[ -n "${NO_PROXY}" ]]; then
  echo "Setting NO_PROXY: ${NO_PROXY}"
  export NO_PROXY="${NO_PROXY}"
  # /etc/environment format: KEY=VALUE (no export keyword, systemd compatible)
  echo "NO_PROXY=\"${NO_PROXY}\"" >> /etc/environment

  # Also set lowercase version (some tools use lowercase)
  export no_proxy="${NO_PROXY}"
  echo "no_proxy=\"${NO_PROXY}\"" >> /etc/environment
fi

if [[ -n "${HTTP_PROXY}" || -n "${HTTPS_PROXY}" ]]; then
  echo "Proxy configuration enabled"
else
  echo "Proxy configuration not provided, using direct connection"
fi

# Update system
echo "=== Updating system ==="
if command -v yum &> /dev/null; then
  # Alibaba Cloud Linux / CentOS / RHEL
  yum update -y
  yum install -y curl wget git
elif command -v apt-get &> /dev/null; then
  # Ubuntu / Debian
  apt-get update -y
  apt-get install -y curl wget git
else
  echo "Error: Unsupported package manager" >&2
  exit 1
fi

# Install Aliyun CLI (required for self-destruct mechanism)
echo "=== Installing Aliyun CLI ==="
if ! command -v aliyun &> /dev/null; then
  # Detect architecture
  ARCH=$(uname -m)
  if [[ "${ARCH}" == "x86_64" ]]; then
    CLI_ARCH="amd64"
  elif [[ "${ARCH}" == "aarch64" ]]; then
    CLI_ARCH="arm64"
  else
    echo "Error: Unsupported architecture for Aliyun CLI: ${ARCH}" >&2
    exit 1
  fi

  # Download and install Aliyun CLI
  CLI_URL="https://aliyuncli.alicdn.com/aliyun-cli-linux-latest-${CLI_ARCH}.tgz"
  echo "Downloading Aliyun CLI from: ${CLI_URL}"
  curl -o /tmp/aliyun-cli.tgz -L \
    --retry 5 --retry-all-errors \
    --connect-timeout 10 --max-time 300 \
    "${CLI_URL}"

  # Extract and install
  tar xzf /tmp/aliyun-cli.tgz -C /tmp
  mv /tmp/aliyun /usr/local/bin/aliyun
  chmod +x /usr/local/bin/aliyun
  rm -f /tmp/aliyun-cli.tgz

  # Verify installation
  if command -v aliyun &> /dev/null; then
    ALIYUN_VERSION=$(aliyun version 2>/dev/null || echo "unknown")
    echo "Aliyun CLI installed successfully (version: ${ALIYUN_VERSION})"
  else
    echo "Error: Failed to install Aliyun CLI" >&2
    exit 1
  fi
else
  ALIYUN_VERSION=$(aliyun version 2>/dev/null || echo "unknown")
  echo "Aliyun CLI already installed (version: ${ALIYUN_VERSION})"
fi

# Set up instance self-destruct mechanism
# NOTE: This chapter is deliberately placed BEFORE any Runner step so that a
# bootstrap failure at any later stage (runner download, registration, service
# install/start) still leaves the instance armed: EXIT trap (script dies
# non-zero) + runner-watchdog (dead-man switch); the action workflow's failure
# cleanup and the AutoReleaseTime floor cover the remaining teardown paths.
echo "=== Setting up instance self-destruct mechanism ==="
SELF_DESTRUCT_SCRIPT="/usr/local/bin/self-destruct.sh"

# Create self-destruct script
cat > "${SELF_DESTRUCT_SCRIPT}" << 'SELF_DESTRUCT_EOF'
#!/bin/bash

# Instance self-destruct script
# Automatically delete ECS instance after Runner exits
# Use instance role (RamRoleName) to get permissions for authentication

set -euo pipefail

# Log file
LOG_FILE="/var/log/self-destruct.log"

# Log function
log() {
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*" | tee -a "${LOG_FILE}"
}

log "=== Instance Self-Destruct Script Started ==="

# Prevent concurrent duplicate destruction (EXIT trap / watchdog may race);
# the loser exits quietly, the winner proceeds exactly once.
# /run (not /tmp): root-only tmpfs, so unprivileged job code cannot hold
# the lock open and block self-destruction.
exec 9> /run/self-destruct.lock
if ! flock -n 9; then
    log "Another self-destruct process already holds the lock; exiting"
    exit 0
fi

# Get instance ID (via Aliyun metadata service)
METADATA_URL="http://100.100.100.200/latest/meta-data"
INSTANCE_ID=$(curl -s --connect-timeout 5 --max-time 10 "${METADATA_URL}/instance-id" || echo "")
REGION_ID=$(curl -s --connect-timeout 5 --max-time 10 "${METADATA_URL}/region-id" || echo "")

if [[ -z "${INSTANCE_ID}" ]]; then
    log "Error: Failed to get instance ID from metadata service"
    exit 1
fi

if [[ -z "${REGION_ID}" ]]; then
    log "Error: Failed to get region ID from metadata service"
    exit 1
fi

log "Instance ID: ${INSTANCE_ID}"
log "Region ID: ${REGION_ID}"

# Check if Aliyun CLI is installed
if ! command -v aliyun &> /dev/null; then
    log "Error: Aliyun CLI is not installed"
    exit 1
fi

# Configure Aliyun CLI to use instance role authentication
# Get instance role name (from metadata service)
RAM_ROLE_NAME=$(curl -s --connect-timeout 5 --max-time 10 "${METADATA_URL}/ram/security-credentials/" || echo "")

if [[ -z "${RAM_ROLE_NAME}" ]]; then
    log "Error: Failed to get RAM role name from metadata service"
    log "Please ensure the instance has a RAM role attached"
    exit 1
fi

log "RAM Role Name: ${RAM_ROLE_NAME}"
log "Configuring Aliyun CLI to use instance role authentication"

# Configure aliyun cli to use instance role authentication
# Use non-interactive mode
aliyun configure set \
    --mode EcsRamRole \
    --ram-role-name "${RAM_ROLE_NAME}" \
    --region "${REGION_ID}" 2>&1 | tee -a "${LOG_FILE}" || {
    log "Error: Failed to configure Aliyun CLI"
    exit 1
}

log "Aliyun CLI configured successfully"

# Wait for a while to ensure Runner completely exits
log "Waiting 10 seconds before self-destruct..."
sleep 10

# Delete instance
log "Deleting instance: ${INSTANCE_ID}"
RESPONSE=$(aliyun ecs DeleteInstance \
    --RegionId "${REGION_ID}" \
    --InstanceId "${INSTANCE_ID}" \
    --Force true 2>&1)

EXIT_CODE=$?

if [[ ${EXIT_CODE} -ne 0 ]]; then
    log "Error: Failed to delete instance (exit code: ${EXIT_CODE})"
    log "Response: ${RESPONSE}"
    exit ${EXIT_CODE}
fi

log "Instance deleted successfully: ${INSTANCE_ID}"
log "=== Instance Self-Destruct Script Completed ==="
SELF_DESTRUCT_EOF

chmod +x "${SELF_DESTRUCT_SCRIPT}"

# Verify instance role configuration
if [[ -z "${ALIYUN_ECS_SELF_DESTRUCT_ROLE_NAME:-}" ]]; then
    echo "Warning: ALIYUN_ECS_SELF_DESTRUCT_ROLE_NAME is not configured, self-destruct mechanism may not work"
    echo "Please configure ALIYUN_ECS_SELF_DESTRUCT_ROLE_NAME in GitHub Variables"
else
    echo "Using instance role (${ALIYUN_ECS_SELF_DESTRUCT_ROLE_NAME}) for self-destruct mechanism"
fi

# Exit trap handler: if user-data exits non-zero (any bootstrap failure from
# here on), trigger self-destruct in the background so cloud-init finalization
# is not blocked. Guarded by script existence (armed as early as possible).
# The handler never overrides the original exit code: an EXIT trap only
# replaces it via an explicit `exit`, so we simply return the captured code.
on_user_data_exit() {
  local exit_code=$?
  echo "=== User Data exit handler: exit code ${exit_code} ==="
  if [[ ${exit_code} -ne 0 ]]; then
    echo "Bootstrap failed (exit code ${exit_code}); triggering self-destruct"
    if [[ -x /usr/local/bin/self-destruct.sh ]]; then
      # Prefer a systemd transient unit: its own cgroup survives cloud-init
      # teardown (KillMode=control-group would reap a plain nohup child when
      # the cloud-final unit exits). nohup remains the fallback.
      if systemd-run --unit=user-data-self-destruct --collect \
          /usr/local/bin/self-destruct.sh >> /var/log/user-data.log 2>&1; then
        echo "Self-destruct triggered via transient systemd unit (user-data-self-destruct)"
      else
        nohup /usr/local/bin/self-destruct.sh >> /var/log/user-data.log 2>&1 &
        echo "Self-destruct triggered in background via nohup fallback (pid: $!)"
      fi
    else
      echo "Warning: /usr/local/bin/self-destruct.sh not armed yet; nothing to trigger"
    fi
  else
    echo "Bootstrap completed successfully; teardown left to the runner-watchdog"
  fi
  # Preserve the original exit code (handler failures must not mask it)
  return "${exit_code}"
}

trap on_user_data_exit EXIT

# Validate the operator escape-hatch override for the watchdog's stop-verdict
# threshold (watchdog-hardening AC-9): read STOP_CONFIRMATIONS_REQUIRED from
# /etc/environment -- the same channel the watchdog unit's EnvironmentFile
# consumes -- with the pinned shape (line-anchored key, last duplicate wins,
# value past the first '=', double quotes stripped). An existing but
# non-positive-integer value must fail user-data NOW: the EXIT trap above then
# triggers self-destruct (loud, no residual instance). Validating inside the
# watchdog instead would loop its Restart=on-failure into start-limit and
# silently kill the dead-man switch. A missing key is the legal "no override
# expressed" path: the watchdog default (STOP_CONFIRMATIONS_REQUIRED:-6)
# applies, not a silent fallback.
STOP_CONFIRMATIONS_REQUIRED_RAW=""
if grep -q '^STOP_CONFIRMATIONS_REQUIRED=' /etc/environment 2>/dev/null; then
  STOP_CONFIRMATIONS_REQUIRED_RAW="$(grep '^STOP_CONFIRMATIONS_REQUIRED=' /etc/environment | tail -1 | cut -d= -f2- | tr -d '"' || true)"
  if ! [[ "${STOP_CONFIRMATIONS_REQUIRED_RAW}" =~ ^[0-9]+$ ]] || [[ "${STOP_CONFIRMATIONS_REQUIRED_RAW}" -eq 0 ]]; then
    echo "Error: STOP_CONFIRMATIONS_REQUIRED must be a positive integer, got '${STOP_CONFIRMATIONS_REQUIRED_RAW}'" >&2
    exit 1
  fi
  echo "STOP_CONFIRMATIONS_REQUIRED override: ${STOP_CONFIRMATIONS_REQUIRED_RAW} consecutive confirmations"
fi

# Create runner watchdog (dead-man switch)
# Replaces the old inline self-destruct.service glob-wait loop: that loop
# treated "glob does not match yet" as "runner already stopped" and exited
# immediately during bootstrap (race). This watchdog instead bounds its wait
# for the runner service to APPEAR, and only arms on stop after it was seen
# active at least once.
cat > /usr/local/bin/runner-watchdog.sh << 'WATCHDOG_EOF'
#!/bin/bash

# Runner watchdog - dead-man switch for the bootstrap
# Phase 1 (bootstrap wait): wait up to BOOTSTRAP_WATCH_TIMEOUT seconds for an
#   actions.runner.*.service to become active. Timeout means bootstrap died
#   without tripping the EXIT trap (e.g. reboot, kill -9) -> self-destruct.
# Phase 2 (run watch): once the runner is active, self-destruct only after
#   STOP_CONFIRMATIONS_REQUIRED consecutive confirmed-inactive probes (the
#   ephemeral runner finished its single job), so a transient query failure
#   can never kill a healthy runner on a single hit.
# Note: no `set -e` here on purpose - a watchdog must not die silently on a
# failed probe; every branch below is self-guarded.

# Bound for phase 1; overridable via environment (e.g. systemd unit override)
BOOTSTRAP_WATCH_TIMEOUT="${BOOTSTRAP_WATCH_TIMEOUT:-1800}"
# Phase-2 stop verdict: consecutive confirmed-inactive probes required before
# self-destruction; any active probe resets the streak. Default
# 6 x POLL_INTERVAL_SECONDS(5s) = 30s window; overridable via environment,
# validated at user-data bootstrap time.
STOP_CONFIRMATIONS_REQUIRED="${STOP_CONFIRMATIONS_REQUIRED:-6}"
POLL_INTERVAL_SECONDS=5
SELF_DESTRUCT_SCRIPT="/usr/local/bin/self-destruct.sh"

log() {
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] runner-watchdog: $*" | tee -a /var/log/runner-watchdog.log
}

# Tri-state probe of the actions.runner.* services. The unit pattern is
# QUOTED so systemd (not the shell) expands it: an empty result means "not
# active right now", never "glob did not match = stopped".
#   systemctl rc=0 + non-empty output -> "active"
#   systemctl rc=0 + empty output    -> "inactive" (confirmed-inactive: the
#       query SUCCEEDED and no unit is active -- valid stop evidence)
#   systemctl rc!=0                  -> "unknown" (the query itself failed;
#       NEVER stop evidence -- stderr stays suppressed, the captured exit
#       code keeps the states apart)
runner_service_probe() {
    local units
    units="$(systemctl list-units --type=service --state=active --no-legend --no-pager 'actions.runner.*.service' 2>/dev/null)"
    local rc=$?
    if [[ ${rc} -ne 0 ]]; then
        echo "unknown"
    elif [[ -n "${units}" ]]; then
        echo "active"
    else
        echo "inactive"
    fi
}

# Pre-destruction forensics dump (best-effort by design): the probe timeline
# (tri-state, timestamped, already in the watchdog log), a systemctl status
# tail and a journal tail, each size-capped (tail -c, 16KB total budget).
# Output goes to the watchdog log AND the serial console (/dev/console --
# GetInstanceConsoleOutput can capture it before the instance vanishes).
# Every segment is self-guarded: a dump failure must never block or replace
# the self-destruct path below.
dump_forensics() {
    {
        echo "=== runner-watchdog forensics dump before self-destruct ==="
        echo "--- probe timeline (tail) ---"
        tail -c 4096 /var/log/runner-watchdog.log 2>/dev/null || true
        echo "--- systemctl status (tail) ---"
        systemctl status 'actions.runner.*.service' --no-pager --lines=20 2>/dev/null | tail -c 4096 || true
        echo "--- journal (tail) ---"
        journalctl --no-pager -n 200 2>/dev/null | tail -c 8192 || true
    } 2>/dev/null | tee -a /var/log/runner-watchdog.log /dev/console >/dev/null 2>&1 || true
}

log "started (BOOTSTRAP_WATCH_TIMEOUT=${BOOTSTRAP_WATCH_TIMEOUT}s, STOP_CONFIRMATIONS_REQUIRED=${STOP_CONFIRMATIONS_REQUIRED})"

# Phase 1: bounded dead-man wait for the runner service to appear. Only an
# "active" probe ends the wait; "inactive" (not up yet) and "unknown" (query
# failed) both fall into the sleep-and-continue branch -- a query failure is
# not bootstrap death.
deadline=$(( $(date +%s) + BOOTSTRAP_WATCH_TIMEOUT ))
while true; do
    state="$(runner_service_probe)"
    if [[ "${state}" == "active" ]]; then
        break
    fi
    if [[ "${state}" == "unknown" ]]; then
        log "bootstrap wait: probe unknown (systemctl query failed); keep waiting"
    fi
    if [[ $(date +%s) -ge ${deadline} ]]; then
        log "runner service never became active within ${BOOTSTRAP_WATCH_TIMEOUT}s (bootstrap failed) -> self-destruct"
        dump_forensics
        exec "${SELF_DESTRUCT_SCRIPT}"
    fi
    sleep "${POLL_INTERVAL_SECONDS}"
done

log "runner service is active; watching for it to stop"

# Phase 2: poll until the runner service stops. A stop verdict requires
# STOP_CONFIRMATIONS_REQUIRED consecutive confirmed-inactive probes; any
# active probe resets the streak; an unknown probe neither increments nor
# resets it (probe jitter must not stretch the window forever nor erase
# accumulated stop evidence -- the leak side stays bounded by
# AutoReleaseTime).
confirmations=0
while true; do
    state="$(runner_service_probe)"
    if [[ "${state}" == "active" ]]; then
        if [[ ${confirmations} -gt 0 ]]; then
            log "probe: active again; ${confirmations} confirmation(s) cleared"
        fi
        confirmations=0
    elif [[ "${state}" == "inactive" ]]; then
        confirmations=$((confirmations + 1))
        log "probe: confirmed-inactive ${confirmations}/${STOP_CONFIRMATIONS_REQUIRED}"
        if [[ ${confirmations} -ge ${STOP_CONFIRMATIONS_REQUIRED} ]]; then
            log "runner service stopped (${STOP_CONFIRMATIONS_REQUIRED} consecutive confirmed-inactive probes) -> self-destruct"
            dump_forensics
            exec "${SELF_DESTRUCT_SCRIPT}"
        fi
    else
        log "probe: unknown (systemctl query failed); streak stays at ${confirmations}/${STOP_CONFIRMATIONS_REQUIRED}"
    fi
    sleep "${POLL_INTERVAL_SECONDS}"
done
WATCHDOG_EOF

chmod +x /usr/local/bin/runner-watchdog.sh

# Create systemd service to run the watchdog (starts during bootstrap, survives
# reboots via multi-user.target)
cat > /etc/systemd/system/runner-watchdog.service << 'UNIT_EOF'
[Unit]
Description=GitHub Actions Runner Bootstrap Watchdog (dead-man switch)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
# A failed self-destruct (transient metadata/network error) must not leave
# the dead-man switch dead; retry the whole watchdog cycle.
Restart=on-failure
ExecStart=/usr/local/bin/runner-watchdog.sh
StandardOutput=journal
StandardError=journal
EnvironmentFile=/etc/environment

[Install]
WantedBy=multi-user.target
UNIT_EOF

# Enable and start watchdog service
systemctl daemon-reload
systemctl enable runner-watchdog.service
systemctl start runner-watchdog.service

echo "Self-destruct armed: EXIT trap (non-zero exit) + runner-watchdog (dead-man)"
echo "Instance will be automatically deleted when bootstrap fails, or when the Runner service stops"

# Install GitHub Actions Runner
echo "=== Installing GitHub Actions Runner ==="
RUNNER_DIR="/opt/actions-runner"
mkdir -p "${RUNNER_DIR}"

# Detect architecture
ARCH=$(uname -m)
if [[ "${ARCH}" == "x86_64" ]]; then
  RUNNER_ARCH="x64"
elif [[ "${ARCH}" == "aarch64" ]]; then
  RUNNER_ARCH="arm64"
else
  echo "Error: Unsupported architecture: ${ARCH}" >&2
  exit 1
fi

# Download Runner
echo "Using Runner version: ${RUNNER_VERSION}"
RUNNER_URL="https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/actions-runner-linux-${RUNNER_ARCH}-${RUNNER_VERSION}.tar.gz"

cd "${RUNNER_DIR}"
echo "Downloading runner from: ${RUNNER_URL}"
# Add retry and timeout to improve robustness in proxy/weak network environments
curl -o runner.tar.gz -L \
  --retry 5 --retry-all-errors \
  --connect-timeout 10 --max-time 300 \
  "${RUNNER_URL}"
tar xzf runner.tar.gz
rm runner.tar.gz

echo "=== Installing runner dependencies ==="
# Install GitHub Actions Runner dependencies (.NET runtime dependencies, etc.)
# Note: Script will automatically choose apt/yum to install libicu and other dependencies based on system
./bin/installdependencies.sh

# Configure Runner (Ephemeral mode)
echo "=== Configuring Runner ==="
# Allow running runner configuration as root
export RUNNER_ALLOW_RUNASROOT=1
./config.sh \
  --url "https://github.com/${GITHUB_REPOSITORY}" \
  --token "${RUNNER_REGISTRATION_TOKEN}" \
  --name "${RUNNER_NAME}" \
  --labels "${RUNNER_LABELS:-self-hosted,Linux,aliyun,spot-instance,${RUNNER_ARCH}}" \
  --ephemeral \
  --unattended \
  --replace

# Install Runner service (using root user)
echo "=== Installing Runner service ==="
echo "Writing runner environment file: ${RUNNER_DIR}/.env"
{
  echo "HTTP_PROXY=${HTTP_PROXY}"
  echo "HTTPS_PROXY=${HTTPS_PROXY}"
  echo "NO_PROXY=${NO_PROXY}"
  # Lowercase variants for tools that rely on them under systemd service
  echo "http_proxy=${HTTP_PROXY}"
  echo "https_proxy=${HTTPS_PROXY}"
  echo "no_proxy=${NO_PROXY}"
} > "${RUNNER_DIR}/.env"
chmod 600 "${RUNNER_DIR}/.env" || true

./svc.sh install root

# Start Runner service
echo "=== Starting Runner service ==="
./svc.sh start

echo "=== User Data Script Completed ==="
echo "Timestamp: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
