"""Local state persistence using SQLite in the synced Nudge state directory."""

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from nudge.sleep_reminders import (
    SLEEP_AFTER_SKIP_STATUS,
    SLEEP_AUTO_SKIP_LOOKAHEAD_HOURS,
    later_sleep_reminders_after,
)
from nudge.config import load_config, resolve_state_dir


logger = logging.getLogger(__name__)
_LEGACY_JSON_MIGRATION_NAME = "legacy_state_json"


def _default_state_dir(config: dict | None = None) -> Path:
    if config is None:
        try:
            config = load_config()
        except FileNotFoundError:
            config = {}
    return resolve_state_dir(config)


STATE_DIR = _default_state_dir()
DB_PATH = STATE_DIR / "nudge.db"
LEGACY_JSON = STATE_DIR / "state.json"
_schema_initialized_for: Path | None = None
_QUEUE_STATUS = {"queued", "running", "succeeded", "failed", "dead_letter"}
DEFAULT_COMMAND_QUEUE_MAX_DEPTH = 1000
DEFAULT_AGENT_REQUEST_STALE_MINUTES = 30
_HEALTH_DAILY_MAX_FIELDS = {
    "steps",
    "distance_walking_running_m",
    "active_energy_kcal",
    "basal_energy_kcal",
    "exercise_minutes",
    "stand_minutes",
    "sleep_asleep_minutes",
    "sleep_in_bed_minutes",
}
_HEALTH_DAILY_LATEST_FIELDS = {"body_weight_kg"}
_HEALTH_DAILY_FILL_FIELDS = {
    "resting_heart_rate",
    "avg_heart_rate",
    "hrv_sdnn_avg",
    "walking_heart_rate_avg",
    "body_fat_percent",
    "vo2max",
}


def configure_state(config: dict | None = None) -> Path:
    """Re-resolve process state paths from an already-loaded config.

    Most commands use the default config and can rely on import-time paths.
    Commands that accept ``--config`` must call this after ``load_config`` so
    SQLite state follows that config's ``[state].dir`` instead of the default
    project state directory.
    """
    global STATE_DIR, DB_PATH, LEGACY_JSON, _migrated, _schema_initialized_for

    STATE_DIR = _default_state_dir(config)
    DB_PATH = STATE_DIR / "nudge.db"
    LEGACY_JSON = STATE_DIR / "state.json"
    _migrated = False
    _schema_initialized_for = None
    return STATE_DIR


def _ensure_dir():
    STATE_DIR.mkdir(parents=True, exist_ok=True)


def _connect_raw() -> sqlite3.Connection:
    """Open a database connection without migration or schema setup."""
    _ensure_dir()
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """Initialize schema once per process for the current database path."""
    global _schema_initialized_for

    db_path = DB_PATH.resolve()
    if _schema_initialized_for == db_path:
        return
    _init_tables(conn)
    _schema_initialized_for = db_path


def _get_conn() -> sqlite3.Connection:
    """Get a raw database connection, creating tables if needed."""
    _ensure_dir()
    _ensure_migrated()
    conn = _connect_raw()
    try:
        _ensure_schema(conn)
    except Exception:
        conn.close()
        raise
    return conn


@contextmanager
def _db():
    """Context manager for database connections — auto-closes on exit."""
    conn = _get_conn()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _init_tables(conn: sqlite3.Connection):
    """Create tables if they don't exist."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS plans (
            id          TEXT PRIMARY KEY,
            goal        TEXT NOT NULL,
            status      TEXT DEFAULT 'active',
            config      TEXT,
            created_at  TEXT DEFAULT (datetime('now', 'localtime'))
        );

        CREATE TABLE IF NOT EXISTS actions (
            id              TEXT PRIMARY KEY,
            plan_id         TEXT REFERENCES plans(id),
            type            TEXT NOT NULL,
            summary         TEXT NOT NULL,
            scheduled_at    TEXT,
            completed_at    TEXT,
            status          TEXT DEFAULT 'pending',
            external_id     TEXT,
            feedback        TEXT,
            created_at      TEXT DEFAULT (datetime('now', 'localtime'))
        );

        CREATE INDEX IF NOT EXISTS idx_actions_status
            ON actions(status);

        CREATE INDEX IF NOT EXISTS idx_actions_plan_id
            ON actions(plan_id);

        CREATE INDEX IF NOT EXISTS idx_actions_scheduled_at
            ON actions(scheduled_at);

        CREATE INDEX IF NOT EXISTS idx_actions_completed_at
            ON actions(completed_at);

        CREATE INDEX IF NOT EXISTS idx_actions_created_at
            ON actions(created_at);

        CREATE TABLE IF NOT EXISTS habit_logs (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            habit_name  TEXT NOT NULL,
            date        TEXT NOT NULL,
            completed   INTEGER DEFAULT 1,
            notes       TEXT,
            streak      INTEGER DEFAULT 0,
            UNIQUE(habit_name, date)
        );

        CREATE TABLE IF NOT EXISTS evaluations (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_id         TEXT REFERENCES plans(id),
            period          TEXT NOT NULL,
            period_start    TEXT NOT NULL,
            period_end      TEXT NOT NULL,
            metrics         TEXT,
            insights        TEXT,
            adaptations     TEXT,
            created_at      TEXT DEFAULT (datetime('now', 'localtime'))
        );

        CREATE TABLE IF NOT EXISTS chat_history (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            role        TEXT NOT NULL,
            content     TEXT NOT NULL,
            created_at  TEXT DEFAULT (datetime('now', 'localtime'))
        );

        CREATE TABLE IF NOT EXISTS health_imports (
            source_hash     TEXT PRIMARY KEY,
            source_path     TEXT NOT NULL,
            export_xml_name TEXT,
            date_start      TEXT,
            date_end        TEXT,
            daily_count     INTEGER DEFAULT 0,
            workout_count   INTEGER DEFAULT 0,
            imported_at     TEXT DEFAULT (datetime('now', 'localtime'))
        );

        CREATE TABLE IF NOT EXISTS health_daily_summary (
            date                        TEXT PRIMARY KEY,
            steps                       REAL,
            distance_walking_running_m  REAL,
            active_energy_kcal          REAL,
            basal_energy_kcal           REAL,
            exercise_minutes            REAL,
            stand_minutes               REAL,
            sleep_asleep_minutes        REAL,
            sleep_in_bed_minutes        REAL,
            resting_heart_rate          REAL,
            avg_heart_rate              REAL,
            hrv_sdnn_avg                REAL,
            walking_heart_rate_avg      REAL,
            body_weight_kg              REAL,
            body_fat_percent            REAL,
            vo2max                      REAL,
            source_counts               TEXT,
            updated_at                  TEXT DEFAULT (datetime('now', 'localtime'))
        );

        CREATE TABLE IF NOT EXISTS health_workouts (
            external_id         TEXT PRIMARY KEY,
            source_name         TEXT,
            workout_type        TEXT,
            start_at            TEXT NOT NULL,
            end_at              TEXT,
            duration_minutes    REAL,
            active_energy_kcal  REAL,
            distance_m          REAL,
            updated_at          TEXT DEFAULT (datetime('now', 'localtime'))
        );

        CREATE TABLE IF NOT EXISTS command_queue (
            request_id      TEXT PRIMARY KEY,
            source          TEXT,
            request_type    TEXT NOT NULL,
            payload         TEXT NOT NULL,
            status          TEXT NOT NULL DEFAULT 'queued',
            attempts        INTEGER DEFAULT 0,
            queue_created_at TEXT DEFAULT (datetime('now', 'localtime')),
            started_at      TEXT,
            finished_at     TEXT,
            last_error      TEXT,
            last_exit_code  INTEGER,
            last_duration_ms INTEGER,
            command_id      TEXT,
            last_payload_size INTEGER
        );

        CREATE INDEX IF NOT EXISTS idx_command_queue_status_created
            ON command_queue (status, queue_created_at);

        CREATE TABLE IF NOT EXISTS daemon_runs (
            run_id         TEXT PRIMARY KEY,
            request_id     TEXT NOT NULL,
            command_id     TEXT NOT NULL,
            request_type   TEXT NOT NULL,
            status         TEXT NOT NULL,
            started_at     TEXT NOT NULL,
            finished_at    TEXT NOT NULL,
            queue_wait_ms  INTEGER DEFAULT 0,
            processing_ms  INTEGER DEFAULT 0,
            total_ms       INTEGER DEFAULT 0,
            payload_size   INTEGER DEFAULT 0,
            error_text     TEXT,
            output_json    TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_daemon_runs_request
            ON daemon_runs (request_id, finished_at);

        CREATE TABLE IF NOT EXISTS agent_request_runs (
            request_id      TEXT PRIMARY KEY,
            payload_hash    TEXT NOT NULL,
            status          TEXT NOT NULL,
            response_json   TEXT,
            exit_code       INTEGER,
            created_at      TEXT DEFAULT (datetime('now', 'localtime')),
            finished_at     TEXT
        );

        CREATE TABLE IF NOT EXISTS state_migrations (
            name        TEXT PRIMARY KEY,
            status      TEXT NOT NULL,
            last_error  TEXT,
            updated_at  TEXT DEFAULT (datetime('now', 'localtime'))
        );
    """)
    conn.commit()


# ── Migration from state.json ──────────────────────────────────


def _migrate_from_json():
    """One-time migration: import data from legacy state.json into SQLite."""
    if not LEGACY_JSON.exists():
        return

    conn = _connect_raw()
    migrated = False
    try:
        _ensure_schema(conn)

        pending = conn.execute(
            "SELECT status FROM state_migrations WHERE name = ?",
            (_LEGACY_JSON_MIGRATION_NAME,),
        ).fetchone()
        if pending:
            if pending["status"] == "archive_pending":
                _archive_legacy_json(conn)
            return

        # Check if already migrated
        count = conn.execute("SELECT COUNT(*) FROM habit_logs").fetchone()[0]
        if count > 0:
            logger.warning(
                "Skipping legacy state JSON migration because SQLite habit_logs already contains data; "
                "leaving %s in place",
                LEGACY_JSON,
            )
            return

        try:
            with open(LEGACY_JSON) as f:
                data = json.load(f)
        except (json.JSONDecodeError, ValueError):
            return

        with conn:
            habits = data.get("habits", {})
            for name, info in habits.items():
                last_logged = info.get("last_logged")
                streak = info.get("streak", 0)
                if last_logged:
                    conn.execute(
                        "INSERT OR IGNORE INTO habit_logs (habit_name, date, completed, streak) VALUES (?, ?, 1, ?)",
                        (name, last_logged, streak),
                    )
            conn.execute(
                """
                INSERT INTO state_migrations (name, status, last_error, updated_at)
                VALUES (?, 'archive_pending', NULL, datetime('now', 'localtime'))
                ON CONFLICT(name) DO UPDATE SET
                    status = excluded.status,
                    last_error = excluded.last_error,
                    updated_at = excluded.updated_at
                """,
                (_LEGACY_JSON_MIGRATION_NAME,),
            )
        migrated = True
    finally:
        conn.close()

    # Rename old file so we don't migrate again
    if migrated:
        archive_conn = _connect_raw()
        try:
            _ensure_schema(archive_conn)
            _archive_legacy_json(archive_conn)
        finally:
            archive_conn.close()


def _archive_legacy_json(conn: sqlite3.Connection) -> bool:
    """Archive legacy state.json after committed SQLite migration, retrying on later runs."""
    if not LEGACY_JSON.exists():
        with conn:
            conn.execute(
                """
                UPDATE state_migrations
                SET status = 'archived', last_error = NULL, updated_at = datetime('now', 'localtime')
                WHERE name = ?
                """,
                (_LEGACY_JSON_MIGRATION_NAME,),
            )
        return True

    try:
        LEGACY_JSON.rename(LEGACY_JSON.with_suffix(".json.bak"))
    except OSError as exc:
        with conn:
            conn.execute(
                """
                UPDATE state_migrations
                SET status = 'archive_pending', last_error = ?, updated_at = datetime('now', 'localtime')
                WHERE name = ?
                """,
                (str(exc), _LEGACY_JSON_MIGRATION_NAME),
            )
        logger.warning(
            "Failed to archive legacy state JSON after migration; will retry on next state initialization: %s",
            exc,
        )
        return False

    with conn:
        conn.execute(
            """
            UPDATE state_migrations
            SET status = 'archived', last_error = NULL, updated_at = datetime('now', 'localtime')
            WHERE name = ?
            """,
            (_LEGACY_JSON_MIGRATION_NAME,),
        )
    return True


# ── Habit tracking ──────────────────────────────────────────────


def update_habit(habit_name: str, completed: bool = True, notes: str | None = None):
    """Log a habit completion for today."""
    with _db() as conn:
        today = date.today().isoformat()

        existing = conn.execute(
            "SELECT id FROM habit_logs WHERE habit_name = ? AND date = ?",
            (habit_name, today),
        ).fetchone()
        if existing:
            return

        streak = 0
        if completed:
            yesterday = (date.today() - timedelta(days=1)).isoformat()
            prev = conn.execute(
                "SELECT streak FROM habit_logs WHERE habit_name = ? AND date = ? AND completed = 1",
                (habit_name, yesterday),
            ).fetchone()
            streak = (prev["streak"] + 1) if prev else 1

        conn.execute(
            "INSERT INTO habit_logs (habit_name, date, completed, notes, streak) VALUES (?, ?, ?, ?, ?)",
            (habit_name, today, int(completed), notes, streak),
        )


def get_habit_streaks() -> dict[str, dict]:
    """Get current streak for all tracked habits."""
    with _db() as conn:
        rows = conn.execute("""
            SELECT habit_name, date, streak
            FROM habit_logs
            WHERE (habit_name, date) IN (
                SELECT habit_name, MAX(date) FROM habit_logs GROUP BY habit_name
            )
        """).fetchall()

    result = {}
    for row in rows:
        result[row["habit_name"]] = {
            "streak": row["streak"],
            "last_logged": row["date"],
        }
    return result


# ── Action logging ──────────────────────────────────────────────


def log_action(
    action_type: str,
    summary: str,
    scheduled_at: str | None = None,
    external_id: str | None = None,
    plan_id: str | None = None,
    status: str = "created",
) -> str:
    """Log an action. Returns the action id."""
    action_id = uuid4().hex[:12]
    with _db() as conn:
        conn.execute(
            "INSERT INTO actions (id, plan_id, type, summary, scheduled_at, external_id, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (action_id, plan_id, action_type, summary, scheduled_at, external_id, status),
        )
    return action_id


def complete_action(
    action_id: str,
    feedback: dict | None = None,
    completed_at: str | None = None,
) -> list[dict]:
    """Mark an action as completed and return any auto-skipped sleep reminders."""
    has_explicit_completed_at = completed_at is not None
    now = completed_at or datetime.now().strftime("%Y-%m-%d %H:%M")
    feedback_json = json.dumps(feedback, ensure_ascii=False) if feedback else None
    with _db() as conn:
        conn.execute(
            "UPDATE actions SET status = 'done', completed_at = ?, feedback = ? WHERE id = ?",
            (now, feedback_json, action_id),
        )
    return skip_later_sleep_reminders_after_completion(
        action_id,
        prefer_completed_at=has_explicit_completed_at,
    )


def skip_later_sleep_reminders_after_completion(
    action_id: str,
    *,
    prefer_completed_at: bool = True,
) -> list[dict]:
    """Auto-skip later same-day sleep reminders after bedtime is completed."""
    completed = get_action(action_id)
    if not completed:
        return []
    if not prefer_completed_at:
        completed = dict(completed)
        completed["completed_at"] = None
    scheduled_at = str(completed.get("scheduled_at") or "")
    if len(scheduled_at) < 10:
        return []
    try:
        scheduled_time = datetime.strptime(scheduled_at[:16], "%Y-%m-%d %H:%M")
    except ValueError:
        return []
    action_time_text = str(completed.get("completed_at") or completed.get("scheduled_at") or "").strip()
    try:
        action_time = datetime.strptime(action_time_text[:16], "%Y-%m-%d %H:%M")
    except ValueError:
        action_time = scheduled_time

    start_time = min(scheduled_time, action_time).replace(hour=0, minute=0)
    end_time = max(
        scheduled_time.replace(hour=0, minute=0) + timedelta(days=1),
        action_time + timedelta(hours=SLEEP_AUTO_SKIP_LOOKAHEAD_HOURS),
    )
    start = start_time.strftime("%Y-%m-%d %H:%M")
    end = end_time.strftime("%Y-%m-%d %H:%M")
    actions = get_actions(since=start, until=end)
    later = later_sleep_reminders_after(completed, actions)
    for action in later:
        update_action_status(
            action["id"],
            SLEEP_AFTER_SKIP_STATUS,
            feedback={
                "source": "nudge sleep auto-skip",
                "note": "已完成睡觉目标，后续睡眠提醒自动跳过，不计失败。",
                "completed_sleep_action_id": action_id,
                "completed_sleep_action_summary": completed.get("summary"),
            },
        )
    return later


def skip_action(action_id: str, feedback: dict | None = None):
    """Mark an action as skipped."""
    feedback_json = json.dumps(feedback, ensure_ascii=False) if feedback else None
    with _db() as conn:
        conn.execute(
            "UPDATE actions SET status = 'skipped', feedback = ? WHERE id = ?",
            (feedback_json, action_id),
        )


def partial_action(
    action_id: str,
    feedback: dict | None = None,
    completed_at: str | None = None,
):
    """Mark an action as partially completed."""
    now = completed_at or datetime.now().strftime("%Y-%m-%d %H:%M")
    feedback_json = json.dumps(feedback, ensure_ascii=False) if feedback else None
    with _db() as conn:
        conn.execute(
            "UPDATE actions SET status = 'partial', completed_at = ?, feedback = ? WHERE id = ?",
            (now, feedback_json, action_id),
        )


def update_action_status(action_id: str, status: str, feedback: dict | None = None):
    """Update an action status while preserving feedback history context."""
    feedback_json = json.dumps(feedback, ensure_ascii=False) if feedback else None
    with _db() as conn:
        conn.execute(
            "UPDATE actions SET status = ?, feedback = ? WHERE id = ?",
            (status, feedback_json, action_id),
        )


def update_action_external_id(action_id: str, external_id: str) -> None:
    """Attach a stable backend external id to an existing action."""
    with _db() as conn:
        conn.execute(
            "UPDATE actions SET external_id = ? WHERE id = ?",
            (external_id, action_id),
        )


def get_actions(
    status: str | None = None,
    since: str | None = None,
    until: str | None = None,
    plan_id: str | None = None,
) -> list[dict]:
    """Query actions with optional filters.

    `since`/`until` select actions by scheduled time, completion time, or
    creation time for unscheduled items. This keeps period reports aligned with
    when an action actually belongs, not merely when it was created.
    """
    with _db() as conn:
        query = "SELECT * FROM actions WHERE 1=1"
        params = []

        if status:
            query += " AND status = ?"
            params.append(status)
        if since and until:
            query += (
                " AND ("
                "(scheduled_at IS NOT NULL AND scheduled_at >= ? AND scheduled_at < ?) "
                "OR (completed_at IS NOT NULL AND completed_at >= ? AND completed_at < ?) "
                "OR (scheduled_at IS NULL AND completed_at IS NULL AND created_at >= ? AND created_at < ?)"
                ")"
            )
            params.extend([since, until, since, until, since, until])
        elif since:
            query += (
                " AND ("
                "(scheduled_at IS NOT NULL AND scheduled_at >= ?) "
                "OR (completed_at IS NOT NULL AND completed_at >= ?) "
                "OR (scheduled_at IS NULL AND completed_at IS NULL AND created_at >= ?)"
                ")"
            )
            params.extend([since, since, since])
        elif until:
            query += (
                " AND ("
                "(scheduled_at IS NOT NULL AND scheduled_at < ?) "
                "OR (completed_at IS NOT NULL AND completed_at < ?) "
                "OR (scheduled_at IS NULL AND completed_at IS NULL AND created_at < ?)"
                ")"
            )
            params.extend([until, until, until])
        if plan_id:
            query += " AND plan_id = ?"
            params.append(plan_id)

        query += " ORDER BY created_at DESC"
        rows = conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def get_action(action_id: str) -> dict | None:
    """Return one action by id."""
    if not action_id:
        return None
    with _db() as conn:
        row = conn.execute("SELECT * FROM actions WHERE id = ?", (action_id,)).fetchone()
    return dict(row) if row else None


# ── Plan management ─────────────────────────────────────────────


def create_plan(goal: str, config: dict | None = None) -> str:
    """Create a new plan. Returns plan id."""
    plan_id = uuid4().hex[:12]
    config_json = json.dumps(config, ensure_ascii=False) if config else None
    with _db() as conn:
        conn.execute(
            "INSERT INTO plans (id, goal, config) VALUES (?, ?, ?)",
            (plan_id, goal, config_json),
        )
    return plan_id


def get_plans(status: str = "active") -> list[dict]:
    """Get plans by status."""
    with _db() as conn:
        rows = conn.execute(
            "SELECT * FROM plans WHERE status = ? ORDER BY created_at DESC", (status,)
        ).fetchall()
    return [dict(row) for row in rows]


def get_plan(plan_id: str) -> dict | None:
    """Return one plan by id."""
    if not plan_id:
        return None
    with _db() as conn:
        row = conn.execute("SELECT * FROM plans WHERE id = ?", (plan_id,)).fetchone()
    return dict(row) if row else None


def update_plan_config(plan_id: str, config: dict) -> None:
    """Replace a plan's config JSON."""
    config_json = json.dumps(config, ensure_ascii=False)
    with _db() as conn:
        conn.execute("UPDATE plans SET config = ? WHERE id = ?", (config_json, plan_id))


def update_plan_status(plan_id: str, status: str) -> None:
    """Update a plan status so inactive/failed plans leave active queries."""
    with _db() as conn:
        conn.execute("UPDATE plans SET status = ? WHERE id = ?", (status, plan_id))


# ── Health summaries ────────────────────────────────────────────


def save_health_import(
    *,
    source_path: str,
    source_hash: str,
    export_xml_name: str,
    date_start: str | None,
    date_end: str | None,
    daily_summaries: list[dict],
    workouts: list[dict],
) -> dict:
    """Persist parsed health summaries and workout metadata.

    Raw samples and route points are intentionally not stored here. The import
    is idempotent by date for daily summaries and by deterministic workout
    external_id for workouts.
    """
    with _db() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO health_imports
                (source_hash, source_path, export_xml_name, date_start, date_end, daily_count, workout_count, imported_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now', 'localtime'))
            """,
            (
                source_hash,
                source_path,
                export_xml_name,
                date_start,
                date_end,
                len(daily_summaries),
                len(workouts),
            ),
        )
        for summary in daily_summaries:
            existing = conn.execute(
                "SELECT * FROM health_daily_summary WHERE date = ?",
                (summary.get("date"),),
            ).fetchone()
            merged_summary = _merge_health_daily_summary(existing, summary) if existing else summary
            conn.execute(
                """
                INSERT OR REPLACE INTO health_daily_summary
                    (date, steps, distance_walking_running_m, active_energy_kcal, basal_energy_kcal,
                     exercise_minutes, stand_minutes, sleep_asleep_minutes, sleep_in_bed_minutes,
                     resting_heart_rate, avg_heart_rate, hrv_sdnn_avg, walking_heart_rate_avg,
                     body_weight_kg, body_fat_percent, vo2max, source_counts, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now', 'localtime'))
                """,
                (
                    merged_summary.get("date"),
                    merged_summary.get("steps"),
                    merged_summary.get("distance_walking_running_m"),
                    merged_summary.get("active_energy_kcal"),
                    merged_summary.get("basal_energy_kcal"),
                    merged_summary.get("exercise_minutes"),
                    merged_summary.get("stand_minutes"),
                    merged_summary.get("sleep_asleep_minutes"),
                    merged_summary.get("sleep_in_bed_minutes"),
                    merged_summary.get("resting_heart_rate"),
                    merged_summary.get("avg_heart_rate"),
                    merged_summary.get("hrv_sdnn_avg"),
                    merged_summary.get("walking_heart_rate_avg"),
                    merged_summary.get("body_weight_kg"),
                    merged_summary.get("body_fat_percent"),
                    merged_summary.get("vo2max"),
                    json.dumps(merged_summary.get("source_counts") or {}, ensure_ascii=False, sort_keys=True),
                ),
            )
        for workout in workouts:
            conn.execute(
                """
                INSERT OR REPLACE INTO health_workouts
                    (external_id, source_name, workout_type, start_at, end_at, duration_minutes,
                     active_energy_kcal, distance_m, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now', 'localtime'))
                """,
                (
                    workout.get("external_id"),
                    workout.get("source_name"),
                    workout.get("workout_type"),
                    workout.get("start_at"),
                    workout.get("end_at"),
                    workout.get("duration_minutes"),
                    workout.get("active_energy_kcal"),
                    workout.get("distance_m"),
                ),
            )
    return {"daily_upserted": len(daily_summaries), "workouts_upserted": len(workouts)}


def _merge_health_daily_summary(existing_row: sqlite3.Row, incoming: dict) -> dict:
    """Merge same-day daily summaries from multiple health export sources.

    HealthExport JSON files can be incremental and sparse. A later same-day
    import with no weight sample must not erase weight imported from an earlier
    Apple export or another app. For cumulative fields, keep the larger daily
    value to avoid downgrading a fuller summary with a sparse increment. For
    point-in-time weight, prefer a new non-null value.
    """
    existing = dict(existing_row)
    merged = {"date": incoming.get("date") or existing.get("date")}

    for field in _HEALTH_DAILY_MAX_FIELDS:
        merged[field] = _max_non_null(existing.get(field), incoming.get(field))

    for field in _HEALTH_DAILY_LATEST_FIELDS:
        merged[field] = incoming.get(field) if incoming.get(field) is not None else existing.get(field)

    for field in _HEALTH_DAILY_FILL_FIELDS:
        merged[field] = existing.get(field) if existing.get(field) is not None else incoming.get(field)

    merged["source_counts"] = _merge_source_counts(existing.get("source_counts"), incoming.get("source_counts"))
    return merged


def _max_non_null(left: object, right: object) -> object:
    if left is None:
        return right
    if right is None:
        return left
    return max(left, right)


def _merge_source_counts(existing_value: object, incoming_value: object) -> dict:
    if isinstance(existing_value, str):
        try:
            existing = json.loads(existing_value or "{}")
        except json.JSONDecodeError:
            existing = {}
    elif isinstance(existing_value, dict):
        existing = existing_value
    else:
        existing = {}

    incoming = incoming_value if isinstance(incoming_value, dict) else {}
    merged = dict(existing)
    for source, count in incoming.items():
        merged[source] = max(int(merged.get(source, 0) or 0), int(count or 0))
    return dict(sorted(merged.items()))


def get_health_daily_summaries(since: str | None = None, until: str | None = None) -> list[dict]:
    """Return health daily summaries in [since, until)."""
    with _db() as conn:
        query = "SELECT * FROM health_daily_summary WHERE 1=1"
        params = []
        if since:
            query += " AND date >= ?"
            params.append(since)
        if until:
            query += " AND date < ?"
            params.append(until)
        query += " ORDER BY date ASC"
        rows = conn.execute(query, params).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        try:
            item["source_counts"] = json.loads(item.get("source_counts") or "{}")
        except json.JSONDecodeError:
            item["source_counts"] = {}
        result.append(item)
    return result


def get_health_workouts(since: str | None = None, until: str | None = None) -> list[dict]:
    """Return workout metadata in [since, until)."""
    with _db() as conn:
        query = "SELECT * FROM health_workouts WHERE 1=1"
        params = []
        if since:
            query += " AND start_at >= ?"
            params.append(since)
        if until:
            query += " AND start_at < ?"
            params.append(until)
        query += " ORDER BY start_at ASC"
        rows = conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]


# ── Queue / daemon runtime persistence ──────────────────────────


def enqueue_agent_command(
    *,
    payload: dict,
    request_type: str = "agent.apply",
    source: str | None = None,
    request_id: str | None = None,
    max_queue_depth: int | None = DEFAULT_COMMAND_QUEUE_MAX_DEPTH,
) -> str:
    """Enqueue one structured command for daemon execution."""
    resolved_id = (request_id or uuid4().hex[:12]).strip()
    if not resolved_id:
        resolved_id = uuid4().hex[:12]
    payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    with _db() as conn:
        if max_queue_depth is not None and max_queue_depth > 0:
            active_count = conn.execute(
                """
                SELECT COUNT(*) FROM command_queue
                WHERE status IN ('queued', 'running')
                """
            ).fetchone()[0]
            if active_count >= max_queue_depth:
                raise ValueError(
                    "command queue is full: "
                    f"active_depth={active_count}, max_queue_depth={max_queue_depth}"
                )
        conn.execute(
            """
            INSERT INTO command_queue (
                request_id,
                source,
                request_type,
                payload,
                status,
                last_payload_size
            ) VALUES (?, ?, ?, ?, 'queued', ?)
            """,
            (resolved_id, source, request_type, payload_json, len(payload_json)),
        )
    return resolved_id


def _parse_json_payload(payload_text: str, request_id: str | None = None) -> dict:
    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid payload json: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"request payload must be object, request_id={request_id}")
    return payload


def claim_agent_request_run(
    request_id: str,
    payload_hash: str,
    *,
    stale_minutes: int = DEFAULT_AGENT_REQUEST_STALE_MINUTES,
) -> dict:
    """Reserve a non-dry-run agent request id before external side effects."""
    with _db() as conn:
        try:
            conn.execute(
                """
                INSERT INTO agent_request_runs (request_id, payload_hash, status)
                VALUES (?, ?, 'running')
                """,
                (request_id, payload_hash),
            )
            return {"claimed": True, "existing": None, "conflict": False}
        except sqlite3.IntegrityError:
            row = conn.execute(
                """
                SELECT request_id, payload_hash, status, response_json, exit_code, created_at
                FROM agent_request_runs
                WHERE request_id = ?
                """,
                (request_id,),
            ).fetchone()
            if row:
                existing = dict(row)
                cutoff = (
                    datetime.now() - timedelta(minutes=max(1, stale_minutes))
                ).strftime("%Y-%m-%d %H:%M:%S")
                if (
                    existing.get("payload_hash") == payload_hash
                    and existing.get("status") == "running"
                    and not existing.get("response_json")
                    and str(existing.get("created_at") or "") <= cutoff
                ):
                    conn.execute(
                        """
                        UPDATE agent_request_runs
                        SET created_at = datetime('now', 'localtime')
                        WHERE request_id = ? AND payload_hash = ? AND status = 'running'
                        """,
                        (request_id, payload_hash),
                    )
                    return {
                        "claimed": True,
                        "existing": existing,
                        "conflict": False,
                        "reclaimed_stale": True,
                    }

    if not row:
        return {"claimed": False, "existing": None, "conflict": False}
    existing = dict(row)
    if existing.get("response_json"):
        existing["response"] = _parse_json_payload(
            existing["response_json"],
            request_id=request_id,
        )
    return {
        "claimed": False,
        "existing": existing,
        "conflict": existing.get("payload_hash") != payload_hash,
    }


def finish_agent_request_run(
    request_id: str,
    *,
    payload_hash: str,
    response: dict,
    exit_code: int,
) -> None:
    """Persist the final response for a claimed non-dry-run agent request."""
    status = "succeeded" if exit_code == 0 else "failed"
    response_json = json.dumps(response, ensure_ascii=False, sort_keys=True)
    with _db() as conn:
        conn.execute(
            """
            UPDATE agent_request_runs
            SET status = ?,
                response_json = ?,
                exit_code = ?,
                finished_at = datetime('now', 'localtime')
            WHERE request_id = ? AND payload_hash = ?
            """,
            (status, response_json, exit_code, request_id, payload_hash),
        )


def list_queued_commands(
    status: str | None = "queued",
    limit: int = 100,
) -> list[dict]:
    """List queue entries by status."""
    with _db() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM command_queue WHERE status = ? ORDER BY queue_created_at ASC LIMIT ?",
                (status, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM command_queue ORDER BY queue_created_at ASC LIMIT ?",
                (limit,),
            ).fetchall()
    return [dict(row) for row in rows]


def _get_queue_row(conn: sqlite3.Connection, request_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM command_queue WHERE request_id = ?", (request_id,)).fetchone()
    return dict(row) if row else None


def claim_next_queued_command() -> dict | None:
    """Claim the oldest queued request and mark it running."""
    with _db() as conn:
        row = conn.execute(
            """
            SELECT request_id, source, request_type, payload, queue_created_at
            FROM command_queue
            WHERE status = 'queued'
            ORDER BY queue_created_at ASC
            LIMIT 1
            """
        ).fetchone()
        if not row:
            return None
        request_id = row["request_id"]
        cursor = conn.execute(
            """
            UPDATE command_queue
            SET status = 'running', attempts = attempts + 1, started_at = datetime('now', 'localtime')
            WHERE request_id = ? AND status = 'queued'
            """,
            (request_id,),
        )
        if cursor.rowcount == 0:
            return None
        full_row = conn.execute(
            """
            SELECT request_id, source, request_type, payload, status,
                   started_at, attempts, queue_created_at
            FROM command_queue
            WHERE request_id = ?
            """,
            (request_id,),
        ).fetchone()
    if not full_row:
        return None
    result = dict(full_row)
    result["payload"] = _parse_json_payload(result["payload"], request_id=request_id)
    return result


def recover_stale_running_commands(
    *,
    stale_minutes: int = 30,
    max_attempts: int = 3,
    limit: int = 500,
) -> dict[str, object]:
    """Recover daemon commands left in `running` after crash, sleep, or restart.

    Stale commands below the retry ceiling are requeued so the daemon can replay
    them. Commands that have already reached the ceiling are moved to
    `dead_letter` and must be explicitly retried.
    """
    if stale_minutes < 1:
        raise ValueError("stale_minutes must be >= 1")
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")
    if limit < 1:
        raise ValueError("limit must be >= 1")

    cutoff = (datetime.now() - timedelta(minutes=stale_minutes)).strftime("%Y-%m-%d %H:%M:%S")
    requeued: list[dict] = []
    dead_lettered: list[dict] = []

    with _db() as conn:
        stale_rows = conn.execute(
            """
            SELECT *
            FROM command_queue
            WHERE status = 'running'
              AND (started_at IS NULL OR started_at <= ?)
            ORDER BY started_at ASC, queue_created_at ASC
            LIMIT ?
            """,
            (cutoff, limit),
        ).fetchall()

        for row in stale_rows:
            request_id = row["request_id"]
            attempts = int(row["attempts"] or 0)
            error_text = (
                "stale running command recovered: "
                f"started_at={row['started_at'] or 'unknown'}, "
                f"stale_minutes={stale_minutes}, attempts={attempts}, max_attempts={max_attempts}"
            )
            if attempts >= max_attempts:
                conn.execute(
                    """
                    UPDATE command_queue
                    SET status = 'dead_letter',
                        finished_at = datetime('now', 'localtime'),
                        last_error = ?,
                        last_exit_code = COALESCE(last_exit_code, 1)
                    WHERE request_id = ?
                    """,
                    (error_text, request_id),
                )
                updated = _get_queue_row(conn, request_id)
                if updated:
                    dead_lettered.append(updated)
                continue

            conn.execute(
                """
                UPDATE command_queue
                SET status = 'queued',
                    started_at = NULL,
                    finished_at = NULL,
                    last_error = ?,
                    last_exit_code = NULL,
                    last_duration_ms = NULL
                WHERE request_id = ?
                """,
                (error_text, request_id),
            )
            updated = _get_queue_row(conn, request_id)
            if updated:
                requeued.append(updated)

    return {
        "stale_minutes": stale_minutes,
        "max_attempts": max_attempts,
        "scanned_count": len(requeued) + len(dead_lettered),
        "requeued_count": len(requeued),
        "dead_lettered_count": len(dead_lettered),
        "requeued": requeued,
        "dead_lettered": dead_lettered,
    }


def list_stale_running_commands(
    *,
    stale_minutes: int = 30,
    max_attempts: int = 3,
    limit: int = 500,
) -> list[dict]:
    """Return stale running commands without mutating queue state."""
    if stale_minutes < 1:
        raise ValueError("stale_minutes must be >= 1")
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")
    if limit < 1:
        raise ValueError("limit must be >= 1")

    cutoff = (datetime.now() - timedelta(minutes=stale_minutes)).strftime("%Y-%m-%d %H:%M:%S")
    with _db() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM command_queue
            WHERE status = 'running'
              AND (started_at IS NULL OR started_at <= ?)
            ORDER BY started_at ASC, queue_created_at ASC
            LIMIT ?
            """,
            (cutoff, limit),
        ).fetchall()

    result = []
    for row in rows:
        item = dict(row)
        item["will_dead_letter"] = int(item.get("attempts") or 0) >= max_attempts
        result.append(item)
    return result


def retry_queued_command(request_id: str) -> dict | None:
    """Move one failed/dead-letter command back to queued for explicit replay."""
    request_id = request_id.strip()
    if not request_id:
        return None

    with _db() as conn:
        cursor = conn.execute(
            """
            UPDATE command_queue
            SET status = 'queued',
                attempts = 0,
                started_at = NULL,
                finished_at = NULL,
                last_error = NULL,
                last_exit_code = NULL,
                last_duration_ms = NULL,
                command_id = NULL
            WHERE request_id = ?
              AND status IN ('failed', 'dead_letter')
            """,
            (request_id,),
        )
        if cursor.rowcount == 0:
            return None
        return _get_queue_row(conn, request_id)


def mark_queued_command_complete(
    request_id: str,
    *,
    status: str,
    command_id: str | None = None,
    exit_code: int = 0,
    error: str | None = None,
    duration_ms: int | None = None,
) -> None:
    """Persist command completion state."""
    with _db() as conn:
        conn.execute(
            """
            UPDATE command_queue
            SET
                status = ?,
                command_id = COALESCE(?, command_id),
                finished_at = datetime('now', 'localtime'),
                last_error = ?,
                last_exit_code = ?,
                last_duration_ms = ?
            WHERE request_id = ?
            """,
            (status, command_id, error, exit_code, duration_ms, request_id),
        )


def mark_queued_command_running_failed(
    request_id: str,
    *,
    command_id: str | None = None,
    error: str | None = None,
) -> int:
    """Mark queued/running command as failed without overwriting exit code info."""
    with _db() as conn:
        cursor = conn.execute(
            """
            UPDATE command_queue
            SET
                status = 'failed',
                command_id = COALESCE(?, command_id),
                finished_at = datetime('now', 'localtime'),
                last_error = COALESCE(?, last_error),
                last_exit_code = COALESCE(last_exit_code, 1)
            WHERE request_id = ? AND status IN ('running', 'queued')
            """,
            (command_id, error, request_id),
        )
    return cursor.rowcount


def log_daemon_run(
    *,
    request_id: str,
    command_id: str,
    request_type: str,
    status: str,
    started_at: str,
    finished_at: str,
    queue_wait_ms: int = 0,
    processing_ms: int = 0,
    total_ms: int = 0,
    payload_size: int = 0,
    error_text: str | None = None,
    output_json: dict | None = None,
) -> str:
    """Persist a single daemon execution attempt for audit and replay."""
    run_id = uuid4().hex[:12]
    with _db() as conn:
        conn.execute(
            """
            INSERT INTO daemon_runs (
                run_id,
                request_id,
                command_id,
                request_type,
                status,
                started_at,
                finished_at,
                queue_wait_ms,
                processing_ms,
                total_ms,
                payload_size,
                error_text,
                output_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                request_id,
                command_id,
                request_type,
                status,
                started_at,
                finished_at,
                queue_wait_ms,
                processing_ms,
                total_ms,
                payload_size,
                error_text,
                json.dumps(output_json, ensure_ascii=False) if output_json is not None else None,
            ),
        )
    return run_id


def get_daemon_runtime_status() -> dict[str, object]:
    """Return queue depth and recent run status for Local Agent runtime."""
    with _db() as conn:
        status_counts = {
            row["status"]: row["count"]
            for row in conn.execute(
                "SELECT status, COUNT(*) AS count FROM command_queue GROUP BY status"
            ).fetchall()
        }
        last_run = conn.execute(
            """
            SELECT
                request_id,
                command_id,
                request_type,
                status,
                finished_at,
                total_ms
            FROM daemon_runs
            ORDER BY finished_at DESC
            LIMIT 1
            """,
        ).fetchone()
    return {
        "queued": status_counts.get("queued", 0),
        "running": status_counts.get("running", 0),
        "succeeded": status_counts.get("succeeded", 0),
        "failed": status_counts.get("failed", 0),
        "dead_letter": status_counts.get("dead_letter", 0),
        "last_run_at": last_run["finished_at"] if last_run else None,
        "last_run_ms": last_run["total_ms"] if last_run else None,
        "last_run_request_id": last_run["request_id"] if last_run else None,
        "last_run_command_id": last_run["command_id"] if last_run else None,
    }


# ── Backward compat (used by tests and legacy code) ─────────────


def load_state() -> dict:
    """Legacy compat: load state as a dict (reads from SQLite now)."""
    streaks = get_habit_streaks()
    return {"habits": streaks}


def save_state(state: dict):
    """Legacy compat: save state dict (writes habits to SQLite)."""
    with _db() as conn:
        for name, info in state.get("habits", {}).items():
            last_logged = info.get("last_logged")
            streak = info.get("streak", 0)
            if last_logged:
                conn.execute(
                    "INSERT OR REPLACE INTO habit_logs (habit_name, date, completed, streak) VALUES (?, ?, 1, ?)",
                    (name, last_logged, streak),
                )


_migrated = False


def _ensure_migrated():
    """Run migration once on first database access."""
    global _migrated
    if not _migrated:
        _migrate_from_json()
        _migrated = True
