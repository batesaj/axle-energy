# Configuring Shift Patterns

AXLE v3.1 supports rotating shift work patterns up to 21 days (3 weeks). This allows the load forecasting model to learn distinct energy profiles for each shift type rather than averaging them together.

## Shift types

Four shift types are supported by default:

| Type | Description | Typical daily load | Hourly profile |
|---|---|---|---|
| `OFF` | Home all day | ~13 kWh | High spread, peaks 18:00-20:00 |
| `DAYS` | Out ~09:00-19:00 | ~8.5 kWh | Low daytime, late evening peak |
| `LATES` | Out ~12:00-21:00 | ~9.5 kWh | Medium morning, very late peak |
| `SUNDAY_WORK` | Working Sunday (variable) | ~9.0 kWh | Average of DAYS/LATES |
| `BANK_HOLIDAY` | Auto-detected from HA | ~13 kWh | Same as OFF |

You can rename these or add your own types — they are just dictionary keys.

## Setting up your cycle

### Step 1 — Identify your reference date

Find a Monday that was definitively the start of Week 1 of your cycle. The further in the past the better (less likely to have been disrupted).

```python
SHIFT_CYCLE_REF   = "2026-06-01"  # Replace with your Week 1 Monday
SHIFT_CYCLE_WEEKS = 3             # Number of weeks in cycle
```

### Step 2 — Map your 21-day pattern

Each position 0-20 represents a day in the cycle:
- Position 0 = Monday of Week 1
- Position 1 = Tuesday of Week 1
- Position 6 = Sunday of Week 1
- Position 7 = Monday of Week 2
- etc.

```python
SHIFT_PATTERN = {
    0:  "OFF",    # Mon W1
    1:  "OFF",    # Tue W1
    2:  "OFF",    # Wed W1
    3:  "DAYS",   # Thu W1
    4:  "DAYS",   # Fri W1
    5:  "DAYS",   # Sat W1
    6:  "OFF",    # Sun W1
    7:  "LATES",  # Mon W2
    8:  "LATES",  # Tue W2
    9:  "OFF",    # Wed W2
    10: "OFF",    # Thu W2
    11: "OFF",    # Fri W2
    12: "OFF",    # Sat W2
    13: "OFF",    # Sun W2
    14: "DAYS",   # Mon W3
    15: "DAYS",   # Tue W3
    16: "DAYS",   # Wed W3
    17: "LATES",  # Thu W3
    18: "LATES",  # Fri W3
    19: "LATES",  # Sat W3
    20: "OFF",    # Sun W3
}
```

### Step 3 — Set bootstrap load values

Before AXLE has learned your actual load profile, it uses these starting estimates. Set them to your best guess for each shift type:

```python
SHIFT_LOAD_BOOTSTRAP = {
    "OFF":         13.0,   # kWh — both home all day
    "DAYS":         8.5,   # kWh — out during working hours
    "LATES":        9.5,   # kWh — out during afternoon/evening
    "SUNDAY_WORK":  9.0,   # kWh — working Sunday
    "BANK_HOLIDAY": 13.0,  # kWh — treat like OFF
}
```

### Step 4 — Adjust hourly weight profiles

The `SHIFT_HOURLY_WEIGHTS` dictionary controls how daily load is distributed across hours. Each hour (0-23) gets a relative weight. Higher weight = more load in that hour.

The defaults model a typical UK household with the described shift patterns. You may want to adjust these based on your own observations, particularly for:
- Electric vehicle charging times
- Immersion heater schedules
- Unusual working hours

## No shift pattern?

If your household doesn't have a shift pattern, simply set all 21 positions to day-of-week types:

```python
SHIFT_CYCLE_REF   = "2026-06-01"  # Any Monday
SHIFT_CYCLE_WEEKS = 3

SHIFT_PATTERN = {
    0: "MON", 1: "TUE", 2: "WED", 3: "THU", 4: "FRI", 5: "SAT", 6: "SUN",
    7: "MON", 8: "TUE", 9: "WED", 10: "THU", 11: "FRI", 12: "SAT", 13: "SUN",
    14: "MON", 15: "TUE", 16: "WED", 17: "THU", 18: "FRI", 19: "SAT", 20: "SUN",
}

SHIFT_LOAD_BOOTSTRAP = {
    "MON": 10.0, "TUE": 10.0, "WED": 10.0, "THU": 10.0,
    "FRI": 10.5, "SAT": 11.0, "SUN": 11.0,
    "BANK_HOLIDAY": 12.0
}
```

## Verifying your cycle

Run this in Home Assistant Developer Tools → Template to verify the cycle is tracking correctly:

```jinja
{% set ref = strptime('YOUR-WEEK1-MONDAY', '%Y-%m-%d') %}
{% set pos = ((now().date() - ref.date()).days % 21) %}
{% set pattern = {
  0:'OFF',1:'OFF',2:'OFF',3:'DAYS',4:'DAYS',5:'DAYS',6:'SUNDAY_WORK',
  7:'LATES',8:'LATES',9:'OFF',10:'OFF',11:'OFF',12:'OFF',13:'OFF',
  14:'DAYS',15:'DAYS',16:'DAYS',17:'LATES',18:'LATES',19:'LATES',20:'OFF'
} %}
Today: cycle position {{ pos }}, week {{ (pos // 7) + 1 }}, shift = {{ pattern.get(pos, 'OFF') }}
```
