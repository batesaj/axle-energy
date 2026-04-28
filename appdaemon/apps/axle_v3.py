"""
AXLE v3.1 Energy Intelligence Engine
AppDaemon Python app for Home Assistant

Changes from v3.0:
- 21-day shift cycle awareness
- Adaptive solar correction speed
- BMS cell balancing (7-day full charge rule)
- Confidence-driven SOC floor
- Solcast primary solar forecast
"""

import appdaemon.plugins.hass.hassapi as hass
import json
import os
from datetime import datetime, timedelta

# ─────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────

MEMORY_FILE            = "/homeassistant/axle_memory.json"
BATTERY_CAPACITY_KWH   = 13.0
EXPORT_LIMIT_KW        = 4.5
NUM_PANELS_SE          = 10
NUM_PANELS_NW          = 10
PANEL_RATING_W         = 440
CHEAP_RATE_START       = 2
CHEAP_RATE_END         = 5
SOC_MIN_FLOOR          = 20
CHARGE_SAFETY_BUFFER   = 5
LEARNING_DAYS          = 21  # Extended to cover full shift cycle

# ── Winter full charge ────────────────────────────────────────
WINTER_MONTHS          = [10, 11, 12, 1, 2, 3]
WINTER_SOLAR_THRESHOLD = 15.0  # kWh — below this, fill battery

# ── BMS cell balancing ────────────────────────────────────────
BMS_BALANCE_DAYS       = 7    # Force 100% if not reached in this many days

# ── 21-day shift cycle ────────────────────────────────────────
SHIFT_CYCLE_REF        = "YYYY-MM-DD"  # Set to a Monday that is Week 1 of your cycle  # Monday Week 1 reference
SHIFT_CYCLE_WEEKS      = 3

# Cycle position (0=Mon W1 ... 20=Sun W3) → shift type
SHIFT_PATTERN = {
    0:  "OFF",          # Mon W1
    1:  "OFF",          # Tue W1
    2:  "OFF",          # Wed W1
    3:  "DAYS",         # Thu W1
    4:  "DAYS",         # Fri W1
    5:  "DAYS",         # Sat W1
    6:  "SUNDAY_WORK",  # Sun W1 — alternates DAYS/LATES
    7:  "LATES",        # Mon W2
    8:  "LATES",        # Tue W2
    9:  "OFF",          # Wed W2
    10: "OFF",          # Thu W2
    11: "OFF",          # Fri W2
    12: "OFF",          # Sat W2
    13: "OFF",          # Sun W2
    14: "DAYS",         # Mon W3
    15: "DAYS",         # Tue W3
    16: "DAYS",         # Wed W3
    17: "LATES",        # Thu W3
    18: "LATES",        # Fri W3
    19: "LATES",        # Sat W3
    20: "OFF",          # Sun W3
}

# Expected daily load by shift type (kWh) — bootstrapped, refined by observations
SHIFT_LOAD_BOOTSTRAP = {
    "OFF":         13.0,   # Both home all day
    "DAYS":         8.5,   # Out 09:00-19:00, low daytime
    "LATES":        9.5,   # Out 12:00-21:00, medium morning
    "SUNDAY_WORK":  9.0,   # Average of DAYS/LATES Sunday
    "BANK_HOLIDAY": 13.0,  # Treat like OFF
}

# Hourly load weight by shift type (relative weights, normalised internally)
SHIFT_HOURLY_WEIGHTS = {
    "OFF": {
        0:0.3, 1:0.2, 2:0.2, 3:0.2, 4:0.2, 5:0.3,
        6:0.6, 7:0.9, 8:1.2, 9:1.3, 10:1.3, 11:1.2,
        12:1.1, 13:1.0, 14:1.0, 15:1.1, 16:1.2, 17:1.8,
        18:2.0, 19:1.8, 20:1.5, 21:1.2, 22:0.8, 23:0.5
    },
    "DAYS": {
        0:0.3, 1:0.2, 2:0.2, 3:0.2, 4:0.2, 5:0.3,
        6:0.6, 7:1.0, 8:0.8, 9:0.5, 10:0.4, 11:0.4,
        12:0.4, 13:0.4, 14:0.4, 15:0.4, 16:0.5, 17:0.8,
        18:1.0, 19:2.2, 20:2.0, 21:1.5, 22:1.0, 23:0.6
    },
    "LATES": {
        0:0.3, 1:0.2, 2:0.2, 3:0.2, 4:0.2, 5:0.3,
        6:0.6, 7:0.9, 8:1.2, 9:1.3, 10:1.2, 11:1.0,
        12:0.8, 13:0.5, 14:0.4, 15:0.4, 16:0.4, 17:0.5,
        18:0.5, 19:0.6, 20:0.8, 21:2.2, 22:1.8, 23:0.8
    },
    "SUNDAY_WORK": {
        0:0.3, 1:0.2, 2:0.2, 3:0.2, 4:0.2, 5:0.3,
        6:0.6, 7:0.9, 8:1.1, 9:1.2, 10:1.1, 11:0.9,
        12:0.7, 13:0.5, 14:0.4, 15:0.4, 16:0.5, 17:0.7,
        18:0.8, 19:1.5, 20:1.5, 21:1.8, 22:1.4, 23:0.7
    },
    "BANK_HOLIDAY": {
        0:0.3, 1:0.2, 2:0.2, 3:0.2, 4:0.2, 5:0.3,
        6:0.6, 7:0.9, 8:1.2, 9:1.3, 10:1.3, 11:1.2,
        12:1.1, 13:1.0, 14:1.0, 15:1.1, 16:1.2, 17:1.8,
        18:2.0, 19:1.8, 20:1.5, 21:1.2, 22:0.8, 23:0.5
    },
}

NW_SEASONAL_WEIGHT = {
    1:0.65, 2:0.65, 3:0.78, 4:0.84,
    5:0.85, 6:0.85, 7:0.85, 8:0.85,
    9:0.80, 10:0.75, 11:0.68, 12:0.65
}

SE_HOUR = {6:0.1,7:0.3,8:0.6,9:0.85,10:1.0,11:1.0,12:0.9,
           13:0.75,14:0.55,15:0.35,16:0.2,17:0.1,18:0.05}
NW_HOUR = {8:0.05,9:0.1,10:0.2,11:0.35,12:0.5,13:0.7,
           14:0.85,15:1.0,16:1.0,17:0.9,18:0.75,19:0.55,20:0.3,21:0.1}

GROWATT_SE_TODAY    = "sensor.YOUR_INVERTER_SN_LOWER_energy_today_input_1"
GROWATT_NW_TODAY    = "sensor.YOUR_INVERTER_SN_LOWER_energy_today_input_2"
GROWATT_TOTAL_TODAY = "sensor.YOUR_INVERTER_SN_LOWER_energy_today"


class AxleV3Engine(hass.Hass):

    def initialize(self):
        self.log("=" * 60)
        self.log("AXLE v3.1 Energy Intelligence Engine starting")
        self.log("=" * 60)
        self.memory = self._load_memory()
        obs = len(self.memory.get("observations", []))
        profiles = len(self.memory.get("daily_loads", {}))
        self.log(f"Memory: {obs} observations, {profiles} shift profiles")
        self.run_daily(self.overnight_charge_decision, "01:30:00")
        self.run_daily(self.record_daily_observation, "23:50:00")
        self.run_daily(self.self_validate, "23:55:00")
        self.run_in(self.startup_check, 30)
        self.run_in(self.publish_simulation_curve, 35)
        self.run_every(self.cheap_rate_watchdog, "now+60", 30*60)
        self.run_every(self.export_soc_watchdog, "now+60", 2*60)
        self.run_in(self.attempt_growatt_bootstrap, 60)
        self.log("Scheduled: charge=01:30 observe=23:50 validate=23:55")

    # ── STARTUP ───────────────────────────────────────────────

    def startup_check(self, kwargs):
        soc = self._f("sensor.aio_YOUR_GIVENERGY_SERIAL_soc", 50)
        pv = self._f("sensor.aio_YOUR_GIVENERGY_SERIAL_pv_power", 0)
        load = self._f("sensor.aio_YOUR_GIVENERGY_SERIAL_load_power", 0)
        solar_today = self._f("sensor.solar_forecast_kwh", 0)
        shift_today = self._get_shift_type(datetime.now())
        shift_tomorrow = self._get_shift_type(datetime.now() + timedelta(days=1))
        days_since_100 = self._days_since_full_charge()
        self.log(f"Status: SOC={soc}% PV={pv}W Load={load}W")
        self.log(f"Shift today={shift_today} tomorrow={shift_tomorrow}")
        self.log(f"Solar forecast today={solar_today}kWh")
        self.log(f"Days since 100% SOC: {days_since_100}")
        self.log(f"Load profiles: {list(self.memory.get('daily_loads',{}).keys())}")
        self.log(f"Solar corrections: {self.memory.get('solar_corrections',{})}")
        self.set_state("sensor.axle_v3_status", state="RUNNING",
            attributes={
                "observations": len(self.memory.get("observations",[])),
                "accuracy_score": self.memory.get("accuracy_score", 0),
                "last_decision": self.memory.get("last_charge_decision","never"),
                "last_observation": self.memory.get("last_observation_date","never"),
                "shift_today": shift_today,
                "shift_tomorrow": shift_tomorrow,
                "days_since_full_charge": days_since_100,
                "friendly_name": "AXLE v3 Status"
            })
        # Publish shift sensor
        self.set_state("sensor.axle_shift_today", state=shift_today,
            attributes={
                "shift_tomorrow": shift_tomorrow,
                "cycle_position": self._get_cycle_position(datetime.now()),
                "shift_week": self._get_shift_week(datetime.now()),
                "friendly_name": "AXLE Shift Today"
            })

    # ── SHIFT CYCLE HELPERS ───────────────────────────────────

    def _get_cycle_position(self, dt):
        """Return position in 21-day cycle (0-20)."""
        ref = datetime.strptime(SHIFT_CYCLE_REF, "%Y-%m-%d")
        days = (dt.date() - ref.date()).days
        return days % 21

    def _get_shift_week(self, dt):
        """Return shift week number (1, 2 or 3)."""
        pos = self._get_cycle_position(dt)
        return (pos // 7) + 1

    def _get_shift_type(self, dt):
        """Return shift type for a given date."""
        # Check bank holiday first
        workday = self.get_state("binary_sensor.workday")
        if dt.date() == datetime.now().date():
            is_workday = workday == "on"
            if not is_workday and dt.weekday() < 5:
                return "BANK_HOLIDAY"
        pos = self._get_cycle_position(dt)
        return SHIFT_PATTERN.get(pos, "OFF")

    def _days_since_full_charge(self):
        """Return days since battery last reached 100% SOC."""
        last_full = self.memory.get("last_full_charge_date")
        if not last_full:
            return 999
        try:
            last_dt = datetime.strptime(last_full, "%Y-%m-%d")
            return (datetime.now() - last_dt).days
        except Exception:
            return 999

    # ── OVERNIGHT CHARGE DECISION ─────────────────────────────

    def overnight_charge_decision(self, kwargs):
        self.log("=" * 60)
        self.log("AXLE v3.1: Overnight charge decision")
        soc = self._f("sensor.aio_YOUR_GIVENERGY_SERIAL_soc", 50)
        capacity = self._f("input_number.axle_battery_capacity", BATTERY_CAPACITY_KWH)
        charge_kw = self._f("input_number.axle_charge_power", 5.0)
        confidence = self._f("sensor.axle_forecast_confidence", 100)

        tomorrow = datetime.now() + timedelta(days=1)
        shift_type = self._get_shift_type(tomorrow)
        self.log(f"Tomorrow: {tomorrow.strftime('%A')} shift={shift_type}")
        self.log(f"Current SOC: {soc}% Confidence: {confidence}%")

        # Adaptive SOC floor based on forecast confidence
        if confidence < 50:
            soc_floor = SOC_MIN_FLOOR + 10
            self.log(f"Low confidence ({confidence}%) — raising floor to {soc_floor}%")
        elif confidence < 75:
            soc_floor = SOC_MIN_FLOOR + 5
            self.log(f"Medium confidence ({confidence}%) — raising floor to {soc_floor}%")
        else:
            soc_floor = SOC_MIN_FLOOR

        solar = self._solar_forecast_tomorrow()
        load = self._predicted_load(shift_type)
        dd = self._f("sensor.axle_degree_days_today", 0)
        load += dd * 0.3
        self.log(f"Solar={solar:.1f}kWh Load={load:.1f}kWh DD={dd:.1f}")

        sim = self._simulate(soc, solar, load, capacity, shift_type)
        min_soc = min(p["soc"] for p in sim)
        end_soc = sim[-1]["soc"]
        self.log(f"Simulation: min={min_soc:.1f}% end={end_soc:.1f}%")

        # Core decision logic
        if soc < soc_floor:
            needed = soc_floor - soc + CHARGE_SAFETY_BUFFER
            reason = f"SOC {soc}% below floor {soc_floor}%"
        elif min_soc < soc_floor:
            needed = (soc_floor - min_soc) + CHARGE_SAFETY_BUFFER
            reason = f"Forecast min {min_soc:.1f}% below floor {soc_floor}%"
        else:
            needed = 0
            reason = (f"Solar {solar:.1f}kWh sufficient. "
                      f"Min SOC {min_soc:.1f}% stays above {soc_floor}%")

        # Winter full charge strategy
        month = datetime.now().month
        if month in WINTER_MONTHS and solar < WINTER_SOLAR_THRESHOLD:
            needed = max(100 - soc, 0)
            reason += (f" | Winter: solar {solar:.1f}kWh "
                       f"< {WINTER_SOLAR_THRESHOLD}kWh — charging to 100%")
            self.log(f"Winter full-charge: solar={solar:.1f}kWh → 100%")

        # BMS cell balancing
        days_since_100 = self._days_since_full_charge()
        if days_since_100 >= BMS_BALANCE_DAYS:
            needed = max(100 - soc, needed)
            reason += f" | BMS balance: {days_since_100} days since full charge"
            self.log(f"BMS balance charge triggered: {days_since_100} days since 100%")

        target = min(round(soc + needed), 100)
        self.log(f"Decision: needed={needed:.1f}% target={target}% shift={shift_type}")
        self.log(f"Reason: {reason}")

        self._apply_decision(needed > 0, target, charge_kw)
        self._notify_charge_decision(needed > 0, target, reason, solar, load, min_soc, shift_type)

        self.memory["last_charge_decision"] = datetime.now().isoformat()
        self.memory["last_charge_decision_detail"] = {
            "date": tomorrow.strftime("%Y-%m-%d"),
            "shift_type": shift_type,
            "soc_at_decision": soc,
            "solar_forecast": round(solar, 2),
            "load_forecast": round(load, 2),
            "min_soc_predicted": round(min_soc, 1),
            "charge_needed_pct": round(needed, 1),
            "charge_target_soc": target,
            "reason": reason,
            "charge_needed": needed > 0,
            "confidence": round(confidence, 1),
            "simulation": sim
        }
        self._save()
        self.run_in(self.publish_simulation_curve, 5)

        self.set_state("sensor.axle_charge_decision", state=target,
            attributes={
                "charge_needed": needed > 0,
                "needed_pct": round(needed, 1),
                "reason": reason,
                "solar_kwh": round(solar, 2),
                "load_kwh": round(load, 2),
                "min_soc": round(min_soc, 1),
                "shift_type": shift_type,
                "confidence": round(confidence, 1),
                "unit_of_measurement": "%",
                "friendly_name": "AXLE Charge Target"
            })
        self.log("=" * 60)

    def _apply_decision(self, charge, target, charge_kw):
        if charge:
            self.log(f"Enabling charge: 02:00-05:00 target={target}%")
            self.call_service("switch/turn_on",
                entity_id="switch.aio_YOUR_GIVENERGY_SERIAL_enable_charge_schedule")
            self.call_service("select/select_option",
                entity_id="select.aio_YOUR_GIVENERGY_SERIAL_charge_start_time_slot_1",
                option="02:00:00")
            self.call_service("select/select_option",
                entity_id="select.aio_YOUR_GIVENERGY_SERIAL_charge_end_time_slot_1",
                option="05:00:00")
            self.call_service("number/set_value",
                entity_id="number.aio_YOUR_GIVENERGY_SERIAL_charge_target_soc_1",
                value=target)
            self.call_service("number/set_value",
                entity_id="number.aio_YOUR_GIVENERGY_SERIAL_battery_charge_rate",
                value=int(charge_kw * 1000))
        else:
            self.log("No charge needed — disabling schedule")
            self.call_service("switch/turn_off",
                entity_id="switch.aio_YOUR_GIVENERGY_SERIAL_enable_charge_schedule")

    # ── SIMULATION ────────────────────────────────────────────

    def _simulate(self, start_soc, solar_kwh, load_kwh, capacity, shift_type):
        month = (datetime.now() + timedelta(days=1)).month
        nw_w = NW_SEASONAL_WEIGHT.get(month, 0.5)
        rad = self.get_state("sensor.solar_weather_raw", attribute="shortwave_radiation")
        cloud = self.get_state("sensor.solar_weather_raw", attribute="cloud_cover")
        correction = self._solar_correction(month)
        sol_start = int(self._f("sensor.axle_solar_start_hour", 7))
        sol_end = int(self._f("sensor.axle_solar_end_hour", 20))

        # Get shift-specific hourly weights
        weights = SHIFT_HOURLY_WEIGHTS.get(shift_type,
                  SHIFT_HOURLY_WEIGHTS["OFF"])
        total_weight = sum(weights.values())

        result = []
        soc = start_soc
        for h in range(24):
            # Solar
            if h < sol_start or h > sol_end:
                pv = 0.0
            elif rad and cloud and len(rad) > h + 24:
                r = float(rad[h+24])
                c = float(cloud[h+24])
                se = SE_HOUR.get(h, 0.0)
                nw = NW_HOUR.get(h, 0.0) * nw_w
                combined = (se + nw) / (1.0 + nw_w)
                pv = (r/1000)*((100-c)/100)*combined*(NUM_PANELS_SE+NUM_PANELS_NW)*PANEL_RATING_W/1000*correction
            else:
                pv = 0.0

            # Load — shift-aware hourly distribution
            hl = load_kwh * weights.get(h, 0.5) / total_weight

            # Charging
            if CHEAP_RATE_START <= h < CHEAP_RATE_END and soc < 99:
                net = pv - hl + self._f("input_number.axle_charge_power", 5.0)
            else:
                net = pv - hl

            soc = max(0.0, min(100.0, soc + (net/capacity)*100))
            result.append({"h":h, "soc":round(soc,1), "pv_kw":round(pv,2),
                           "load_kw":round(hl,2), "net_kw":round(net,2)})
        return result

    def _solar_forecast_tomorrow(self):
        """Solcast primary, Open-Meteo fallback."""
        solcast = self._f("sensor.solcast_pv_forecast_forecast_tomorrow", 0)
        if solcast > 0:
            self.log(f"Solar forecast (Solcast): {solcast:.2f} kWh")
            return round(solcast, 2)
        self.log("Solcast unavailable — Open-Meteo fallback", level="WARNING")
        rad = self.get_state("sensor.solar_weather_raw", attribute="shortwave_radiation")
        cloud = self.get_state("sensor.solar_weather_raw", attribute="cloud_cover")
        if not rad or not cloud:
            return self._f("sensor.solar_forecast_kwh", 5.0)
        month = (datetime.now() + timedelta(days=1)).month
        nw_w = NW_SEASONAL_WEIGHT.get(month, 0.5)
        correction = self._solar_correction(month)
        sol_start = int(self._f("sensor.axle_solar_start_hour", 7))
        sol_end = int(self._f("sensor.axle_solar_end_hour", 20))
        total = 0.0
        for h in range(24):
            if h < sol_start or h > sol_end: continue
            idx = h+24 if len(rad) > h+24 else h
            r = float(rad[idx]); c = float(cloud[idx])
            se = SE_HOUR.get(h, 0.0); nw = NW_HOUR.get(h, 0.0) * nw_w
            combined = (se + nw) / (1.0 + nw_w)
            total += (r/1000)*((100-c)/100)*combined*(NUM_PANELS_SE+NUM_PANELS_NW)*PANEL_RATING_W/1000*correction
        return round(total, 2)

    def _predicted_load(self, shift_type):
        """Get predicted load using shift-type aware profiles."""
        daily_loads = self.memory.get("daily_loads", {}).get(shift_type, [])
        if len(daily_loads) >= 3:
            weights = list(range(1, len(daily_loads)+1))
            return round(sum(l*w for l,w in zip(daily_loads,weights))/sum(weights), 2)
        # Fall back to bootstrap value for this shift type
        bootstrap = SHIFT_LOAD_BOOTSTRAP.get(shift_type, 10.0)
        self.log(f"Using bootstrap load for {shift_type}: {bootstrap}kWh")
        return bootstrap

    def _solar_correction(self, month):
        return self.memory.get("solar_corrections", {}).get(str(month), 1.0)

    # ── DAILY OBSERVATION ─────────────────────────────────────

    def record_daily_observation(self, kwargs):
        self.log("AXLE v3.1: Recording daily observation")
        today = datetime.now().strftime("%Y-%m-%d")
        shift_type = self._get_shift_type(datetime.now())

        load = self._f("sensor.aio_YOUR_GIVENERGY_SERIAL_load_energy_today_kwh", 0)
        pv_givenergy = self._f("sensor.aio_YOUR_GIVENERGY_SERIAL_pv_energy_today_kwh", 0)
        pv_growatt = self._f(GROWATT_TOTAL_TODAY, 0)
        pv_se = self._f(GROWATT_SE_TODAY, 0)
        pv_nw = self._f(GROWATT_NW_TODAY, 0)
        pv_actual = pv_growatt if pv_growatt > 0 else pv_givenergy
        forecast = self._f("sensor.solar_forecast_kwh", 0)
        soc = self._f("sensor.aio_YOUR_GIVENERGY_SERIAL_soc", 50)
        dd = self._f("sensor.axle_degree_days_today", 0)

        # Track if battery reached 100% today
        if soc >= 99.0:
            self.memory["last_full_charge_date"] = today
            self.log("Battery reached 100% today — BMS balance timer reset")

        # Record NW/SE ratio
        if pv_se > 0 and pv_nw > 0:
            month = str(datetime.now().month)
            ratios = self.memory.get("nw_se_ratios", {})
            month_ratios = ratios.get(month, [])
            month_ratios.append(round(pv_nw/pv_se, 3))
            if len(month_ratios) > 30: month_ratios = month_ratios[-30:]
            ratios[month] = month_ratios
            self.memory["nw_se_ratios"] = ratios

        obs = {
            "date": today, "shift_type": shift_type,
            "load": round(load,2), "pv": round(pv_actual,2),
            "pv_se": round(pv_se,2), "pv_nw": round(pv_nw,2),
            "soc_end": round(soc,1), "degree_days": round(dd,2),
            "forecast_solar": round(forecast,2)
        }
        self.log(f"Observation: {json.dumps(obs)}")

        observations = self.memory.get("observations", [])
        observations.append(obs)
        if len(observations) > LEARNING_DAYS * 21:
            observations = observations[-(LEARNING_DAYS*21):]
        self.memory["observations"] = observations
        self.memory["last_observation_date"] = today

        # Update shift-type load profile
        loads = self.memory.get("daily_loads", {})
        shift_loads = loads.get(shift_type, [])
        shift_loads.append(round(load, 2))
        if len(shift_loads) > LEARNING_DAYS: shift_loads = shift_loads[-LEARNING_DAYS:]
        loads[shift_type] = shift_loads
        self.memory["daily_loads"] = loads
        self.log(f"Load profile updated: {shift_type}={load:.1f}kWh "
                 f"({len(shift_loads)} observations)")

        # Adaptive solar correction
        if forecast >= 0.5:
            month = str(datetime.now().month)
            corrections = self.memory.get("solar_corrections", {})
            current = corrections.get(month, 1.0)
            ratio = max(0.3, min(2.0, pv_actual/forecast))
            error_magnitude = abs(ratio - current) / current

            # Adaptive learning rate — faster correction when error is large
            if error_magnitude > 0.3:
                alpha = 0.4   # Large error — learn faster
                self.log(f"Solar correction: large error ({error_magnitude:.2f}) — fast learning")
            elif error_magnitude > 0.15:
                alpha = 0.25  # Medium error
            else:
                alpha = 0.1   # Small error — stable, learn slowly
                self.log(f"Solar correction: small error ({error_magnitude:.2f}) — stable")

            corrections[month] = round(current*(1-alpha) + ratio*alpha, 3)
            self.memory["solar_corrections"] = corrections
            self.log(f"Solar correction m{month}: {current:.3f}→{corrections[month]:.3f} "
                     f"(actual={pv_actual:.1f} forecast={forecast:.1f} α={alpha})")

        self._save()
        self.log(f"Observation saved: shift={shift_type} load={load:.1f}kWh "
                 f"pv={pv_actual:.1f}kWh SE={pv_se:.1f} NW={pv_nw:.1f}")

    # ── SELF VALIDATION ───────────────────────────────────────

    def self_validate(self, kwargs):
        self.log("AXLE v3.1: Self-validation")
        last = self.memory.get("last_charge_decision_detail", {})
        if not last: return
        predicted = last.get("min_soc_predicted", 50)
        actual = self._f("sensor.aio_YOUR_GIVENERGY_SERIAL_soc", 50)
        error = predicted - actual
        accuracy = max(0, 100 - abs(error)*2)
        self.memory["accuracy_score"] = round(accuracy, 1)
        self.memory["last_error"] = round(error, 1)
        self.call_service("input_number/set_value",
            entity_id="input_number.axle_soc_forecast_error", value=round(error,1))
        self.call_service("input_number/set_value",
            entity_id="input_number.axle_soc_accuracy_score", value=round(accuracy,1))
        self.log(f"Validation: predicted={predicted:.1f}% actual={actual:.1f}% "
                 f"error={error:.1f}% accuracy={accuracy:.1f}%")
        self._save()

    # ── PUBLISH SIMULATION CURVE ──────────────────────────────

    def publish_simulation_curve(self, kwargs=None):
        detail = self.memory.get("last_charge_decision_detail", {})
        sim = detail.get("simulation", [])
        if not sim: return
        decision_date = detail.get("date", "")
        if not decision_date: return
        try:
            base = datetime.strptime(decision_date, "%Y-%m-%d")
        except Exception:
            return
        curve = []
        for point in sim:
            h = point.get("h", 0)
            ts = base + timedelta(hours=h)
            curve.append({"t": ts.isoformat(), "soc": point.get("soc",0),
                          "pv_kw": point.get("pv_kw",0),
                          "load_kw": point.get("load_kw",0),
                          "net_kw": point.get("net_kw",0)})
        min_soc = min(p["soc"] for p in sim)
        max_soc = max(p["soc"] for p in sim)
        min_hour = next(p["h"] for p in sim if p["soc"] == min_soc)
        self.set_state("sensor.axle_soc_simulation_curve", state="OK",
            attributes={"curve": curve, "decision_date": decision_date,
                        "shift_type": detail.get("shift_type",""),
                        "solar_forecast": detail.get("solar_forecast",0),
                        "load_forecast": detail.get("load_forecast",0),
                        "min_soc_predicted": round(min_soc,1),
                        "max_soc_predicted": round(max_soc,1),
                        "min_soc_hour": min_hour,
                        "charge_needed": detail.get("charge_needed",False),
                        "charge_target": detail.get("charge_target_soc",0),
                        "reason": detail.get("reason",""),
                        "friendly_name": "AXLE SOC Simulation Curve"})
        self.log(f"Simulation curve: {len(curve)} points "
                 f"min={min_soc:.1f}% at h{min_hour} max={max_soc:.1f}%")

    # ── EASY WINS ─────────────────────────────────────────────

    def _notify_charge_decision(self, charge_needed, target_soc, reason,
                                 solar_kwh, load_kwh, min_soc, shift_type):
        days_since_100 = self._days_since_full_charge()
        if charge_needed:
            title = f"AXLE: Charging to {target_soc}% tonight"
            message = (f"Shift: {shift_type} | "
                       f"Solar: {solar_kwh:.1f}kWh | Load: {load_kwh:.1f}kWh | "
                       f"Min SOC: {min_soc:.1f}% | {reason}")
        else:
            title = "AXLE: No charge needed tonight"
            message = (f"Shift: {shift_type} | "
                       f"Solar {solar_kwh:.1f}kWh covers {load_kwh:.1f}kWh load | "
                       f"Min SOC: {min_soc:.1f}% | "
                       f"Days since full: {days_since_100}")
        try:
            self.call_service("notify/notify", title=title, message=message)
            self.log(f"Notification: {title}")
        except Exception as e:
            self.log(f"Notification failed: {e}", level="WARNING")

    def cheap_rate_watchdog(self, kwargs):
        h = datetime.now().hour
        if not (CHEAP_RATE_START <= h < CHEAP_RATE_END): return
        last = self.memory.get("last_charge_decision_detail", {})
        if not last.get("charge_needed", False): return
        soc = self._f("sensor.aio_YOUR_GIVENERGY_SERIAL_soc", 50)
        bat = self._f("sensor.aio_YOUR_GIVENERGY_SERIAL_battery_power", 0)
        schedule = self._get_state("switch.aio_YOUR_GIVENERGY_SERIAL_enable_charge_schedule", "off")
        target = last.get("charge_target_soc", 100)
        if soc >= target:
            self.log("Watchdog: target reached — disabling schedule")
            self.call_service("switch/turn_off",
                entity_id="switch.aio_YOUR_GIVENERGY_SERIAL_enable_charge_schedule")
            return
        if schedule == "on" and bat > -100:
            self.log("Watchdog: not charging — re-applying", level="WARNING")
            self._apply_decision(True, target,
                                 self._f("input_number.axle_charge_power", 5.0))
            try:
                self.call_service("notify/notify",
                    title="AXLE: Charge watchdog triggered",
                    message=f"Re-applied charge. SOC={soc}% target={target}%")
            except Exception as e:
                self.log(f"Watchdog notify failed: {e}", level="WARNING")

    def export_soc_watchdog(self, kwargs):
        if self._get_state("sensor.axle_export_window_active","off") != "on": return
        soc = self._f("sensor.aio_YOUR_GIVENERGY_SERIAL_soc", 50)
        if soc <= SOC_MIN_FLOOR:
            self.log(f"EXPORT SOC FLOOR: SOC={soc}% — returning to Eco",
                     level="WARNING")
            self.call_service("select/select_option",
                entity_id="select.aio_YOUR_GIVENERGY_SERIAL_mode", option="Eco")
            self.call_service("switch/turn_on",
                entity_id="switch.aio_YOUR_GIVENERGY_SERIAL_eco_mode")
            self.call_service("select/select_option",
                entity_id="select.aio_YOUR_GIVENERGY_SERIAL_force_export", option="Normal")
            try:
                self.call_service("notify/notify",
                    title="AXLE: Export stopped — battery floor",
                    message=f"SOC {soc}% during export. Returned to Eco.")
            except Exception as e:
                self.log(f"Notify failed: {e}", level="WARNING")

    def attempt_growatt_bootstrap(self, kwargs):
        corrections = self.memory.get("solar_corrections", {})
        if len(corrections) >= 6:
            self.log("Growatt bootstrap: sufficient data — skipping")
            return
        username = self.args.get("growatt_username", "")
        password = self.args.get("growatt_password", "")
        plant_id = self.args.get("growatt_plant_id", "YOUR_PLANT_ID")
        if not username or not password:
            self.log("Growatt bootstrap: no credentials", level="WARNING")
            return
        try:
            import growattServer
            api = growattServer.GrowattApi()
            login = api.login(username, password)
            self.log(f"Growatt bootstrap: logged in")
            monthly = {}
            for m in range(6):
                target = datetime.now() - timedelta(days=m*30)
                ms = target.strftime("%Y-%m")
                mk = str(target.month)
                try:
                    data = api.plant_detail(plant_id, 2, ms)
                    if data and "datas" in data:
                        total = sum(float(d.get("epvtotal",0))
                                   for d in data["datas"] if d.get("epvtotal"))
                        monthly.setdefault(mk, []).append(total)
                        self.log(f"Growatt: {ms}={total:.1f}kWh")
                except Exception as e:
                    self.log(f"Growatt {ms}: {e}", level="WARNING")
            if monthly:
                self.memory["growatt_monthly_totals"] = monthly
                self._save()
        except Exception as e:
            self.log(f"Growatt bootstrap failed: {e}", level="WARNING")

    # ── MEMORY ────────────────────────────────────────────────

    def _load_memory(self):
        if os.path.exists(MEMORY_FILE):
            try:
                with open(MEMORY_FILE) as f:
                    return json.load(f)
            except Exception as e:
                self.log(f"Memory load error: {e}", level="WARNING")
        return {
            "observations": [], "daily_loads": {},
            "solar_corrections": {}, "accuracy_score": 0,
            "last_charge_decision": None, "last_observation_date": None,
            "last_full_charge_date": None
        }

    def _save(self):
        try:
            with open(MEMORY_FILE, "w") as f:
                json.dump(self.memory, f, indent=2, default=str)
        except Exception as e:
            self.log(f"Memory save error: {e}", level="ERROR")

    # ── HELPERS ───────────────────────────────────────────────

    def _f(self, entity_id, default=0.0):
        try:
            s = self.get_state(entity_id)
            return float(s) if s not in (None,"unknown","unavailable","") else default
        except: return default

    def _get_state(self, entity_id, default="unknown"):
        try:
            s = self.get_state(entity_id)
            return s if s not in (None,"") else default
        except: return default
