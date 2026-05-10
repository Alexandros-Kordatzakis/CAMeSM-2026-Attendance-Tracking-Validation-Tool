#!/usr/bin/env python3
"""
CAMeSM Attendance Tracker — Core Data Layer  v0.8.0
════════════════════════════════════════════════════
Pure data logic: schedule, attendance store, anomaly
detection, analytics, and CSV ingestion.

v0.8.0 — Full field capture
  • Preserves ALL columns from Gravity Forms CSVs
  • Registration: phone, year, university, consents, full name parts
  • Scans: entry_id, date_updated, source_url, created_by, submission_speed
  • Workshop registration import (separate CSV type, email-matched)
  • Demographic analytics: year of studies, university breakdown
  • Device parsing from user agent strings

No GUI imports — importable for scripting, testing,
or integration with other systems (e.g. voting).

Author: Alex (CAMeSM Board – Workshops Coordinator)
"""

import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field

import pandas as pd
import numpy as np

# ══════════════════════════════════════════════════════════════════════════════
#  CONSTANTS
# ══════════════════════════════════════════════════════════════════════════════

APP_TITLE = "CAMeSM Attendance Tracker"
APP_VERSION = "0.8.0"
DEFAULT_THRESHOLD = 4          # additional sessions beyond mandatory ceremonies
DUPLICATE_GAP_MINUTES = 60     # scans within this window = duplicate; beyond = new attendance

# ── Core column names (internal) ─────────────────────────────────────────
COL_ID = "participant_id"
COL_TIMESTAMP = "scan_timestamp"
COL_SESSION = "session_name"
COL_NAME = "participant_name"
COL_EMAIL = "email"
COL_IP = "user_ip"
COL_UA = "user_agent"
COL_REG_IP = "registration_ip"

# ── Extended scan columns ────────────────────────────────────────────────
COL_ENTRY_ID = "entry_id"
COL_DATE_UPDATED = "date_updated"
COL_SOURCE_URL = "source_url"
COL_CREATED_BY = "created_by"
COL_SUBMISSION_SPEED = "submission_speed_ms"

# ── Extended registration columns ────────────────────────────────────────
COL_PHONE = "phone"
COL_YEAR = "year_of_studies"
COL_UNIVERSITY = "university"
COL_REG_DATE = "registration_date"
COL_REG_UA = "registration_ua"

# All scan columns stored in self.records
SCAN_COLS = [
    COL_ID, COL_TIMESTAMP, COL_SESSION, COL_IP, COL_UA,
    COL_ENTRY_ID, COL_DATE_UPDATED, COL_SOURCE_URL, COL_CREATED_BY, COL_SUBMISSION_SPEED,
]

# ── Column mappings: normalised GF name → internal name ──────────────────
REG_COLUMN_MAP = {
    "unique_id": COL_ID,
    "email": COL_EMAIL,
    "user_ip": COL_REG_IP,
    "user_agent": COL_REG_UA,
    "entry_date": COL_REG_DATE,
    "date_updated": COL_DATE_UPDATED,
    "source_url": COL_SOURCE_URL,
    "entry_id": COL_ENTRY_ID,
    "created_by_user_id": COL_CREATED_BY,
    "submission_speed_ms": COL_SUBMISSION_SPEED,
    "phone_number": COL_PHONE,
    "phone": COL_PHONE,
    "year_of_studies": COL_YEAR,
    "university_/_institution": COL_UNIVERSITY,
}

SCAN_COLUMN_MAP = {
    "qr_scanner": COL_ID,
    "entry_date": COL_TIMESTAMP,
    "user_ip": COL_IP,
    "user_agent": COL_UA,
    "workshop": COL_SESSION,
    "entry_id": COL_ENTRY_ID,
    "date_updated": COL_DATE_UPDATED,
    "source_url": COL_SOURCE_URL,
    "created_by_user_id": COL_CREATED_BY,
    "submission_speed_ms": COL_SUBMISSION_SPEED,
}

WORKSHOP_REG_COLUMN_MAP = {
    "email": COL_EMAIL,
    "user_ip": COL_REG_IP,
    "user_agent": COL_REG_UA,
    "entry_date": COL_REG_DATE,
    "date_updated": COL_DATE_UPDATED,
    "source_url": COL_SOURCE_URL,
    "entry_id": COL_ENTRY_ID,
    "created_by_user_id": COL_CREATED_BY,
    "submission_speed_ms": COL_SUBMISSION_SPEED,
    "phone": COL_PHONE,
    "year_of_studies": COL_YEAR,
}


# ══════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _norm_cols(df: pd.DataFrame) -> pd.DataFrame:
    """Normalise column names: strip BOM, lowercase, remove parens, collapse whitespace."""
    df.columns = (
        df.columns
        .str.replace("\ufeff", "")
        .str.strip()
        .str.lower()
        .str.replace(r"[()]", "", regex=True)
        .str.strip()
        .str.replace(r"\s+", "_", regex=True)
    )
    return df


def _map_cols(df: pd.DataFrame, mapping: dict) -> pd.DataFrame:
    """Rename columns that exist in the mapping."""
    return df.rename(columns={k: v for k, v in mapping.items() if k in df.columns})


def _build_full_name(df: pd.DataFrame) -> pd.Series:
    """Assemble full name from name_prefix / name_first / name_middle / name_last / name_suffix."""
    parts = []
    for fragment in ["prefix", "first", "middle", "last", "suffix"]:
        candidates = [c for c in df.columns if fragment in c and "name" in c]
        if candidates:
            parts.append(df[candidates[0]].fillna("").astype(str).str.strip())
    if not parts:
        fc = [c for c in df.columns if "first" in c]
        lc = [c for c in df.columns if "last" in c]
        if fc and lc:
            return (df[fc[0]].fillna("").astype(str) + " " + df[lc[0]].fillna("").astype(str)).str.strip()
        return pd.Series("", index=df.index)
    combined = parts[0]
    for p in parts[1:]:
        combined = combined + " " + p
    return combined.str.replace(r"\s+", " ", regex=True).str.strip()


def _extract_consent_labels(df: pd.DataFrame) -> list[str]:
    """Return consent text column names for building a summary."""
    return [c for c in df.columns if c.startswith("consent_text")]


def parse_device_type(ua: str) -> str:
    """Parse user agent string into device category."""
    if not ua or pd.isna(ua):
        return "Unknown"
    ua_lower = str(ua).lower()
    if any(x in ua_lower for x in ["iphone", "android", "mobile"]):
        return "Mobile"
    elif any(x in ua_lower for x in ["ipad", "tablet"]):
        return "Tablet"
    elif any(x in ua_lower for x in ["macintosh", "windows", "linux", "x11"]):
        return "Desktop"
    return "Unknown"


def parse_browser(ua: str) -> str:
    """Extract browser name from user agent string."""
    if not ua or pd.isna(ua):
        return "Unknown"
    ua_str = str(ua)
    if "Safari" in ua_str and "Chrome" not in ua_str:
        return "Safari"
    elif "Chrome" in ua_str and "Edg" not in ua_str:
        return "Chrome"
    elif "Edg" in ua_str:
        return "Edge"
    elif "Firefox" in ua_str:
        return "Firefox"
    return "Other"


def parse_submission_speed_ms(raw) -> Optional[int]:
    """Extract submission speed in ms from GF JSON like {"1":[12694]}."""
    if not raw or pd.isna(raw):
        return None
    try:
        data = json.loads(str(raw))
        if isinstance(data, dict):
            for v in data.values():
                if isinstance(v, list) and v:
                    return int(v[0])
                elif isinstance(v, (int, float)):
                    return int(v)
        return None
    except (json.JSONDecodeError, ValueError, TypeError):
        try:
            return int(float(str(raw)))
        except (ValueError, TypeError):
            return None


# ══════════════════════════════════════════════════════════════════════════════
#  SCHEDULE
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class ScheduledSession:
    name: str
    date: str
    start: str
    end: str

    @property
    def start_dt(self) -> datetime:
        return datetime.strptime(f"{self.date} {self.start}", "%Y-%m-%d %H:%M")

    @property
    def end_dt(self) -> datetime:
        return datetime.strptime(f"{self.date} {self.end}", "%Y-%m-%d %H:%M")

    @property
    def duration_min(self) -> int:
        return int((self.end_dt - self.start_dt).total_seconds() / 60)

    @property
    def day_label(self) -> str:
        return datetime.strptime(self.date, "%Y-%m-%d").strftime("%A, %d %B %Y")

    def is_within_window(self, ts: datetime, grace_min: int = 15) -> bool:
        return (self.start_dt - timedelta(minutes=grace_min)) <= ts <= (self.end_dt + timedelta(minutes=grace_min))

    def arrival_offset_min(self, ts: datetime) -> float:
        return (ts - self.start_dt).total_seconds() / 60


@dataclass
class Schedule:
    conference_name: str = ""
    sessions: list = field(default_factory=list)

    @classmethod
    def from_json(cls, filepath: str) -> "Schedule":
        with open(filepath, "r") as f:
            data = json.load(f)
        sched = cls(conference_name=data.get("conference", ""))
        for s in data.get("sessions", []):
            sched.sessions.append(ScheduledSession(
                name=s["name"], date=s["date"], start=s["start"], end=s["end"],
            ))
        sched.sessions.sort(key=lambda x: x.start_dt)
        return sched

    def match_session_by_time(self, ts: datetime, grace_min: int = 15) -> Optional[ScheduledSession]:
        for s in self.sessions:
            if s.is_within_window(ts, grace_min):
                return s
        return None

    def match_session_by_name(self, name: str) -> Optional[ScheduledSession]:
        name_l = name.strip().lower()
        for s in self.sessions:
            if s.name.lower() == name_l:
                return s
        for s in self.sessions:
            sn = s.name.lower()
            if name_l in sn or sn in name_l:
                return s
            words_s = set(sn.replace("-", " ").replace("&", " ").split())
            words_n = set(name_l.replace("-", " ").replace("&", " ").split())
            overlap = words_s & words_n
            if len(overlap) >= 2 or (len(overlap) == 1 and len(list(overlap)[0]) > 5):
                return s
        return None

    def get_session_by_name(self, name: str) -> Optional[ScheduledSession]:
        for s in self.sessions:
            if s.name == name:
                return s
        return None

    @property
    def days(self) -> list[str]:
        return sorted(set(s.date for s in self.sessions))

    def sessions_on_day(self, date: str) -> list[ScheduledSession]:
        return [s for s in self.sessions if s.date == date]


# ══════════════════════════════════════════════════════════════════════════════
#  ATTENDANCE STORE
# ══════════════════════════════════════════════════════════════════════════════

class AttendanceStore:
    def __init__(self):
        self.records = pd.DataFrame(columns=SCAN_COLS)
        self.registration: Optional[pd.DataFrame] = None
        self.workshop_registration: Optional[pd.DataFrame] = None
        self.schedule: Optional[Schedule] = None
        self.loaded_files: list[str] = []
        self.audit_log: list[dict] = []

    def _log(self, action: str, detail: str):
        self.audit_log.append({
            "timestamp": datetime.now().isoformat(),
            "action": action,
            "detail": detail,
        })

    # ── Schedule ──────────────────────────────────────────────────────────
    def load_schedule(self, filepath: str) -> int:
        self.schedule = Schedule.from_json(filepath)
        self._log("SCHEDULE_IMPORT", f"{Path(filepath).name}: {len(self.schedule.sessions)} sessions")
        return len(self.schedule.sessions)

    # ── Main Registration ─────────────────────────────────────────────────
    def load_registration(self, filepath: str) -> int:
        df = _map_cols(_norm_cols(pd.read_csv(filepath)), REG_COLUMN_MAP)
        if COL_ID not in df.columns:
            raise KeyError(f"No ID column (expected 'Unique ID'). Available: {list(df.columns)}")
        df[COL_ID] = df[COL_ID].astype(str).str.strip()
        df[COL_NAME] = _build_full_name(df)

        if COL_SUBMISSION_SPEED in df.columns:
            df[COL_SUBMISSION_SPEED] = df[COL_SUBMISSION_SPEED].apply(parse_submission_speed_ms)

        ua_col = COL_REG_UA if COL_REG_UA in df.columns else None
        if ua_col:
            df["device_type"] = df[ua_col].apply(parse_device_type)
            df["browser"] = df[ua_col].apply(parse_browser)

        consent_labels = _extract_consent_labels(df)
        if consent_labels:
            df["consents"] = df[consent_labels].apply(
                lambda row: "; ".join(str(v) for v in row if pd.notna(v) and str(v).strip()), axis=1
            )

        self.registration = df
        self._log("REG_IMPORT", f"{Path(filepath).name}: {len(df)} registrants, "
                  f"{len(df.columns)} fields preserved")
        return len(df)

    # ── Workshop Registration ─────────────────────────────────────────────
    def load_workshop_registration(self, filepath: str) -> tuple[int, int]:
        """
        Import workshop registration CSV (sign-up form, no participant_id).
        Links to main registration via email matching.
        Returns (total_rows, matched_count).
        """
        df = _map_cols(_norm_cols(pd.read_csv(filepath)), WORKSHOP_REG_COLUMN_MAP)
        df[COL_NAME] = _build_full_name(df)

        if COL_SUBMISSION_SPEED in df.columns:
            df[COL_SUBMISSION_SPEED] = df[COL_SUBMISSION_SPEED].apply(parse_submission_speed_ms)

        matched = 0
        if self.registration is not None and COL_EMAIL in df.columns and COL_EMAIL in self.registration.columns:
            email_to_id = self.registration.set_index(COL_EMAIL)[COL_ID].to_dict()
            df[COL_ID] = df[COL_EMAIL].map(email_to_id)
            matched = df[COL_ID].notna().sum()
        else:
            df[COL_ID] = pd.NA

        if self.workshop_registration is not None:
            self.workshop_registration = pd.concat([self.workshop_registration, df], ignore_index=True)
        else:
            self.workshop_registration = df

        self._log("WORKSHOP_REG_IMPORT",
                  f"{Path(filepath).name}: {len(df)} rows, {matched} matched to main registration")
        return len(df), int(matched)

    # ── Scan Import ───────────────────────────────────────────────────────
    def load_csv(self, filepath: str, session_label: Optional[str] = None) -> int:
        path = Path(filepath)
        if path.name in self.loaded_files:
            return -1

        df = _map_cols(_norm_cols(pd.read_csv(filepath)), SCAN_COLUMN_MAP)
        if COL_ID not in df.columns:
            raise KeyError(f"No ID column (expected 'QR Scanner') in '{path.name}'. "
                           f"Available: {list(df.columns)}")

        defaults = {
            COL_TIMESTAMP: datetime.now().isoformat(),
            COL_IP: "", COL_UA: "",
            COL_ENTRY_ID: "", COL_DATE_UPDATED: "", COL_SOURCE_URL: "",
            COL_CREATED_BY: "", COL_SUBMISSION_SPEED: "",
        }
        for col, default in defaults.items():
            if col not in df.columns:
                df[col] = default

        df[COL_SUBMISSION_SPEED] = df[COL_SUBMISSION_SPEED].apply(parse_submission_speed_ms)

        has_session_col = COL_SESSION in df.columns and df[COL_SESSION].notna().any()
        if has_session_col:
            df[COL_SESSION] = df[COL_SESSION].astype(str).str.strip()
            df = df[~df[COL_SESSION].isin(["nan", ""])]
            if df.empty:
                has_session_col = False

        if has_session_col:
            if self.schedule:
                def _match_name(name):
                    m = self.schedule.match_session_by_name(name)
                    return m.name if m else name
                df[COL_SESSION] = df[COL_SESSION].map(_match_name)
        elif session_label:
            df[COL_SESSION] = session_label
        else:
            df[COL_SESSION] = path.stem.replace("_", " ").replace("-", " ").title()

        new = df[SCAN_COLS].copy()
        new[COL_ID] = new[COL_ID].astype(str).str.strip()
        self.records = pd.concat([self.records, new], ignore_index=True)
        self.loaded_files.append(path.name)

        sessions_in_file = new[COL_SESSION].unique().tolist()
        if len(sessions_in_file) > 1:
            self._log("SCAN_IMPORT",
                      f"{path.name}: {len(new)} scans across {len(sessions_in_file)} sessions: "
                      f"{', '.join(sessions_in_file)}")
        else:
            self._log("SCAN_IMPORT", f"{path.name} → '{sessions_in_file[0]}': {len(new)}")
        return len(new)

    def load_folder(self, folder: str, session_labels: Optional[dict] = None) -> dict:
        results = {}
        for f in sorted(Path(folder).glob("*.csv")):
            try:
                results[f.name] = self.load_csv(str(f), session_label=(session_labels or {}).get(f.name))
            except Exception as e:
                results[f.name] = str(e)
        return results

    def rename_session(self, old: str, new: str):
        self.records.loc[self.records[COL_SESSION] == old, COL_SESSION] = new
        self._log("RENAME", f"'{old}' → '{new}'")

    # ── Attendance deduplication ──────────────────────────────────────────
    @staticmethod
    def _is_opening(session_name: str) -> bool:
        return "opening" in session_name.lower()

    @staticmethod
    def _is_closing(session_name: str) -> bool:
        return "closing" in session_name.lower()

    @staticmethod
    def _is_ceremony(session_name: str) -> bool:
        return AttendanceStore._is_opening(session_name) or AttendanceStore._is_closing(session_name)

    def _valid_attendances(self, gap_minutes: int = DUPLICATE_GAP_MINUTES) -> pd.DataFrame:
        """
        Deduplicate scans: for each (participant, session) group, scans within
        `gap_minutes` of the previous scan are collapsed into one attendance.
        Scans more than `gap_minutes` apart count as separate attendances
        (e.g. Roundtables Hour 1 vs Hour 2).

        Returns DataFrame with columns: [COL_ID, COL_SESSION, 'first_scan'].
        """
        if self.records.empty:
            return pd.DataFrame(columns=[COL_ID, COL_SESSION, "first_scan"])

        recs = self.records.copy()
        recs["ts"] = pd.to_datetime(recs[COL_TIMESTAMP], errors="coerce")
        recs = recs.dropna(subset=["ts"]).sort_values([COL_ID, COL_SESSION, "ts"])

        attendances = []
        for (pid, sess), group in recs.groupby([COL_ID, COL_SESSION]):
            last_ts = None
            for _, row in group.iterrows():
                if last_ts is None or (row["ts"] - last_ts).total_seconds() > gap_minutes * 60:
                    attendances.append({COL_ID: pid, COL_SESSION: sess, "first_scan": row["ts"]})
                    last_ts = row["ts"]

        return pd.DataFrame(attendances) if attendances else pd.DataFrame(columns=[COL_ID, COL_SESSION, "first_scan"])

    def ceremony_status(self, pid: str) -> dict:
        """Check whether a participant attended Opening and Closing ceremonies."""
        va = self._valid_attendances()
        pid_sessions = va.loc[va[COL_ID] == pid, COL_SESSION].tolist() if not va.empty else []
        return {
            "opening": any(self._is_opening(s) for s in pid_sessions),
            "closing": any(self._is_closing(s) for s in pid_sessions),
        }

    # ── Lookups ───────────────────────────────────────────────────────────
    @property
    def total_scans(self) -> int:
        return len(self.records)

    @property
    def unique_participants(self) -> int:
        return self.records[COL_ID].nunique() if not self.records.empty else 0

    @property
    def sessions(self) -> list[str]:
        return sorted(self.records[COL_SESSION].unique().tolist()) if not self.records.empty else []

    def session_count_per_participant(self) -> pd.Series:
        if self.records.empty:
            return pd.Series(dtype=int)
        va = self._valid_attendances()
        if va.empty:
            return pd.Series(dtype=int)
        return va.groupby(COL_ID).size()

    def _enrich(self, df: pd.DataFrame, cols: Optional[list] = None) -> pd.DataFrame:
        if self.registration is None or df.empty:
            return df
        cols = cols or [COL_NAME, COL_EMAIL]
        merge_cols = [COL_ID] + [c for c in cols if c in self.registration.columns]
        if len(merge_cols) > 1:
            return df.merge(self.registration[merge_cols], on=COL_ID, how="left")
        return df

    def eligible_participants(self, threshold: int = DEFAULT_THRESHOLD) -> pd.DataFrame:
        va = self._valid_attendances()
        if va.empty:
            return pd.DataFrame(columns=[COL_ID, "sessions_attended"])
        results = []
        for pid, group in va.groupby(COL_ID):
            sessions = group[COL_SESSION].tolist()
            has_opening = any(self._is_opening(s) for s in sessions)
            has_closing = any(self._is_closing(s) for s in sessions)
            others = sum(1 for s in sessions if not self._is_ceremony(s))
            if has_opening and has_closing and others >= threshold:
                results.append({COL_ID: pid, "sessions_attended": len(sessions)})
        result = pd.DataFrame(results) if results else pd.DataFrame(columns=[COL_ID, "sessions_attended"])
        return self._enrich(result.sort_values("sessions_attended", ascending=False) if not result.empty else result)

    def ineligible_participants(self, threshold: int = DEFAULT_THRESHOLD) -> pd.DataFrame:
        va = self._valid_attendances()
        if va.empty:
            return pd.DataFrame(columns=[COL_ID, "sessions_attended", "sessions_remaining", "missing"])
        eligible_ids = set()
        for pid, group in va.groupby(COL_ID):
            sessions = group[COL_SESSION].tolist()
            has_opening = any(self._is_opening(s) for s in sessions)
            has_closing = any(self._is_closing(s) for s in sessions)
            others = sum(1 for s in sessions if not self._is_ceremony(s))
            if has_opening and has_closing and others >= threshold:
                eligible_ids.add(pid)

        results = []
        for pid, group in va.groupby(COL_ID):
            if pid in eligible_ids:
                continue
            sessions = group[COL_SESSION].tolist()
            has_opening = any(self._is_opening(s) for s in sessions)
            has_closing = any(self._is_closing(s) for s in sessions)
            others = sum(1 for s in sessions if not self._is_ceremony(s))
            missing_parts = []
            remaining = 0
            if not has_opening:
                missing_parts.append("Opening")
                remaining += 1
            if not has_closing:
                missing_parts.append("Closing")
                remaining += 1
            others_needed = max(0, threshold - others)
            if others_needed > 0:
                missing_parts.append(f"+{others_needed} other{'s' if others_needed > 1 else ''}")
                remaining += others_needed
            results.append({
                COL_ID: pid,
                "sessions_attended": len(sessions),
                "sessions_remaining": remaining,
                "missing": ", ".join(missing_parts),
            })
        result = pd.DataFrame(results) if results else pd.DataFrame(
            columns=[COL_ID, "sessions_attended", "sessions_remaining", "missing"])
        return self._enrich(result.sort_values("sessions_remaining") if not result.empty else result, [COL_NAME])

    def lookup(self, pid: str) -> Optional[pd.DataFrame]:
        scans = self.records[self.records[COL_ID] == pid.strip()]
        return scans.sort_values(COL_TIMESTAMP) if not scans.empty else None

    def _get_reg_field(self, pid: str, col: str) -> str:
        if self.registration is not None and col in self.registration.columns:
            match = self.registration[self.registration[COL_ID] == pid]
            if not match.empty:
                val = match.iloc[0][col]
                return str(val) if pd.notna(val) else ""
        return ""

    def get_name(self, pid: str) -> str:
        return self._get_reg_field(pid, COL_NAME)

    def get_reg_ip(self, pid: str) -> str:
        return self._get_reg_field(pid, COL_REG_IP)

    def get_email(self, pid: str) -> str:
        return self._get_reg_field(pid, COL_EMAIL)

    def get_phone(self, pid: str) -> str:
        return self._get_reg_field(pid, COL_PHONE)

    def get_year(self, pid: str) -> str:
        return self._get_reg_field(pid, COL_YEAR)

    def get_university(self, pid: str) -> str:
        return self._get_reg_field(pid, COL_UNIVERSITY)

    def global_stats(self) -> dict:
        counts = self.session_count_per_participant()
        return {
            "total_scans": self.total_scans,
            "unique_participants": self.unique_participants,
            "total_sessions": len(self.sessions),
            "avg_sessions": round(counts.mean(), 1) if len(counts) else 0,
            "max_sessions": int(counts.max()) if len(counts) else 0,
            "min_sessions": int(counts.min()) if len(counts) else 0,
            "median_sessions": round(counts.median(), 1) if len(counts) else 0,
        }

    def attendance_per_session(self) -> pd.Series:
        if self.records.empty:
            return pd.Series(dtype=int)
        return self.records.groupby(COL_SESSION)[COL_ID].nunique().sort_values(ascending=False)

    def duplicate_scans(self) -> pd.DataFrame:
        if self.records.empty:
            return pd.DataFrame()

        recs = self.records.copy()
        recs["ts"] = pd.to_datetime(recs[COL_TIMESTAMP], errors="coerce")
        recs = recs.dropna(subset=["ts"]).sort_values([COL_ID, COL_SESSION, "ts"])

        dup_counts = []
        for (pid, sess), group in recs.groupby([COL_ID, COL_SESSION]):
            last_valid_ts = None
            cluster_count = 0
            total_dups = 0
            for _, row in group.iterrows():
                if last_valid_ts is None or (row["ts"] - last_valid_ts).total_seconds() > DUPLICATE_GAP_MINUTES * 60:
                    total_dups += max(0, cluster_count - 1)
                    last_valid_ts = row["ts"]
                    cluster_count = 1
                else:
                    cluster_count += 1
            total_dups += max(0, cluster_count - 1)
            if total_dups > 0:
                dup_counts.append({
                    COL_SESSION: sess, COL_ID: pid,
                    "scan_count": len(group), "duplicate_count": total_dups,
                })

        if not dup_counts:
            return pd.DataFrame()
        return pd.DataFrame(dup_counts).sort_values("duplicate_count", ascending=False)

    def unmatched_ids(self) -> dict:
        if self.registration is None:
            return {"scan_only": set(), "registration_only": set()}
        return {
            "scan_only": set(self.records[COL_ID].unique()) - set(self.registration[COL_ID].unique()),
            "registration_only": set(self.registration[COL_ID].unique()) - set(self.records[COL_ID].unique()),
        }

    def search(self, query: str) -> pd.DataFrame:
        q = query.strip().lower()
        if not q or self.records.empty:
            return pd.DataFrame()
        mask = (
            self.records[COL_ID].str.lower().str.contains(q, na=False)
            | self.records[COL_TIMESTAMP].astype(str).str.lower().str.contains(q, na=False)
            | self.records[COL_SESSION].str.lower().str.contains(q, na=False)
            | self.records[COL_IP].astype(str).str.contains(q, na=False)
        )
        results = self.records[mask].copy()
        if self.registration is not None and COL_NAME in self.registration.columns:
            name_hits = self.registration[
                self.registration[COL_NAME].str.lower().str.contains(q, na=False)
            ][COL_ID].unique()
            results = pd.concat([results, self.records[self.records[COL_ID].isin(name_hits)]]).drop_duplicates()
        return results.sort_values([COL_ID, COL_TIMESTAMP])

    # ── Demographic Analytics ─────────────────────────────────────────────
    def year_distribution(self) -> pd.Series:
        """Year of studies distribution for scanned participants."""
        if self.registration is None or COL_YEAR not in self.registration.columns:
            return pd.Series(dtype=int)
        scanned_ids = set(self.records[COL_ID].unique()) if not self.records.empty else set()
        if not scanned_ids:
            return pd.Series(dtype=int)
        reg = self.registration[self.registration[COL_ID].isin(scanned_ids)]
        years = reg[COL_YEAR].dropna().astype(str).str.strip()
        years = years[years != ""]
        return years.value_counts().sort_index()

    def university_distribution(self) -> pd.Series:
        """University/institution distribution for scanned participants."""
        if self.registration is None or COL_UNIVERSITY not in self.registration.columns:
            return pd.Series(dtype=int)
        scanned_ids = set(self.records[COL_ID].unique()) if not self.records.empty else set()
        if not scanned_ids:
            return pd.Series(dtype=int)
        reg = self.registration[self.registration[COL_ID].isin(scanned_ids)]
        unis = reg[COL_UNIVERSITY].dropna().astype(str).str.strip()
        unis = unis[unis != ""]
        return unis.value_counts()

    def device_distribution(self) -> pd.Series:
        """Device type distribution from scan user agents."""
        if self.records.empty or COL_UA not in self.records.columns:
            return pd.Series(dtype=int)
        return self.records[COL_UA].apply(parse_device_type).value_counts()

    def source_url_summary(self) -> pd.Series:
        """Which scanning forms were used (from source_url)."""
        if self.records.empty or COL_SOURCE_URL not in self.records.columns:
            return pd.Series(dtype=int)
        urls = self.records[COL_SOURCE_URL].dropna().astype(str).str.strip()
        urls = urls[urls != ""]
        return urls.value_counts()

    def edited_scans(self) -> pd.DataFrame:
        """Scans where date_updated differs from scan_timestamp."""
        if self.records.empty or COL_DATE_UPDATED not in self.records.columns:
            return pd.DataFrame()
        df = self.records.copy()
        df["ts"] = pd.to_datetime(df[COL_TIMESTAMP], errors="coerce")
        df["updated"] = pd.to_datetime(df[COL_DATE_UPDATED], errors="coerce")
        mask = df["ts"].notna() & df["updated"].notna() & (df["ts"] != df["updated"])
        edited = df[mask].copy()
        if not edited.empty:
            edited["edit_delta_sec"] = (edited["updated"] - edited["ts"]).dt.total_seconds()
        return edited

    def registration_stats(self) -> dict:
        """Summary statistics from registration data."""
        if self.registration is None:
            return {}
        reg = self.registration
        stats = {
            "total_registrants": len(reg),
            "with_email": int(reg[COL_EMAIL].notna().sum()) if COL_EMAIL in reg.columns else 0,
            "with_phone": int((reg[COL_PHONE].notna() & (reg[COL_PHONE].astype(str).str.strip() != "")).sum())
                if COL_PHONE in reg.columns else 0,
        }
        if COL_YEAR in reg.columns:
            stats["years_represented"] = int(reg[COL_YEAR].dropna().nunique())
        if COL_UNIVERSITY in reg.columns:
            stats["universities_represented"] = int(reg[COL_UNIVERSITY].dropna().nunique())
        if "consents" in reg.columns:
            stats["all_consents_given"] = int((reg["consents"].str.count(";") >= 2).sum())
        return stats

    # ── Anomalies (schedule-aware) ────────────────────────────────────────
    def anomalies(self, isolation_min: int = 10, travel_min: int = 5, grace_min: int = 15) -> dict:
        res = {
            "isolated": pd.DataFrame(),
            "impossible_travel": pd.DataFrame(),
            "out_of_window": pd.DataFrame(),
            "ip_summary": pd.DataFrame(),
            "full_log": pd.DataFrame(),
            "timing_stats": pd.DataFrame(),
            "edited_scans": pd.DataFrame(),
        }
        if self.records.empty:
            return res

        recs = self.records.copy()
        recs[COL_IP] = recs[COL_IP].astype(str).str.strip()
        recs["ts"] = pd.to_datetime(recs[COL_TIMESTAMP], errors="coerce")
        valid = recs.dropna(subset=["ts"]).sort_values("ts").reset_index(drop=True)

        # Isolated scans
        if not valid.empty:
            isolated = []
            sorted_ts = valid["ts"].values
            for i in range(len(valid)):
                nearest = float("inf")
                if i > 0:
                    gap = abs((sorted_ts[i] - sorted_ts[i - 1]) / np.timedelta64(1, "m"))
                    nearest = min(nearest, gap)
                if i < len(valid) - 1:
                    gap = abs((sorted_ts[i + 1] - sorted_ts[i]) / np.timedelta64(1, "m"))
                    nearest = min(nearest, gap)
                if nearest >= isolation_min:
                    row = valid.iloc[i]
                    isolated.append({
                        COL_ID: row[COL_ID], "name": self.get_name(row[COL_ID]),
                        COL_SESSION: row[COL_SESSION], COL_TIMESTAMP: row[COL_TIMESTAMP],
                        COL_IP: row[COL_IP],
                        "nearest_min": round(nearest, 1) if nearest != float("inf") else None,
                    })
            res["isolated"] = pd.DataFrame(isolated)

        # Impossible travel
        if not valid.empty:
            travel = []
            for pid, g in valid.groupby(COL_ID):
                if len(g) < 2:
                    continue
                g = g.sort_values("ts")
                for i in range(1, len(g)):
                    if g.iloc[i][COL_SESSION] == g.iloc[i - 1][COL_SESSION]:
                        continue
                    delta = (g.iloc[i]["ts"] - g.iloc[i - 1]["ts"]).total_seconds() / 60
                    if 0 < delta < travel_min:
                        travel.append({
                            COL_ID: pid, "name": self.get_name(pid),
                            "session_1": g.iloc[i - 1][COL_SESSION], "time_1": str(g.iloc[i - 1]["ts"]),
                            "session_2": g.iloc[i][COL_SESSION], "time_2": str(g.iloc[i]["ts"]),
                            "gap_min": round(delta, 1),
                        })
            res["impossible_travel"] = pd.DataFrame(travel)

        # Out-of-window
        if self.schedule and not valid.empty:
            oow = []
            for _, row in valid.iterrows():
                sess = self.schedule.get_session_by_name(row[COL_SESSION])
                if sess and not sess.is_within_window(row["ts"], grace_min):
                    offset = sess.arrival_offset_min(row["ts"])
                    oow.append({
                        COL_ID: row[COL_ID], "name": self.get_name(row[COL_ID]),
                        COL_SESSION: row[COL_SESSION], COL_TIMESTAMP: row[COL_TIMESTAMP],
                        "scheduled_start": sess.start, "scheduled_end": sess.end,
                        "offset_min": round(offset, 1),
                        "status": "EARLY" if offset < 0 else "LATE",
                    })
            res["out_of_window"] = pd.DataFrame(oow)

        # Timing stats
        if self.schedule and not valid.empty:
            tstats = []
            for sess in self.schedule.sessions:
                s_recs = valid[valid[COL_SESSION] == sess.name]
                if s_recs.empty:
                    tstats.append({
                        "session": sess.name, "scheduled": f"{sess.start}–{sess.end}",
                        "attendees": 0, "first_scan": "–", "last_scan": "–",
                        "avg_arrival_offset": "–", "early_pct": "–", "late_pct": "–", "in_window_pct": "–",
                    })
                    continue
                offsets = [sess.arrival_offset_min(t) for t in s_recs["ts"]]
                in_window = sum(1 for _, r in s_recs.iterrows() if sess.is_within_window(r["ts"], grace_min))
                early = sum(1 for o in offsets if o < -grace_min)
                late = sum(1 for o in offsets if o > sess.duration_min + grace_min)
                n = len(s_recs)
                tstats.append({
                    "session": sess.name, "scheduled": f"{sess.start}–{sess.end}",
                    "attendees": s_recs[COL_ID].nunique(),
                    "first_scan": s_recs["ts"].min().strftime("%H:%M:%S"),
                    "last_scan": s_recs["ts"].max().strftime("%H:%M:%S"),
                    "avg_arrival_offset": f"{np.mean(offsets):+.1f} min",
                    "early_pct": f"{early / n * 100:.0f}%",
                    "late_pct": f"{late / n * 100:.0f}%",
                    "in_window_pct": f"{in_window / n * 100:.0f}%",
                })
            res["timing_stats"] = pd.DataFrame(tstats)

        # IP summary
        res["ip_summary"] = (
            recs.groupby([COL_SESSION, COL_IP])
            .agg(scans=(COL_ID, "count"), unique_ids=(COL_ID, "nunique"))
            .reset_index()
            .sort_values([COL_SESSION, "scans"], ascending=[True, False])
        )

        # Full log with extended fields
        log_cols = [COL_ID, COL_TIMESTAMP, COL_SESSION, COL_IP, COL_UA, COL_ENTRY_ID, COL_SOURCE_URL]
        available = [c for c in log_cols if c in recs.columns]
        full = recs[available].copy()
        full.insert(1, "name", full[COL_ID].map(self.get_name))
        res["full_log"] = full.sort_values(COL_TIMESTAMP)

        # Edited scans
        res["edited_scans"] = self.edited_scans()

        return res

    # ── Deep Analytics ────────────────────────────────────────────────────
    def session_correlation_matrix(self) -> pd.DataFrame:
        if self.records.empty:
            return pd.DataFrame()
        cross = pd.crosstab(self.records[COL_ID], self.records[COL_SESSION])
        cross[cross > 0] = 1
        return cross.corr()

    def dropout_analysis(self) -> pd.DataFrame:
        if self.records.empty:
            return pd.DataFrame()
        recs = self.records.copy()
        recs["ts"] = pd.to_datetime(recs[COL_TIMESTAMP], errors="coerce")
        order = recs.groupby(COL_SESSION)["ts"].min().sort_values().index.tolist()
        if len(order) < 2:
            return pd.DataFrame()
        cross = pd.crosstab(recs[COL_ID], recs[COL_SESSION])
        cross[cross > 0] = 1
        cross = cross.reindex(columns=order, fill_value=0)
        results = []
        for pid, row in cross.iterrows():
            attended = [s for s in order if row[s] > 0]
            if not attended:
                continue
            last_idx = order.index(attended[-1])
            missed = order[last_idx + 1:]
            if missed and len(attended) >= 2:
                results.append({
                    COL_ID: pid, "name": self.get_name(pid),
                    "sessions_attended": len(attended), "last_seen": attended[-1],
                    "dropped_after_session": last_idx + 1, "sessions_missed": len(missed),
                })
        return pd.DataFrame(results).sort_values("dropped_after_session") if results else pd.DataFrame()

    def closing_only_attendees(self) -> pd.DataFrame:
        if self.records.empty or len(self.sessions) < 2:
            return pd.DataFrame()
        recs = self.records.copy()
        recs["ts"] = pd.to_datetime(recs[COL_TIMESTAMP], errors="coerce")
        order = recs.groupby(COL_SESSION)["ts"].min().sort_values().index.tolist()
        last = order[-1]
        counts = self.session_count_per_participant()
        singles = counts[counts == 1].index
        lo = self.records[(self.records[COL_ID].isin(singles)) & (self.records[COL_SESSION] == last)]
        if lo.empty:
            return pd.DataFrame()
        r = lo[[COL_ID]].drop_duplicates()
        r["name"] = r[COL_ID].map(self.get_name)
        r["only_session"] = last
        return r

    # ── Participant Report ────────────────────────────────────────────────
    def generate_participant_report_html(self, pid: str, threshold: int) -> str:
        name = self.get_name(pid) or "Unknown"
        email = self.get_email(pid)
        rip = self.get_reg_ip(pid)
        phone = self.get_phone(pid)
        year = self.get_year(pid)
        university = self.get_university(pid)
        scans = self.lookup(pid)

        # Valid attendance count (time-aware deduplication)
        va = self._valid_attendances()
        pid_va = va[va[COL_ID] == pid] if not va.empty else pd.DataFrame()
        ns = len(pid_va)

        # Ceremony-aware eligibility
        ceremony = self.ceremony_status(pid)
        others = sum(1 for s in pid_va[COL_SESSION] if not self._is_ceremony(s)) if not pid_va.empty else 0
        elig = ceremony["opening"] and ceremony["closing"] and others >= threshold
        all_s = self.sessions

        scan_rows = ""
        if scans is not None:
            last_scan_ts: dict[str, datetime] = {}
            for i, (_, r) in enumerate(scans.iterrows(), 1):
                sess = r[COL_SESSION]
                ts_dt = pd.to_datetime(r[COL_TIMESTAMP], errors="coerce")
                dup = ""
                if sess in last_scan_ts and ts_dt is not pd.NaT:
                    if (ts_dt - last_scan_ts[sess]).total_seconds() <= DUPLICATE_GAP_MINUTES * 60:
                        dup = "⚠️ DUP"
                if ts_dt is not pd.NaT:
                    last_scan_ts[sess] = ts_dt
                sched_info = ""
                if self.schedule:
                    ss = self.schedule.get_session_by_name(r[COL_SESSION])
                    if ss:
                        ts = pd.to_datetime(r[COL_TIMESTAMP])
                        if not ss.is_within_window(ts, 15):
                            sched_info = "🕐 OUT OF WINDOW"
                        else:
                            off = ss.arrival_offset_min(ts)
                            sched_info = f"{off:+.0f} min" if abs(off) > 1 else "on time"
                eid = r.get(COL_ENTRY_ID, "")
                eid_str = f" <span style='color:#94a3b8'>[#{eid}]</span>" if eid and str(eid).strip() else ""
                scan_rows += (
                    f"<tr><td>{i}</td><td>{r[COL_SESSION]}{eid_str}</td>"
                    f"<td>{r[COL_TIMESTAMP]}</td><td>{r[COL_IP]}</td>"
                    f"<td>{sched_info}</td><td style='color:#ef4444'>{dup}</td></tr>\n"
                )

        session_dots = ""
        attended = set(scans[COL_SESSION].unique()) if scans is not None else set()
        for s in all_s:
            colour = "#10b981" if s in attended else "#555"
            icon = "●" if s in attended else "○"
            sched_info = ""
            if self.schedule:
                ss = self.schedule.get_session_by_name(s)
                if ss:
                    sched_info = f"  <span style='color:#94a3b8;font-size:12px'>({ss.start}–{ss.end})</span>"
            session_dots += f'<div style="color:{colour};margin:3px 0">{icon}  {s}{sched_info}</div>\n'

        return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>CAMeSM — {name}</title>
<style>*{{margin:0;padding:0;box-sizing:border-box}}body{{font-family:-apple-system,'Helvetica Neue',sans-serif;background:#fff;color:#1a1a2e;padding:40px;max-width:900px;margin:0 auto}}
.header{{display:flex;justify-content:space-between;align-items:flex-start;border-bottom:3px solid #3b82f6;padding-bottom:20px;margin-bottom:24px}}
.header h1{{font-size:28px}}.header .meta{{text-align:right;font-size:13px;color:#666}}
.badge{{display:inline-block;padding:6px 16px;border-radius:20px;font-weight:700;font-size:14px}}
.badge.ok{{background:#d1fae5;color:#065f46}}.badge.no{{background:#fef3c7;color:#92400e}}
.grid{{display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-bottom:24px}}
.card{{background:#f8fafc;padding:14px;border-radius:8px;border:1px solid #e2e8f0}}
.card .l{{font-size:11px;text-transform:uppercase;color:#94a3b8;letter-spacing:.5px}}.card .v{{font-size:16px;font-weight:600;margin-top:4px}}
h2{{font-size:18px;margin:24px 0 12px;color:#1e293b}}
table{{width:100%;border-collapse:collapse;font-size:13px}}th{{background:#f1f5f9;text-align:left;padding:8px 12px;font-weight:600;border-bottom:2px solid #e2e8f0}}
td{{padding:8px 12px;border-bottom:1px solid #f1f5f9}}.sessions{{margin-top:12px;font-size:15px;line-height:1.6}}
.footer{{margin-top:40px;padding-top:16px;border-top:1px solid #e2e8f0;font-size:11px;color:#94a3b8;text-align:center}}
@media print{{body{{padding:20px}}}}</style></head><body>
<div class="header"><div><h1>🩺 CAMeSM Participant Report</h1><p style="color:#64748b;margin-top:4px">Cyprus Annual Medical Students Meeting — Attendance Record</p></div>
<div class="meta">Generated: {datetime.now():%d %B %Y, %H:%M}<br>Threshold: {threshold} sessions</div></div>
<div class="grid"><div class="card"><div class="l">Participant ID</div><div class="v">{pid}</div></div>
<div class="card"><div class="l">Full Name</div><div class="v">{name}</div></div>
<div class="card"><div class="l">Email</div><div class="v">{email or 'N/A'}</div></div>
<div class="card"><div class="l">Phone</div><div class="v">{phone or 'N/A'}</div></div>
<div class="card"><div class="l">Year of Studies</div><div class="v">{year or 'N/A'}</div></div>
<div class="card"><div class="l">University</div><div class="v">{university or 'N/A'}</div></div>
<div class="card"><div class="l">Registration IP</div><div class="v">{rip or 'N/A'}</div></div></div>
<div style="text-align:center;margin:20px 0"><span class="badge {'ok' if elig else 'no'}">
{'✅ ELIGIBLE' if elig else '⏳ NOT YET ELIGIBLE'}</span>
<div style="margin-top:8px;color:#64748b;font-size:14px">{'✅' if ceremony['opening'] else '❌'} Opening  •  {'✅' if ceremony['closing'] else '❌'} Closing  •  {others}/{threshold} others  •  {ns} attendance(s)  •  {len(scans) if scans is not None else 0} scan(s)</div></div>
<h2>Session Attendance</h2><div class="sessions">{session_dots}</div>
<h2>Scan History</h2><table><tr><th>#</th><th>Session</th><th>Timestamp</th><th>IP</th><th>Timing</th><th>Flags</th></tr>
{scan_rows or '<tr><td colspan="6" style="text-align:center;color:#94a3b8">No scans</td></tr>'}</table>
<div class="footer">CAMeSM Attendance Tracker v{APP_VERSION} — European University Cyprus</div></body></html>"""

    # ── Exports ───────────────────────────────────────────────────────────
    def export_eligibility_csv(self, filepath: str, threshold: int) -> int:
        elig = self.eligible_participants(threshold)
        elig["status"] = "ELIGIBLE"
        inelig = self.ineligible_participants(threshold)
        inelig["status"] = "NOT YET ELIGIBLE"
        combined = pd.concat([elig, inelig], ignore_index=True)
        if self.registration is not None:
            extra = [c for c in [COL_PHONE, COL_YEAR, COL_UNIVERSITY] if c in self.registration.columns]
            if extra:
                combined = combined.merge(self.registration[[COL_ID] + extra], on=COL_ID, how="left")
        combined.to_csv(filepath, index=False)
        self._log("EXPORT", filepath)
        return len(combined)

    def export_attendance_by_session(self, filepath: str) -> int:
        if self.records.empty:
            return 0
        cross = pd.crosstab(self.records[COL_ID], self.records[COL_SESSION])
        cross[cross > 0] = 1
        cross["total_sessions"] = cross.sum(axis=1)
        cross = cross.sort_values("total_sessions", ascending=False)
        if self.registration is not None:
            insert_pos = 0
            for col in [COL_NAME, COL_YEAR, COL_UNIVERSITY]:
                if col in self.registration.columns:
                    nm = self.registration.set_index(COL_ID)[col].to_dict()
                    cross.insert(insert_pos, col, cross.index.map(lambda x, nm=nm: nm.get(x, "")))
                    insert_pos += 1
        cross.to_csv(filepath)
        self._log("EXPORT", filepath)
        return len(cross)

    def export_audit_log(self, filepath: str) -> int:
        pd.DataFrame(self.audit_log).to_csv(filepath, index=False)
        return len(self.audit_log)
