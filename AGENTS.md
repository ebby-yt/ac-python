# AGENTS GUIDE

Use this document to get oriented quickly and avoid breaking core assumptions in the `ac-python` workspace.

## Project Surfaces
- **complete/**: Production-ready scripts for the multi-strip wearable. `complete_v2.py` is the active entry point; older variants stay for regression reference.
- **i2ctest/max30102/**: Sensor experimentation harnesses; helpful for validating MAX30102 heart-rate behavior without touching production code.
- **neopixels/** and **temptest/**: Targeted hardware experiments that demonstrate LED driving and temperature sensing routines.
- **docs/**: Planning artifacts (e.g., `multi-strip-plan.md`) that define the current roadmap. Keep them in sync with code changes.

## Workflow Expectations
1. **Follow the plan**: Before implementing features, verify the next unchecked item in `docs/multi-strip-plan.md`. Update the checklist when a portion is done.
2. **Stay configuration-driven**: All tunable LED colors or thresholds belong in JSON or obvious constants near the top of `complete_v2.py`. Avoid scattering magic numbers.
3. **Defensive parsing**: Configuration loaders must validate shapes, clamp RGB values to `[0, 255]`, and log fallbacks when defaults are applied.
4. **Hardware safety**: Never block the main loop longer than existing waits; keep GPIO writes bounded and ensure cleanup paths run on exceptions.
5. **Backwards compatibility**: When replacing legacy files (e.g., `complete.py`), confirm dependent scripts or docs are updated or explicitly deprecated.

## Quality Gates
- **Static checks**: Run linters or at least `python -m compileall` on edited modules when feasible. Catch syntax errors before deploying to devices.
- **Runtime validation**: Provide dry-run/print modes when touching hardware logic so the code can be exercised on development machines.
- **Logging**: Use concise prints for Raspberry Pi deployments; each fallback or exceptional path should explain what happened and the chosen default.
- **Documentation sync**: Update READMEs or docs when new CLI flags, configuration keys, or hardware behaviors are introduced.

## Suggested Onboarding Steps
1. Read `complete/complete_v2.py` to understand the main loop, LED helpers, and configuration loading.
2. Inspect `complete/color_config.json` to see the expected multi-strip schema.
3. Skim sensor harnesses under `i2ctest/` to learn how heart rate, SpO₂, and temperature samples are produced.
4. Run small hardware tests via the scripts in `neopixels/` or `temptest/` before changing production logic.

Keep this file updated as the architecture evolves so future agents inherit accurate guidance.
