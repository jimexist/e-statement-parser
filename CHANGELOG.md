# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.2.0] - 2026-10-26

### Added

- Importing shows a progress bar: which file is being parsed and, for scanned statements, which OCR page and retry. Parsing now runs in the background and the UI polls for status, so the window stays responsive during long OCR imports. ([#16](https://github.com/jimexist/e-statement-parser/pull/16))
- Before running on-device OCR on an image-only PDF, the app asks you to confirm, since OCR can take several minutes per statement. ([#15](https://github.com/jimexist/e-statement-parser/pull/15))
- A Copy CSV button next to Export CSV puts the same filtered transactions on the clipboard, ready to paste into a spreadsheet. ([#14](https://github.com/jimexist/e-statement-parser/pull/14))

### Removed

- The lite macOS app (`eStatement-lite`). Releases ship one app, with on-device OCR. ([#15](https://github.com/jimexist/e-statement-parser/pull/15))

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

[Unreleased]: https://github.com/jimexist/e-statement-parser/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/jimexist/e-statement-parser/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/jimexist/e-statement-parser/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/jimexist/e-statement-parser/releases/tag/v0.1.0
