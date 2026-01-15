- [x] **Extend color_config schema**
  - Save three `base_colors` and three `end_colors` entries (arrays of RGB triplets) inside [complete/color_config.json](complete/color_config.json).
  - Document the expected order (e.g., strip 1 = heart rate, strip 2 = SpO₂, strip 3 = temperature) to avoid ambiguity.

- [x] **Add validation helpers**
  - Update the configuration loader in [complete/complete_v2.py](complete/complete_v2.py) to parse arrays of RGB tuples, clamp components, and fall back to safe defaults when entries are missing.
  - Log or print when defaults are used so misconfigurations are easy to spot on-device.

- [ ] **Represent strip metadata**
  - Introduce a lightweight structure (list of dicts or dataclass) describing each strip: metric name, LED slice indices, base color, end color.
  - Keep the data-driven table near the top of [complete/complete_v2.py](complete/complete_v2.py) so future strip additions only require edits in one place.

- [ ] **Compute metric ratios**
  - Reuse the existing normalization logic (`clean_data`) to convert heart rate, SpO₂, and temperature into 0–255 values, then divide by 255 to obtain the ratio between MIN and MAX thresholds for each metric.
  - Store the ratios per metric so both the first and last LEDs can use the same derived value.

- [ ] **Render strips independently**
  - Create `betterColorWipe` variants that accept a LED index range plus the corresponding base/end colors.
  - For each strip, set pixel 0 to its base color, pixel `n-1` to `lerp(end_color, ratio)`, and interpolate all intermediate LEDs across the full gradient span.
  - Ensure each strip updates without blocking the others (reuse the same wait time or allow per-strip overrides).

- [ ] **Graceful degradation**
  - If a metric reading is invalid, default its ratio to 0 and optionally dim the strip or flash a warning color so hardware issues are visible.
  - Provide a CLI flag to revert to the single-strip behavior for debugging.

- [ ] **Testing & verification**
  - Add a dry-run mode that prints the resolved colors for the first/last LED of each strip without driving GPIO (useful on development machines).
  - Run on hardware with simulated min/max sensor inputs to confirm the first LED always shows the configured base color and the last LED tracks the metric ratio.
