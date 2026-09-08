# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- New `watchdog_stop_window_seconds` input: max seconds of continuous runner inactivity before self-destruct (any active probe resets it). Unset keeps the watchdog default (24 probes = 2min) and preserves any image-pre-baked STOP_CONFIRMATIONS_REQUIRED; setting it overrides both, replacing hand-edits to /etc/environment (blueprint pr2-intervention v1.1). New `runner_version` / `runner_version_source` outputs expose what the resolve step actually shipped

### Changed

- `runner_version` now defaults to auto-latest: an empty input resolves the newest non-prerelease actions/runner release at setup time through the configured proxy (one HEAD against the releases/latest redirect, no api.github.com rate budget), with a pinned `RUNNER_FALLBACK_VERSION` constant as the loud fallback. Explicit pins are honored unchanged. Removes the stale default pin that kept every instance self-updating on its first job
- `runner_wait_timeout` default raised from 120 to 420 — the old default failed the action's own smoke test ("cold bootstrap via the VPC proxy takes 3-6 min; the 120s default would kill healthy runs")

### Fixed

- Renamed the env var carrying the new instance's runner name to SPOT_RUNNER_NAME. RUNNER_NAME is injected into every step by the Actions runner with the host agent's own name and cannot be overridden at step level, so on a self-hosted runner the instance registered under the host agent name and config.sh --replace took over its registration
- Moved the action's scratch files (user-data, instance id, error log, console log) from fixed /tmp names to RUNNER_TEMP. Several runner agents on one self-hosted host share /tmp, so two concurrent jobs overwrote each other's user-data and one instance booted with the other job's runner name and labels
- Masked the base64 derived form of the registration token as well: the Create Spot Instance step's env banner prints USER_DATA_B64 verbatim and setSecret only masks the exact raw string, so a decodable copy of the token reached the job log; the generate step now registers the b64 value with ::add-mask:: (companion to the core.setSecret fix; empirically confirmed against a pre-fix run's log archive)
- Removed the dead `export DEBUG=true` from the create step (no consumer in scripts/ or templates/)
- Masked the runner registration token with core.setSecret. A token minted at run time is not one of the workflow's configured secrets, so nothing masked it: every later step that carried it through `env:` printed it in clear text in the job log (the step-start banner lists resolved env values), and the token is enough to attach a self-hosted runner to this repository for an hour
- Replaced the bootstrap "Updating system" block with guarded install-on-missing for curl/git only: no more `yum update -y` full upgrade (pure cost on a single-job instance) and no unconditional `apt-get update`; the unattended-upgrades disable moved inside an apt-family guard so yum-family images no longer run a no-op with a misleading banner
- Corrected the stale stop-window texts left by the v1.1 revision: both READMEs' troubleshooting now says 24 probes / 2min, the postmortem carries superseded-by-v1.2 notes, and the watchdog-hardening blueprint's forensics-race arithmetic, AC-9 granularity note and Rollout expectations match the shipped 24x5s default
- Widened the watchdog stop verdict from 6 to 24 consecutive confirmed-inactive probes (30s to 2min). A runner older than the version GitHub serves self-updates when a job arrives, and the service restart could outlast the 30s window, so the watchdog destroyed the instance mid-job (blueprint watchdog-hardening v1.1)
- Disabled unattended-upgrades and the apt-daily timers on the instance. The automatic security upgrade restarted systemd-resolved a few minutes into the instance's life, and every DNS lookup during those seconds failed with connection refused, surfacing as random network errors inside the job
## [1.5.1] - 2026-09-04

### Added

- Hardened runner-watchdog: three-state probe (active / confirmed-inactive / query-failure-unknown) separates transient query failures from confirmed service stops; self-destruct now requires N consecutive confirmed-inactive probes (STOP_CONFIRMATIONS_REQUIRED, default 6 = 30s) instead of a single miss
- Added pre-destroy forensics dump (probe timeline + systemctl/journal tails, size-capped, to watchdog log + serial console)
- Added bootstrap-time validation of STOP_CONFIRMATIONS_REQUIRED from /etc/environment (loud failure via EXIT trap)

### Changed

### Removed

- Removed inert post-job hook dead config (ACTIONS_RUNNER_HOOK_POST_JOB never read by the runner; official variable is ACTIONS_RUNNER_HOOK_JOB_COMPLETED — teardown is handled by the hardened watchdog)

### Fixed

- Fixed stale wait-for-runner.sh timeout comment ("5 minutes" -> 120 seconds)

## [1.5.0] - 2026-09-03

### Added

- Added `spot_strategy` action input: explicit bidding strategy selection — `SpotAsPriceGo` (follow market price automatically; the multiplier and computed price limit do not affect bidding, no `--SpotPriceLimit` is sent; inputs are still fully validated) takes priority over `spot_price_multiplier`; default `SpotWithPriceLimit` preserves existing behavior. Explicit `SpotWithPriceLimit` with no limit available now fails loudly instead of silently switching.

### Changed

### Fixed

## [1.4.0] - 2026-09-03

### Added

- Added `spot_price_multiplier` action input: multiplier applied to the spot market price to compute `SpotPriceLimit` (default `1.2`, preserving existing bid behavior)
- Added `spot_duration` action input: spot protection period in hours, only `0` or `1` (default `1`; spot instances are billed by second regardless of this setting). Although the documented API default is also `1`, users observed frequent sub-hour price-based reclamation before this change — the explicit `--SpotDuration 1` now enforces the 1-hour protection instead of relying on the implicit default

### Changed

- Formatted `SpotPriceLimit` values to three decimal places in all code paths, aligning with the Aliyun RunInstances API constraint (at most 3 decimal places)
- Passed `--SpotDuration` explicitly to RunInstances (default `1`; the documented API default is treated as unreliable in practice — see the `spot_duration` note above)

### Removed

- Removed unused dead code `calculate_spot_price_limit()` from `scripts/create_spot_instance.py`

## [1.0.2] - 2025-12-17

### Added

- Added branding configuration (icon and color) to action.yml for GitHub Marketplace support
- Added CHANGELOG.md following Keep a Changelog format
- Added CI workflow (`.github/workflows/ci.yml`) for automated validation of action.yml
- Added release workflow (`.github/workflows/release.yml`) for automated release creation
- Added `scripts/update-changelog.sh` script for automating CHANGELOG.md version updates

## [1.0.1] - 2025-12-13

### Changed

- Updated README to clarify PAT (Personal Access Token) access and permissions requirements

## [1.0.0] - 2025-12-12

### Added

- Initial release of Setup Aliyun ECS Spot Runner GitHub Action
- Dynamic spot instance selection based on CPU, memory, and architecture requirements
- Multi-architecture support (AMD64 and ARM64)
- Automatic GitHub Actions Runner installation and configuration
- Ephemeral runner mode with automatic cleanup support
- Instance self-destruct functionality using ECS roles
- Support for specifying exact instance type (bypasses automatic selection)
- Multi-zone support for VSwitches across all availability zones (A-Z)
- HTTP/HTTPS proxy configuration support
- Aliyun CLI installation script in user-data
- Comprehensive documentation with usage examples and permission requirements

### Changed

- Reduced default runner timeout from 300s to 120s for faster feedback
- Improved runner name generation with timestamp and random suffix for better uniqueness
- Updated proxy variable export format for systemd compatibility
- Streamlined README content and clarified permissions

### Fixed

- Improved runner name uniqueness to prevent conflicts
- Fixed proxy variable export format for systemd compatibility
