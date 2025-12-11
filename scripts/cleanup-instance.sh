#!/bin/bash

# Cleanup Aliyun ECS instance (fallback mechanism)
# If instance creation fails or Runner doesn't come online, cleanup instance

set -euo pipefail

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

# Configure Aliyun CLI
export ALIBABA_CLOUD_ACCESS_KEY_ID="${ALIYUN_ACCESS_KEY_ID}"
export ALIBABA_CLOUD_ACCESS_KEY_SECRET="${ALIYUN_ACCESS_KEY_SECRET}"

echo "Cleaning up instance: ${INSTANCE_ID}"

# First check instance status
echo "Checking instance status..."
INSTANCE_STATUS=$(aliyun ecs DescribeInstances \
  --RegionId "${ALIYUN_REGION_ID}" \
  --InstanceIds "[\"${INSTANCE_ID}\"]" \
  --query "Instances.Instance[0].Status" \
  --output text 2>/dev/null || echo "NotFound")

if [[ "${INSTANCE_STATUS}" == "NotFound" ]] || [[ "${INSTANCE_STATUS}" == "Stopped" ]] || [[ "${INSTANCE_STATUS}" == "Deleted" ]]; then
  echo "Instance already deleted or not found (status: ${INSTANCE_STATUS})"
  exit 0
fi

# Delete instance
echo "Deleting instance..."
RESPONSE=$(aliyun ecs DeleteInstance \
  --RegionId "${ALIYUN_REGION_ID}" \
  --InstanceId "${INSTANCE_ID}" \
  --Force true 2>&1)

EXIT_CODE=$?

if [[ ${EXIT_CODE} -ne 0 ]]; then
  echo "Warning: Failed to delete instance" >&2
  echo "Response: ${RESPONSE}" >&2
  exit ${EXIT_CODE}
fi

echo "Instance deleted successfully"
