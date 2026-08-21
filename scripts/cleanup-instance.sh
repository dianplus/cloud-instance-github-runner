#!/bin/bash

# Cleanup Aliyun ECS instance (fallback mechanism).
# Contract: this script either verifiably deletes the instance or fails
# loudly (non-zero exit + stderr diagnostics). Success is only reported on
# observed evidence from DescribeInstances; a failed CLI call is never
# treated as "instance gone", and Stopped is never treated as deleted
# (a stopped instance still bills for its disks).

set -euo pipefail

# Tunables: bounded retries for status query / delete, bounded polls for
# post-delete verification. Defaults target production; CI may zero the
# delays to speed tests up.
CLEANUP_MAX_ATTEMPTS="${CLEANUP_MAX_ATTEMPTS:-3}"
CLEANUP_RETRY_DELAY="${CLEANUP_RETRY_DELAY:-5}"
CLEANUP_VERIFY_POLLS="${CLEANUP_VERIFY_POLLS:-12}"
CLEANUP_VERIFY_INTERVAL="${CLEANUP_VERIFY_INTERVAL:-5}"

# Get parameters from environment variables
ALIYUN_ACCESS_KEY_ID="${ALIYUN_ACCESS_KEY_ID:-}"
ALIYUN_ACCESS_KEY_SECRET="${ALIYUN_ACCESS_KEY_SECRET:-}"
ALIYUN_REGION_ID="${ALIYUN_REGION_ID:-}"
INSTANCE_ID="${INSTANCE_ID:-}"

# Validate required parameters
if [[ -z "${ALIYUN_ACCESS_KEY_ID}" ]]; then
  echo "Error: ALIYUN_ACCESS_KEY_ID is required" >&2
  exit 1
fi

if [[ -z "${ALIYUN_ACCESS_KEY_SECRET}" ]]; then
  echo "Error: ALIYUN_ACCESS_KEY_SECRET is required" >&2
  exit 1
fi

if [[ -z "${ALIYUN_REGION_ID}" ]]; then
  echo "Error: ALIYUN_REGION_ID is required" >&2
  exit 1
fi

# If no instance ID, no cleanup needed
if [[ -z "${INSTANCE_ID}" ]]; then
  echo "No instance ID provided, skipping cleanup"
  exit 0
fi

# A missing aliyun CLI is a hard failure: without it we can neither verify
# nor delete, so we must not pretend cleanup happened.
if ! command -v aliyun >/dev/null 2>&1; then
  echo "Error: aliyun CLI not found in PATH (not installed?); cannot verify or delete instance ${INSTANCE_ID}" >&2
  exit 1
fi

# Configure Aliyun CLI
export ALIBABA_CLOUD_ACCESS_KEY_ID="${ALIYUN_ACCESS_KEY_ID}"
export ALIBABA_CLOUD_ACCESS_KEY_SECRET="${ALIYUN_ACCESS_KEY_SECRET}"

echo "Cleaning up instance: ${INSTANCE_ID}"

# Single DescribeInstances call using the raw-JSON convention (no --query):
# rc=0 prints the API response body; rc!=0 means the call itself failed
# (auth/network error) and says nothing about instance existence.
describe_once() {
  aliyun ecs DescribeInstances \
    --RegionId "${ALIYUN_REGION_ID}" \
    --InstanceIds "[\"${INSTANCE_ID}\"]" 2>&1
}

# Parse a DescribeInstances response body: prints "ABSENT" when the instance
# is not in the result set, otherwise its status string. Returns non-zero on
# malformed input; callers must treat that as a query failure, not absence.
# python3 is already a hard dependency of this action (zero new dependencies).
parse_instance_status() {
  python3 -c '
import json, sys
data = json.load(sys.stdin)
instances = data["Instances"]["Instance"]
print(instances[0]["Status"] if instances else "ABSENT")
'
}

# Bounded-retry DescribeInstances; prints the raw JSON body on success.
# A persistently failing query is a loud failure, never "instance absent".
describe_instance_json() {
  local attempt=1
  local output=""
  while (( attempt <= CLEANUP_MAX_ATTEMPTS )); do
    if ! output=$(describe_once); then
      echo "Warning: DescribeInstances attempt ${attempt}/${CLEANUP_MAX_ATTEMPTS} failed for ${INSTANCE_ID}: ${output}" >&2
      if (( attempt < CLEANUP_MAX_ATTEMPTS )); then
        sleep "${CLEANUP_RETRY_DELAY}"
      fi
      attempt=$((attempt + 1))
      continue
    fi
    printf '%s\n' "${output}"
    return 0
  done
  echo "Error: Failed to query instance ${INSTANCE_ID} after ${CLEANUP_MAX_ATTEMPTS} attempts; last output: ${output}" >&2
  exit 1
}

# Stage 1: status query. Any present state (Running/Stopping/Stopped/Starting)
# goes to the delete path -- Stopped still bills for disks.
echo "Checking instance status..."
RAW_JSON="$(describe_instance_json)"
if ! INSTANCE_STATUS=$(printf '%s\n' "${RAW_JSON}" | parse_instance_status); then
  echo "Error: Failed to parse DescribeInstances response for ${INSTANCE_ID}; raw output: ${RAW_JSON}" >&2
  exit 1
fi

if [[ "${INSTANCE_STATUS}" == "ABSENT" ]]; then
  echo "Instance ${INSTANCE_ID} verified absent (not in DescribeInstances result set)"
  exit 0
fi

echo "Instance ${INSTANCE_ID} present with status ${INSTANCE_STATUS}; deleting (a stopped instance still bills for disks)"

# Stage 2: delete with bounded retries. Force-release regardless of state.
DELETE_ATTEMPT=1
DELETE_OUTPUT=""
while (( DELETE_ATTEMPT <= CLEANUP_MAX_ATTEMPTS )); do
  if ! DELETE_OUTPUT=$(aliyun ecs DeleteInstance \
      --RegionId "${ALIYUN_REGION_ID}" \
      --InstanceId "${INSTANCE_ID}" \
      --Force true 2>&1); then
    echo "Warning: DeleteInstance attempt ${DELETE_ATTEMPT}/${CLEANUP_MAX_ATTEMPTS} failed for ${INSTANCE_ID}: ${DELETE_OUTPUT}" >&2
    if (( DELETE_ATTEMPT < CLEANUP_MAX_ATTEMPTS )); then
      sleep "${CLEANUP_RETRY_DELAY}"
    fi
    DELETE_ATTEMPT=$((DELETE_ATTEMPT + 1))
    continue
  fi
  echo "DeleteInstance accepted (attempt ${DELETE_ATTEMPT}/${CLEANUP_MAX_ATTEMPTS}); response: ${DELETE_OUTPUT}"
  break
done
if (( DELETE_ATTEMPT > CLEANUP_MAX_ATTEMPTS )); then
  echo "Error: Failed to delete instance ${INSTANCE_ID} after ${CLEANUP_MAX_ATTEMPTS} attempts; last output: ${DELETE_OUTPUT}" >&2
  exit 1
fi

# Stage 3: verify the deletion by polling DescribeInstances until the
# instance leaves the result set. "Deleted" is only reported on observed
# absence within the poll budget.
POLL=1
while (( POLL <= CLEANUP_VERIFY_POLLS )); do
  if ! POLL_JSON=$(describe_once); then
    echo "Warning: verification poll ${POLL}/${CLEANUP_VERIFY_POLLS} failed for ${INSTANCE_ID}: ${POLL_JSON}" >&2
  elif ! POLL_STATUS=$(printf '%s\n' "${POLL_JSON}" | parse_instance_status); then
    echo "Warning: verification poll ${POLL}/${CLEANUP_VERIFY_POLLS} returned unparseable output for ${INSTANCE_ID}: ${POLL_JSON}" >&2
  elif [[ "${POLL_STATUS}" == "ABSENT" ]]; then
    echo "Instance ${INSTANCE_ID} verified deleted (absent from DescribeInstances result set, poll ${POLL}/${CLEANUP_VERIFY_POLLS})"
    exit 0
  else
    echo "Instance ${INSTANCE_ID} still present (status: ${POLL_STATUS}), poll ${POLL}/${CLEANUP_VERIFY_POLLS}"
  fi
  if (( POLL < CLEANUP_VERIFY_POLLS )); then
    sleep "${CLEANUP_VERIFY_INTERVAL}"
  fi
  POLL=$((POLL + 1))
done

echo "Error: Failed to verify deletion of ${INSTANCE_ID}: still present (or verification queries failing) after ${CLEANUP_VERIFY_POLLS} polls; manual cleanup required" >&2
exit 1
