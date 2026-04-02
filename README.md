# CAMeSM-2026-Attendance-Tracking-Validation-Tool


Internal tool used to manage and validate attendance for **CAMeSM 2026 (Cyprus Annual Medical Students Meeting)**.

It processes exported CSV data from the registration system and on-site QR scanning forms, then builds structured attendance records for each participant, along with multiple layers of validation and analytics.

---

## Overview

This project was built to solve a very specific operational problem:

- Track who attended which sessions
- Ensure fairness for certificate eligibility
- Detect invalid or suspicious scans (e.g. fake entries, timing inconsistencies)

The system takes raw CSV exports (registration + scans) and turns them into a clean, queryable dataset with both individual and global insights.

---

## Core Functionality

### 1. Data Integration
- Imports **registration CSVs** (participant info)
- Imports **scan CSVs** (QR check-ins)
- Supports:
  - Multiple CSV files
  - Workshop-based CSVs with session columns
  - Automatic column normalisation and mapping

### 2. Schedule-Aware Validation
- Loads a **conference schedule (JSON)**
- Matches scans to sessions using:
  - Exact match
  - Fuzzy name matching
  - Time-window validation (with grace periods)

### 3. Attendance Tracking
- Tracks:
  - Total scans
  - Unique participants
  - Sessions attended per participant
- Generates:
  - Eligibility lists (based on threshold)
  - Per-session attendance counts
  - Full attendance matrix

### 4. Anomaly Detection

Built to catch common real-world issues:

- **Duplicate scans**
- **Impossible travel**
  - Same participant scanned in different sessions within unrealistic time
- **Out-of-window scans**
  - Too early / too late relative to session schedule
- **Isolated scans**
  - Suspicious single entries with no nearby activity
- **IP-based patterns**
  - Multiple participants from same IP

### 5. Participant-Level Reports
- Generates detailed **HTML reports** per participant:
  - Sessions attended
  - Scan timestamps
  - Timing relative to schedule
  - Eligibility status

### 6. Visual Analytics
- Session attendance distribution
- Eligibility curves
- Session correlation matrix
- Timing behaviour vs schedule

### 7. GUI Interface
- Built with `customtkinter`
- Includes:
  - Dashboard overview
  - Search functionality
  - Participant lookup
  - Scan audit tools
  - Import/export controls

---

## Tech Stack

- **Python**
- **pandas / numpy** – data processing
- **customtkinter** – GUI
- **matplotlib** – visual analytics

---

## Input Requirements

### Registration CSV
Must include (or equivalent):
- participant ID
- email
- optional: name, IP, user agent

### Scan CSV
Must include:
- participant ID
- timestamp

Optional:
- session/workshop name
- IP / user agent

### Schedule JSON
Simple format:
```json
{
  "conference": "CAMeSM 2026",
  "sessions": [
    {
      "name": "Session Name",
      "date": "2026-05-08",
      "start": "09:00",
      "end": "10:00"
    }
  ]
}
```

---

## Outputs
- Eligibility reports (CSV)
- Attendance matrix (CSV)
- Audit logs
- Participant HTML reports

---

## Notes
- This is a purpose-built internal tool, not a generalised attendance system.
- Designed specifically around how CAMeSM registration and scanning pipelines work.
- Assumes CSV exports from predefined forms (column mapping handled internally).

---

# Author
Alexandros Kordatzakis
CAMeSM 2026 – Workshops Coordinator / I.T. Specialist / Full-Stack Website Developer

## License
MIT
