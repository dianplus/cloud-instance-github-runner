# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
