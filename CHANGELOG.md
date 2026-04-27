# Changelog

## v3.1.0 — 2026-04-27

### Added
- **21-day shift cycle awareness** — load profiles now learn per shift type (OFF/DAYS/LATES/SUNDAY_WORK) rather than day-of-week, allowing accurate modelling of rotating shift work patterns
- **Shift-type hourly load profiles** — each shift type has its own hourly weight distribution reflecting realistic energy usage patterns
- **Bootstrap load values** — sensible starting estimates per shift type before observations accumulate
- **Adaptive solar correction** — learning rate now adjusts based on error magnitude (faster when badly wrong, slower when accurate)
- **BMS cell balancing** — forces 100% charge if battery hasn't been full in 7 days, protecting battery health
- **Confidence-driven SOC floor** — minimum SOC automatically increases when forecast confidence is low
- **`sensor.axle_shift_today`** — new HA sensor publishing current shift type and week number
- **Shift type in notifications** — charge decision push notifications now include tomorrow's shift context
- **Solcast primary solar forecast** — replaces Open-Meteo radiation model as primary source, with Open-Meteo as fallback

### Changed
- `LEARNING_DAYS` extended to 21 to cover full shift cycle
- Load profiles keyed by shift type instead of day name
- Notification messages include shift type for context

### Fixed
- Solar forecast sensor now correctly scales by panel count and rating
- Hourly simulation table uses bracket notation for dict access

---

## v3.0.0 — 2026-04-26

### Initial release

- Physics-based 24-hour SOC simulation
- Overnight charge decision engine (01:30 daily)
- Self-learning solar correction factors (monthly)
- Rolling daily load profiles (day-of-week)
- Self-validation and accuracy scoring
- Winter full-charge strategy (October–March)
- Export SOC watchdog
- Cheap rate watchdog
- Growatt historical bootstrap
- Push notifications
- Three-view HA dashboard (Live / AXLE Brain / Costs)
- Simulation curve published to HA sensor
- Solcast PV Forecast integration support
