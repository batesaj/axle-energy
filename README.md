# AXLE Energy Intelligence v3.1

> **A**daptive e**X**pert **L**earning **E**nergy management engine for Home Assistant

A self-learning, physics-based energy management system built on AppDaemon for Home Assistant. AXLE optimises battery charging decisions overnight using AI-driven forecasting, real solar generation data, and personalised load profiles — saving money on time-of-use tariffs like Octopus Flux.

---

## What it does

Every night at 01:30, AXLE:

1. Fetches tomorrow's solar forecast from **Solcast** (purpose-built satellite solar forecasting)
2. Predicts tomorrow's house load using **learned shift-pattern profiles**
3. Runs a **24-hour physics simulation** of battery SOC hour by hour
4. Decides exactly how much grid charging is needed during the cheap rate window
5. Programs the inverter automatically
6. Sends a **push notification** with the decision and reasoning

Every evening at 23:50, AXLE records what actually happened and uses it to improve future forecasts.

---

## Hardware

This system was developed and tested on the following hardware. It will work with any GivEnergy inverter supported by GivTCP, and any solar array with Growatt monitoring.

### Inverter & Battery
- **GivEnergy AIO 3.0** all-in-one hybrid inverter/battery unit
  - 13 kWh usable battery capacity
  - 5 kW inverter
  - 4.5 kW export limit
  - Controlled via **GivTCP-DEV** Home Assistant addon

### Solar
- **20 × 440W panels** (8.8 kWp total)
  - 10 panels SE-facing (front, 125° azimuth, 30° tilt)
  - 10 panels NW-facing (rear, 305° azimuth, 30° tilt)
- **Growatt MIN 5000TL-X** string inverter
  - Provides per-string monitoring (SE and NW separately)
  - Connected via **Shine LAN box** and **Growatt Server** HA integration

### Home Assistant
- **Home Assistant OS** running as VM on Ugreen NAS
- **AppDaemon 4.x** — Python automation engine hosting AXLE
- **Mosquitto MQTT broker** — communication layer for GivTCP

### Tariff
- **Octopus Flux** time-of-use electricity tariff
  - Cheap rate: 02:00–05:00 (currently ~16p/kWh)
  - Peak rate: 16:00–19:00 (currently ~34p/kWh)
  - Export rate: ~9-12p/kWh

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Data Inputs                               │
│  Solcast API  │  GivTCP MQTT  │  Octopus API  │  Growatt   │
└───────┬───────┴───────┬───────┴───────┬───────┴─────┬──────┘
        │               │               │              │
        ▼               ▼               ▼              ▼
┌─────────────────────────────────────────────────────────────┐
│                 Home Assistant                               │
│  Template sensors │ REST sensors │ Integrations             │
└───────────────────────────┬─────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                   AXLE v3.1 Engine (AppDaemon)              │
│                                                             │
│  Layer 1: Data ingestion from HA sensors                    │
│  Layer 2: 21-day shift-cycle load learning model            │
│  Layer 3: Physics-based SOC simulation (SE/NW arrays)       │
│  Layer 4: Overnight charge decision engine                  │
│  Layer 5: Self-validation and adaptive accuracy scoring     │
└───────────────────────────┬─────────────────────────────────┘
                            │
                ┌───────────┴───────────┐
                ▼                       ▼
┌──────────────────────┐   ┌───────────────────────┐
│  GivEnergy AIO       │   │  AXLE Dashboard        │
│  Charge schedule set │   │  3-view HA dashboard   │
│  via GivTCP entities │   │  + simulation curves   │
└──────────────────────┘   └───────────────────────┘
```

---

## Key features

### Self-learning solar forecasting
- Uses **Solcast** satellite-based solar forecasting as primary source
- Maintains **adaptive correction factors** for each calendar month
- Learning rate adjusts based on forecast error magnitude — faster correction when badly wrong, slower when accurate
- Falls back to Open-Meteo radiation model if Solcast unavailable
- Models **SE and NW arrays separately** with time-of-day weighting

### Shift-pattern load modelling
- Supports **21-day rotating shift patterns** (configurable)
- 4 shift types: OFF (home all day), DAYS (out 09:00-19:00), LATES (out 12:00-21:00), SUNDAY_WORK
- Each shift type has its own **hourly load weight profile**
- **Bootstrap values** get you started immediately; real observations refine them
- Weighted rolling average (recent days weighted higher)

### Physics-based simulation
- Hour-by-hour SOC modelling for the next 24 hours
- Accounts for solar generation, house load, and cheap rate charging simultaneously
- Uses real sunrise/sunset times from Home Assistant
- Applies inverter efficiency and export limit constraints

### Safety systems
- **SOC floor protection** — never lets battery drop below 20%
- **Confidence-driven floor** — raises minimum SOC when forecast confidence is low
- **Winter full-charge strategy** — charges to 100% when solar forecast below threshold (October–March)
- **BMS cell balancing** — forces full charge if battery hasn't reached 100% in 7 days
- **Export SOC watchdog** — cancels export events if battery drops too low
- **Cheap rate watchdog** — verifies charging is actually happening during cheap window

### Dashboard
Three-view Home Assistant dashboard:
1. **Live** — real-time power flow, SOC history, solar strings, Octopus rates
2. **AXLE Brain** — charge decision, simulation curve, prediction vs reality, learning progress
3. **Costs** — Flux rate windows, import/export costs, gas

---

## Prerequisites

### Home Assistant addons
- AppDaemon 4.x
- Mosquitto MQTT broker
- GivTCP-DEV (for GivEnergy control)
- File Editor (for configuration)
- Terminal & SSH

### HA integrations
- **Octopus Energy** (by BottlecapDave) — tariff data
- **Growatt Server** — per-string solar monitoring
- **Solcast PV Forecast** — accurate solar forecasting
- **Workday** — bank holiday detection
- Open-Meteo REST sensor — weather/temperature data

### HACS custom cards (for dashboard)
- ApexCharts Card
- Power Flow Card Plus

---

## Installation

### 1. Install AppDaemon

In HA: **Settings → Add-ons → Add-on Store → AppDaemon 4**

### 2. Copy the AXLE engine

Copy `appdaemon/apps/axle_v3.py` to your AppDaemon apps directory:
```
/addon_configs/a0d7b954_appdaemon/apps/axle_v3.py
```

### 3. Configure apps.yaml

Copy `config/apps.yaml.example` to your AppDaemon apps directory and fill in your details:
```yaml
axle_v3:
  module: axle_v3
  class: AxleV3Engine
  growatt_plant_id: "YOUR_PLANT_ID"
  growatt_inverter_sn: "YOUR_INVERTER_SERIAL"
  growatt_username: "YOUR_GROWATT_EMAIL"
  growatt_password: "YOUR_GROWATT_PASSWORD"
```

### 4. Add HA configuration

Add the contents of `config/configuration.yaml` to your HA configuration. Update all entity IDs to match your hardware serials.

### 5. Add template sensors

Copy `config/templates/energy_sensors.yaml` to your HA config folder. Reference it from `configuration.yaml`:
```yaml
template: !include templates/energy_sensors.yaml
```

### 6. Set up Solcast

1. Create a free account at [solcast.com](https://solcast.com)
2. Add your rooftop site(s) with correct azimuth, tilt and capacity
3. Install the Solcast HA integration via HACS
4. Enter your API key

### 7. Configure your system parameters

Edit the constants at the top of `axle_v3.py`:

```python
BATTERY_CAPACITY_KWH   = 13.0    # Your usable battery capacity
EXPORT_LIMIT_KW        = 4.5     # Your grid export limit
NUM_PANELS_SE          = 10      # Panels on front/SE array
NUM_PANELS_NW          = 10      # Panels on rear/NW array
PANEL_RATING_W         = 440     # Individual panel wattage
LATITUDE_DEG           = 52.777  # Your latitude
LONGITUDE_DEG          = -2.115  # Your longitude
```

### 8. Configure your shift pattern (optional)

If your household has a rotating shift pattern, configure it in `axle_v3.py`:

```python
SHIFT_CYCLE_REF   = "2026-06-01"  # A Monday that is Week 1
SHIFT_CYCLE_WEEKS = 3             # Number of weeks in cycle

SHIFT_PATTERN = {
    0: "OFF",    # Mon W1
    1: "OFF",    # Tue W1
    # ... configure all 21 positions
}
```

See `docs/shift_pattern.md` for full instructions.

If you do not have a shift pattern, all days of the week will be learned independently using standard Mon–Sun profiles.

### 9. Initialise memory

Copy `config/axle_memory.json.example` to `/homeassistant/axle_memory.json` and update the solar corrections for your location. See `docs/configuration.md` for guidance.

### 10. Import the dashboard

Copy the contents of `dashboard/axle_energy.yaml` into a new HA dashboard via the raw config editor. Update all entity IDs to match your hardware.

---

## Configuration reference

See `docs/configuration.md` for a full list of all configurable parameters.

### Key constants in axle_v3.py

| Constant | Default | Description |
|---|---|---|
| `BATTERY_CAPACITY_KWH` | 13.0 | Usable battery capacity in kWh |
| `EXPORT_LIMIT_KW` | 4.5 | Grid export limit in kW |
| `PANEL_RATING_W` | 440 | Individual panel wattage |
| `NUM_PANELS_SE` | 10 | Panels on SE/front array |
| `NUM_PANELS_NW` | 10 | Panels on NW/rear array |
| `SOC_MIN_FLOOR` | 20 | Minimum SOC % — never charge below this |
| `CHARGE_SAFETY_BUFFER` | 5 | Extra % added to calculated charge need |
| `CHEAP_RATE_START` | 2 | Cheap rate start hour (02:00) |
| `CHEAP_RATE_END` | 5 | Cheap rate end hour (05:00) |
| `WINTER_MONTHS` | [10,11,12,1,2,3] | Months triggering full-charge strategy |
| `WINTER_SOLAR_THRESHOLD` | 15.0 | kWh below which winter full charge fires |
| `BMS_BALANCE_DAYS` | 7 | Days without full charge before BMS top-up |
| `LEARNING_DAYS` | 21 | Rolling window for load learning |

---

## How the charge decision works

```
01:30 every night
        │
        ▼
Get Solcast tomorrow forecast
        │
        ▼
Look up shift type for tomorrow
        │
        ▼
Get predicted load (learned or bootstrap)
        │
        ▼
Run 24h SOC simulation
        │
        ├─ min_soc < floor?  ──► Charge enough to stay above floor
        │
        ├─ Winter + solar < threshold?  ──► Charge to 100%
        │
        ├─ BMS: >7 days since 100%?  ──► Charge to 100%
        │
        └─ else  ──► No charge needed
        │
        ▼
Programme GivEnergy inverter
        │
        ▼
Send push notification
```

---

## Learning & accuracy

AXLE improves over time through three feedback loops:

**1. Solar correction factors**
Compares Solcast forecast vs actual Growatt generation each evening. Updates monthly correction factors using an adaptive learning rate — faster when the error is large, slower when accurate.

**2. Load profiles**
Records actual daily load under each shift type. Uses weighted rolling average with recent days weighted more heavily.

**3. Self-validation**
At 23:55 each night, compares the overnight prediction against actual SOC. Updates accuracy score and forecast error correction factor.

---

## Adapting for your setup

### Single-array system
Set `NUM_PANELS_NW = 0` and ignore NW-related sensors. The SE array profile will handle all solar generation.

### Different inverter
Replace all `aio_YOUR_GIVENERGY_SERIAL_` entity references with your inverter's GivTCP entity prefix.

### Different tariff
Update `CHEAP_RATE_START`, `CHEAP_RATE_END`, and the Octopus entity IDs. The core logic works with any time-of-use tariff.

### No shift pattern
Remove the shift pattern constants and replace `_get_shift_type()` with a simple day-of-week lookup using `["MONDAY","TUESDAY","WEDNESDAY","THURSDAY","FRIDAY","SATURDAY","SUNDAY"]`.

### No Growatt monitoring
Set `GROWATT_TOTAL_TODAY` to your GivEnergy PV sensor instead. Per-string monitoring will not be available but all other features work normally.

---

## Contributing

Pull requests welcome. Areas where contributions would be particularly valuable:

- Support for other inverter brands (SolarEdge, SMA, Sungrow)
- Support for Octopus Agile dynamic pricing
- Mid-day recalculation loop
- EV charging integration
- Immersion heater dump load control

---

## Licence

MIT — free to use, modify and distribute with attribution.

---

## Acknowledgements

- **GivTCP** — excellent open source GivEnergy control library
- **Solcast** — free hobbyist solar forecasting API
- **Octopus Energy** HA integration by BottlecapDave
- **ApexCharts Card** for HA dashboard visualisation
- The Home Assistant community for inspiration and support
