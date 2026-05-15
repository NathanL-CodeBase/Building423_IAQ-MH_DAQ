# NIST Building 423 IAQ Manufactured House - Instrument Documentation

This document provides detailed descriptions and specifications for all active instruments in the NIST Building 423 IAQ Manufactured House Data Acquisition and Backup System.

## Table of Contents
1. [Met One AIO 2 Sonic Weather Sensor](#met-one-aio-2-sonic-weather-sensor)
2. [Vaisala HUMICAP HMP155 Humidity and Temperature Probe](#vaisala-humicap-hmp155-humidity-and-temperature-probe)
3. [Vaisala HUMICAP HMP45A Humidity and Temperature Probe](#vaisala-humicap-hmp45a-humidity-and-temperature-probe)

---

## Met One AIO 2 Sonic Weather Sensor

**Description:** Met One AIO 2 Sonic Weather Sensor - 10m MET Tower  
**Manufacturer:** Met One Instruments  
**Model:** AIO 2  
**Status:** ACTIVE  
**Measurement:** Wind Speed, Wind Direction, Ambient Temperature, Relative Humidity, Barometric Pressure  
**Output:** RS-232, RS-485, SDI-12  
**Connection:** Serial (RS-232) - separate from cDAQ  
**Date Format:** `%Y%m%d`   
**Base Path:** MH DAQ/weather_station  
**Datetime Columns:** Date, Time

### Variables
- Wind_Speed_m/s
- Wind_Direction_deg
- Ambient_Temperature_degC
- Relative_Humidity_%
- Barometric_Pressure_mb

### Specifications

| Parameter | Range | Accuracy | Resolution |
|-----------|-------|----------|------------|
| Wind Speed | 0-75 m/s (calibrated 0-60 m/s) | ±0.5 m/s or 5% of reading (whichever is greater) | 0.1 m/s |
| Wind Direction | 0-360° | ±5° (including compass) | 1.0° |
| Temperature | -40°C to +60°C | ±0.2°C (0-60°C), ±0.5°C (-40-0°C) | 0.1°C |
| Relative Humidity | 0-100% | ±3% at 25°C | 1.0% |
| Barometric Pressure | 500-1100 hPa (mbar) | ±0.5 hPa at 25°C | 0.1 hPa |

### Notes
- Sensor installed on a 10m MET Tower.
- Data logged via serial output at 1 Hz.
- Tab-delimited format with Date and Time columns.
- NOT connected to cDAQ - uses separate serial connection.

---

## Vaisala HUMICAP HMP155 Humidity and Temperature Probe

**Description:** Vaisala HUMICAP HMP155 Humidity and Temperature Probe  
**Manufacturer:** Vaisala  
**Model:** HMP155  
**Status:** ACTIVE  
**Measurement:** Relative Humidity, Temperature  
**Output:** 0-10 VDC  
**Excitation:** 24 VDC  
**DAQ Connection:** Module 3-5 (NI 9201)  
**Date Format:** `%Y%m%d`    
**Base Path:** MH DAQ/indoor_daq  
**Datetime Columns:** Date, Time

### Variables
**Relative Humidity:**
- RH_Bed1_M3_C0
- RH_Liv_M3_C3
- RH_Fam_M3_C4
- RH_HVAC-S_M4_C3

**Temperature:**
- T_Bed1_M4_C4
- T_Liv_M4_C7
- T_Fam_M5_C0
- T_HVAC-S_M5_C7

### Specifications

| Parameter | Range | Accuracy | Notes |
|-----------|-------|----------|-------|
| Relative Humidity | 0-100% RH | ±1% RH (0-90% RH), ±1.7% RH (90-100% RH) | at 15-25°C |
| Relative Humidity | 0-100% RH | ±(1.0 + 0.008 × reading) % RH | at -20 to +40°C |
| Relative Humidity | 0-100% RH | ±(1.2 + 0.012 × reading) % RH | at -40 to -20°C |
| Relative Humidity | 0-100% RH | ±(1.2 + 0.012 × reading) % RH | at +40 to +60°C |
| Relative Humidity | 0-100% RH | ±(1.4 + 0.032 × reading) % RH | at -60 to -40°C |
| Temperature | -80°C to +60°C | ±(0.226 - 0.0027 x reading) °C | at -80 to +20°C |
| Temperature | -80°C to +60°C | ±(0.055 + 0.0057 x reading) °C | at +20 to +60°C |

### Notes
- Higher accuracy probes used at key monitoring locations.
- Recommended calibration interval: 1 year.

---

## Vaisala HUMICAP HMP45A Humidity and Temperature Probe

**Description:** Vaisala HUMICAP HMP45A Humidity and Temperature Probe  
**Manufacturer:** Vaisala  
**Model:** HMP45A  
**Status:** ACTIVE  
**Measurement:** Relative Humidity, Temperature  
**Output:** 0-1 VDC  
**Excitation:** 7-35 VDC  
**DAQ Connection:** Module 3-5 (NI 9201)  
**Date Format:** `%Y%m%d`   
**Base Path:** MH DAQ/indoor_daq  
**Datetime Columns:** Date, Time

### Variables
**Relative Humidity:**
- RH_Bed2_M3_C1
- RH_Bed3_M3_C2
- RH_MBa_M3_C5
- RH_Ba1_M3_C6
- RH_UR_M3_C7
- RH_Gar_M4_C0
- RH_Attic_M4_C1
- RH_Out_M4_C2

**Temperature:**
- T_Bed2_M4_C5
- T_Bed3_M4_C6
- T_MBa_M5_C1
- T_Ba1_M5_C2
- T_UR_M5_C3
- T_Gar_M5_C4
- T_Attic_M5_C5
- T_Out_M5_C6

### Specifications

| Parameter | Range | Accuracy | Notes |
|-----------|-------|----------|-------|
| Relative Humidity | 0.8-100% RH | ±1% RH at 20°C | factory calibration |
| Relative Humidity | 0-100% RH | ±2% RH (0-90% RH), ±3% RH (90-100% RH) | field accuracy |
| Relative Humidity | - | better than 1% RH/year | long term stability |
| Temperature | -39.2°C to +60°C | ±0.2°C at 20°C | |

### Notes
- Legacy sensors - planned replacement with HMP155.
- Used at secondary monitoring locations.

---