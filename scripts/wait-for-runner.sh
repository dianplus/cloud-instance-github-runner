#!/bin/bash

# Wait for Runner to come online
# Poll to check if Runner successfully registered to GitHub

set -euo pipefail

# Get parameters from environment variables
GITHUB_TOKEN="${GITHUB_TOKEN:-}"
GITHUB_REPOSITORY="${GITHUB_REPOSITORY:-}"
RUNNER_NAME="${RUNNER_NAME:-}"
TIMEOUT="${TIMEOUT:-120}"  # Default timeout 5 minutes
INTERVAL="${INTERVAL:-10}"  # Default polling interval 10 seconds

# Validate required parameters
if [[ -z "${GITHUB_TOKEN}" ]]; then
  echo "Error: GITHUB_TOKEN is required" >&2
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

echo "Waiting for runner: ${RUNNER_NAME}"
echo "Timeout: ${TIMEOUT} seconds"
echo "Polling interval: ${INTERVAL} seconds"

# Calculate maximum polling attempts
MAX_ATTEMPTS=$((TIMEOUT / INTERVAL))
ATTEMPT=0

# Poll to check if Runner is online
while [[ ${ATTEMPT} -lt ${MAX_ATTEMPTS} ]]; do
  ATTEMPT=$((ATTEMPT + 1))
  echo "Checking runner status (attempt ${ATTEMPT}/${MAX_ATTEMPTS})..."

  # Call GitHub API to query Runner list
  # API: GET /repos/{owner}/{repo}/actions/runners
  response=$(curl -s -w "\n%{http_code}" \
    -X GET \
    -H "Accept: application/vnd.github+json" \
    -H "Authorization: Bearer ${GITHUB_TOKEN}" \
    -H "X-GitHub-Api-Version: 2022-11-28" \
    "https://api.github.com/repos/${GITHUB_REPOSITORY}/actions/runners")

  # Separate response body and status code
  http_code=$(echo "${response}" | tail -n1)
  body=$(echo "${response}" | sed '$d')

  if [[ "${http_code}" != "200" ]]; then
    echo "Warning: Failed to query runners (HTTP ${http_code})" >&2
    echo "Response: ${body}" >&2
    sleep ${INTERVAL}
    continue
  fi

  # Check if Runner is in the list
  if echo "${body}" | jq -e --arg name "${RUNNER_NAME}" '.runners[] | select(.name == $name)' > /dev/null 2>&1; then
    # Get Runner status
    RUNNER_STATUS=$(echo "${body}" | jq -r --arg name "${RUNNER_NAME}" '.runners[] | select(.name == $name) | .status')
    RUNNER_ID=$(echo "${body}" | jq -r --arg name "${RUNNER_NAME}" '.runners[] | select(.name == $name) | .id')

    echo "Runner found: ${RUNNER_NAME}"
    echo "Runner ID: ${RUNNER_ID}"
    echo "Runner Status: ${RUNNER_STATUS}"

    # Check if Runner is online
    if [[ "${RUNNER_STATUS}" == "online" ]]; then
      echo "Runner is online!"
      if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
        echo "runner_online=true" >> "${GITHUB_OUTPUT}"
      fi
      exit 0
    else
      echo "Runner is registered but not online yet (status: ${RUNNER_STATUS})"
    fi
  else
    echo "Runner not found yet"
  fi

  # Wait for next poll
  if [[ ${ATTEMPT} -lt ${MAX_ATTEMPTS} ]]; then
    sleep ${INTERVAL}
  fi
done

# Timeout - Runner not found
echo "Error: Runner did not come online within ${TIMEOUT} seconds" >&2
if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
  echo "runner_online=false" >> "${GITHUB_OUTPUT}"
fi
exit 1
