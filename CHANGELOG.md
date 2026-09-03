# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

### Changed

### Fixed

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
