# AXLE Architecture

## Overview

AXLE is a five-layer energy intelligence engine running inside AppDaemon on Home Assistant. Each layer builds on the previous one to produce an overnight charge decision that improves in accuracy over time.

## Layer 1 — Data ingestion

AXLE reads from Home Assistant entities every time it needs data. Key sources:

| Entity | Source | Used for |
|---|---|---|
| `sensor.solcast_pv_forecast_forecast_tomorrow` | Solcast integration | Tomorrow's solar forecast |
| `sensor.aio_*_soc` | GivTCP | Current battery state |
| `sensor.aio_*_load_power` | GivTCP | Current house load |
| `sensor.solar_weather_raw` | Open-Meteo REST | Weather, temperature, cloud cover |
| `sensor.wnkde2101d_energy_today_input_*` | Growatt Server | Per-string actual generation |
| Octopus rate entities | Octopus Energy integration | Current and next tariff rates |
| `binary_sensor.workday` | Workday integration | Bank holiday detection |

## Layer 2 — Learning model

Three separate learning systems run in parallel:

### Solar correction factors
- One factor per calendar month (1-12)
- Updated nightly: `new = old × (1-α) + (actual/forecast) × α`
- α (learning rate) adapts to error magnitude:
  - Error > 30%: α = 0.4 (fast correction)
  - Error > 15%: α = 0.25 (medium)
  - Error < 15%: α = 0.1 (stable)

### Shift-type load profiles
- One rolling list per shift type (OFF, DAYS, LATES, etc.)
- Each day's actual load is appended
- Prediction uses weighted average (recent days weighted higher)
- Falls back to bootstrap values until 3+ observations exist

### Self-validation accuracy score
- Compares overnight predicted minimum SOC against actual SOC at 23:55
- `accuracy = 100 - (|error| × 2)`
- Used to adjust confidence-driven SOC floor

## Layer 3 — Physics simulation

The simulation runs hour-by-hour from midnight to 23:00 for the target day:

```
For each hour h in 0..23:
  1. Solar generation:
     - Get Open-Meteo shortwave radiation for hour h+24 (tomorrow)
     - Apply cloud cover reduction
     - Apply SE/NW array split based on hour-of-day factors
     - Apply NW seasonal weight (lower in winter)
     - Apply solar correction factor for this month
     - Cap at export limit + house load

  2. House load:
     - Distribute daily load forecast across hours
     - Using shift-type specific hourly weight profile

  3. Cheap rate charging (02:00-05:00):
     - Add charge power to net if within cheap window

  4. SOC delta:
     - net_kw = pv_kw - load_kw [+ charge_kw]
     - delta_pct = (net_kw / battery_capacity) × 100
     - soc = clamp(soc + delta, 0, 100)

  5. Store: {h, soc, pv_kw, load_kw, net_kw}
```

## Layer 4 — Decision engine

After simulation, the decision logic applies in priority order:

```
1. SOC below floor now?
   → Charge to floor + safety buffer

2. Simulated minimum SOC below floor?
   → Charge enough to prevent this

3. Winter + solar below threshold?
   → Charge to 100% (maximise stored energy)

4. BMS: >7 days since 100% SOC?
   → Charge to 100% (cell balancing)

5. None of the above?
   → No overnight charge needed

Then: programme GivEnergy via GivTCP entities
      send push notification
      store decision + simulation in memory
      publish simulation curve to HA sensor
```

## Layer 5 — Self-validation

At 23:55 each night:
- Read actual SOC (end of day)
- Compare to predicted minimum SOC from last night's simulation
- Update accuracy score and forecast error correction
- Log for dashboard display

At 23:50 each night (before validation):
- Record actual load, actual PV, shift type
- Update load profile for this shift type
- Update solar correction factor
- Record NW/SE string ratio for this month
- Check if battery reached 100% (BMS timer reset)

## Sensor publishing

AXLE publishes several HA sensors during operation:

| Sensor | Updated | Contains |
|---|---|---|
| `sensor.axle_v3_status` | Startup + validation | Engine state, accuracy, last decision |
| `sensor.axle_charge_decision` | 01:30 | Target SOC, reason, solar/load forecast |
| `sensor.axle_soc_simulation_curve` | Startup + 01:30 | Full 24h simulation data |
| `sensor.axle_shift_today` | Startup | Today's shift type, week number |

## Scheduling

| Time | Event |
|---|---|
| Startup +30s | Status check and sensor publish |
| Startup +35s | Publish simulation curve from memory |
| Startup +60s | Growatt historical bootstrap (if needed) |
| Every 2 mins | Export SOC watchdog |
| Every 30 mins | Cheap rate watchdog (02:00-05:00 only) |
| 23:50 daily | Record daily observation |
| 23:55 daily | Self-validation |
| 01:30 daily | Overnight charge decision |
