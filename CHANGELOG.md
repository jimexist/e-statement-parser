# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.1] - 2026-10-26

### Added

- The app offers a one-time download of the OCR model the first time a statement needs it, or when you pick the OCR engine, with a progress bar. The model is pinned to one Hugging Face commit and each file to a SHA-256, so a changed or tampered file is refused. ([#10](https://github.com/jimexist/e-statement-parser/pull/10))
- A 180 MB lite macOS app (`eStatement-lite`) without the on-device OCR runtime, for statements with a text layer (UOB, DBS). Releases ship it next to the full app; `ESTATEMENT_OCR=0` builds it. ([#11](https://github.com/jimexist/e-statement-parser/pull/11))
- CI guards: a `personal-data` job that fails if statement PDFs, databases, CSVs (outside test fixtures), spreadsheets, OFX or QIF files are tracked, plus a gitleaks scan of the full history. The vendored Alpine.js script gets a Subresource Integrity attribute, and CI builds the wheel and checks that the web UI files are in it. ([#8](https://github.com/jimexist/e-statement-parser/pull/8))

### Changed

- The full macOS app is 550 MB, down from 914 MB, after leaving out libraries the OCR runtime pulls in but never uses (OpenCV, pyarrow, pandas, onnxruntime, scipy). ([#11](https://github.com/jimexist/e-statement-parser/pull/11))
- Bumped GitHub Actions dependencies (`actions/checkout`, `astral-sh/setup-uv`, `pnpm/action-setup`, `actions/setup-node`, `actions/upload-artifact`). ([#7](https://github.com/jimexist/e-statement-parser/pull/7))

## [0.1.0] - 2026-10-26

First release.

### Added

- On-device parser that turns bank e-statement PDFs into SQLite and CSV, for UOB credit card, UOB One Account, DBS consolidated statements and HSBC credit card. It reads the PDF text layer when there is one and falls back to GLM-OCR on MLX for HSBC, whose PDFs have none. Includes a local web UI and a macOS app. ([#1](https://github.com/jimexist/e-statement-parser/pull/1))
- Release workflow: pushing a `v*` tag builds `eStatement.app` on Apple Silicon, smoke-tests it, and publishes it to a GitHub release as a zip with a SHA-256 checksum. ([#3](https://github.com/jimexist/e-statement-parser/pull/3))
- Runtime type checking across the package with beartype. ([#5](https://github.com/jimexist/e-statement-parser/pull/5))
- Weekly Dependabot updates for Python (uv), web UI tooling (npm) and GitHub Actions. ([#6](https://github.com/jimexist/e-statement-parser/pull/6))

### Changed

- Now targets Python 3.14. ([#2](https://github.com/jimexist/e-statement-parser/pull/2))
- Rebuilt the web UI on vendored Alpine.js 3.14.9, so it makes no CDN or other network requests, and lints it with oxlint/oxfmt. ([#4](https://github.com/jimexist/e-statement-parser/pull/4))

[Unreleased]: https://github.com/jimexist/e-statement-parser/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/jimexist/e-statement-parser/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/jimexist/e-statement-parser/releases/tag/v0.1.0
