#!/bin/bash

# Fetch the last-boot console output of an ECS instance (forensics before
# destruction). The output carries user-data/cloud-init logs and is
# unrecoverable once the instance is deleted, so callers must invoke this
# BEFORE cleanup-instance.sh.
#
# Contract -- deliberate design decision, do not "fix" (blueprint:
# docs/intent-blueprints/failure-forensics-console-output-v1.blueprint.md):
# forensics is best-effort and billing safety wins. Unlike
# cleanup-instance.sh, which fails loudly because a failed cleanup is a
# leak/billing risk, every failure here (CLI missing / API error / bad JSON /
# bad base64) only emits a stderr warning and exits 0 so the subsequent
# instance destruction is NEVER blocked. A failed fetch costs one log file,
# not money.

# No -e on purpose: with it, any failing forensics command would abort this
# script with a non-zero status and block the cleanup that runs after it.
# Every command failure below is handled explicitly and always ends in
# exit 0.
set -uo pipefail

# Best-effort cleanup of scratch files on any exit path (signals included).
# The trap only removes files; it never alters the exit status, preserving
# the exit-0 contract.
trap 'rm -f "${TMP_FILE:-}" "${ERROR_FILE:-}"' EXIT

# Get parameters from environment variables. Credentials are deliberately
# NOT validated here: when absent the API call fails on its own and takes
# the warning path, which is all the best-effort contract requires.
ALIYUN_ACCESS_KEY_ID="${ALIYUN_ACCESS_KEY_ID:-}"
ALIYUN_ACCESS_KEY_SECRET="${ALIYUN_ACCESS_KEY_SECRET:-}"
ALIYUN_REGION_ID="${ALIYUN_REGION_ID:-}"
INSTANCE_ID="${INSTANCE_ID:-}"
CONSOLE_LOG_FILE="${CONSOLE_LOG_FILE:-/tmp/instance-console.log}"

# If no instance ID, there is nothing to fetch (e.g. creation failed before
# an instance ID existed).
if [[ -z "${INSTANCE_ID}" ]]; then
  echo "Warning: INSTANCE_ID is empty, nothing to fetch (forensics is best-effort; cleanup continues)" >&2
  exit 0
fi

# Configure Aliyun CLI (same convention as cleanup-instance.sh).
export ALIBABA_CLOUD_ACCESS_KEY_ID="${ALIYUN_ACCESS_KEY_ID}"
export ALIBABA_CLOUD_ACCESS_KEY_SECRET="${ALIYUN_ACCESS_KEY_SECRET}"

echo "Fetching console output of instance: ${INSTANCE_ID}"

# Stderr scratch file, reused by each stage so every warning can quote the
# concrete failure reason.
ERROR_FILE="$(mktemp)"
if [[ -z "${ERROR_FILE}" ]]; then
  echo "Warning: failed to create stderr scratch file (tmp unwritable?); skipping forensics (best-effort; cleanup continues)" >&2
  exit 0
fi

# A missing aliyun CLI needs no `command -v` preflight: the shell's
# command-not-found failure makes the call below fail, taking the same
# warning path as any API error. (This is the reverse of
# cleanup-instance.sh's hard-fail preflight -- a deliberate difference: a
# missing CLI here only costs the log, not billing safety.)
# Bounded call (blueprint AC-6): the CLI's transport layer retries with long
# timeouts by default; under network partitions that could eat the whole
# cancellation grace window and push instance deletion out to the 240-min TTL
# backstop. Cap it: connect 10s + read 30s, retries disabled (~40s worst case).
# All three knobs are env-overridable.
CONSOLE_FETCH_CONNECT_TIMEOUT="${CONSOLE_FETCH_CONNECT_TIMEOUT:-10}"
CONSOLE_FETCH_READ_TIMEOUT="${CONSOLE_FETCH_READ_TIMEOUT:-30}"
CONSOLE_FETCH_RETRY_COUNT="${CONSOLE_FETCH_RETRY_COUNT:-0}"

if ! API_JSON="$(aliyun ecs GetInstanceConsoleOutput \
    --RegionId "${ALIYUN_REGION_ID}" \
    --InstanceId "${INSTANCE_ID}" \
    --connect-timeout "${CONSOLE_FETCH_CONNECT_TIMEOUT}" \
    --read-timeout "${CONSOLE_FETCH_READ_TIMEOUT}" \
    --retry-count "${CONSOLE_FETCH_RETRY_COUNT}" 2>"${ERROR_FILE}")"; then
  echo "Warning: GetInstanceConsoleOutput failed for ${INSTANCE_ID}: $(tr '\n' ' ' < "${ERROR_FILE}") (forensics is best-effort; cleanup continues)" >&2
  rm -f "${ERROR_FILE}"
  exit 0
fi

# Extract the base64 ConsoleOutput field with python3 (jq is not part of this
# action's dependency surface; python3 already is). The same step STRICTLY
# validates the base64 payload: BSD base64 silently discards invalid
# characters and still exits 0 (verified on macOS), so strict rejection must
# live here for the decode-failure warning path to be reachable at all.
# Malformed JSON, a missing/null ConsoleOutput field, or an invalid payload
# fails this step and takes the warning path.
if ! CONSOLE_B64="$(printf '%s' "${API_JSON}" | python3 -c '
import base64, json, sys
data = json.load(sys.stdin)
payload = "".join(data["ConsoleOutput"].split())
base64.b64decode(payload, validate=True)
sys.stdout.write(payload)
' 2>"${ERROR_FILE}")"; then
  echo "Warning: failed to extract or validate base64 ConsoleOutput from GetInstanceConsoleOutput response for ${INSTANCE_ID}: $(tr '\n' ' ' < "${ERROR_FILE}") (forensics is best-effort; cleanup continues)" >&2
  rm -f "${ERROR_FILE}"
  exit 0
fi

# Decode base64 into a temp file NEXT TO the target (same filesystem, so the
# final publish is an atomic mv): a failed fetch never leaves a half-written
# CONSOLE_LOG_FILE behind. The rc check still guards decode/IO errors that
# strict validation cannot predict.
TMP_FILE="$(mktemp "${CONSOLE_LOG_FILE}.tmp.XXXXXX")"
if [[ -z "${TMP_FILE}" ]]; then
  echo "Warning: failed to create temp file next to ${CONSOLE_LOG_FILE} (parent directory missing or unwritable?); skipping forensics (best-effort; cleanup continues)" >&2
  exit 0
fi
if ! printf '%s' "${CONSOLE_B64}" | base64 -d > "${TMP_FILE}" 2>"${ERROR_FILE}"; then
  echo "Warning: failed to base64-decode ConsoleOutput of ${INSTANCE_ID}: $(tr '\n' ' ' < "${ERROR_FILE}") (forensics is best-effort; cleanup continues)" >&2
  rm -f "${TMP_FILE}" "${ERROR_FILE}"
  exit 0
fi

# Success: publish atomically and report what was captured.
if ! mv -f "${TMP_FILE}" "${CONSOLE_LOG_FILE}"; then
  echo "Warning: failed to publish console log to ${CONSOLE_LOG_FILE} (target a directory? disk full?); forensics lost, cleanup continues" >&2
  exit 0
fi
rm -f "${ERROR_FILE}"
LINE_COUNT="$(wc -l < "${CONSOLE_LOG_FILE}" 2>/dev/null | tr -d '[:space:]')"
echo "Console output saved to ${CONSOLE_LOG_FILE} (${LINE_COUNT:-unknown} lines)"
exit 0
