from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any


DEFAULT_DB = Path(os.environ.get("EVALFORGE_DB", "evalforge.sqlite3"))


class TraceStore:
    def __init__(self, path: str | Path = DEFAULT_DB) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS traces (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                    input TEXT NOT NULL,
                    tool_calls TEXT NOT NULL,
                    output TEXT NOT NULL,
                    feature TEXT NOT NULL DEFAULT '',
                    scenario TEXT NOT NULL DEFAULT '',
                    prompt_version TEXT NOT NULL,
                    suite_version TEXT NOT NULL DEFAULT 'scenarios-v1',
                    assertions_passed INTEGER,
                    assertion_details TEXT NOT NULL DEFAULT '[]'
                );
                CREATE TABLE IF NOT EXISTS labels (
                    trace_id INTEGER PRIMARY KEY REFERENCES traces(id),
                    is_good INTEGER NOT NULL CHECK (is_good IN (0, 1)),
                    critique TEXT NOT NULL DEFAULT '',
                    final_output TEXT,
                    source TEXT NOT NULL DEFAULT 'human' CHECK (source IN ('human', 'assistant')),
                    labeled_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                );
                CREATE TABLE IF NOT EXISTS judge_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trace_id INTEGER NOT NULL REFERENCES traces(id),
                    judge_version TEXT NOT NULL,
                    critique TEXT NOT NULL,
                    is_good INTEGER NOT NULL CHECK (is_good IN (0, 1)),
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                );
                """
            )
            label_columns = {row["name"] for row in db.execute("PRAGMA table_info(labels)")}
            if "source" not in label_columns:
                db.execute(
                    "ALTER TABLE labels ADD COLUMN source TEXT NOT NULL DEFAULT 'human' "
                    "CHECK (source IN ('human', 'assistant'))"
                )

    def add_trace(
        self,
        *,
        user_input: str,
        tool_calls: list[dict[str, Any]],
        output: str,
        prompt_version: str,
        feature: str = "",
        scenario: str = "",
        suite_version: str = "scenarios-v1",
        assertions_passed: bool | None = None,
        assertion_details: list[dict[str, Any]] | None = None,
    ) -> int:
        with self._connect() as db:
            cursor = db.execute(
                """INSERT INTO traces
                (input, tool_calls, output, feature, scenario, prompt_version, suite_version,
                 assertions_passed, assertion_details)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    user_input,
                    json.dumps(tool_calls),
                    output,
                    feature,
                    scenario,
                    prompt_version,
                    suite_version,
                    None if assertions_passed is None else int(assertions_passed),
                    json.dumps(assertion_details or []),
                ),
            )
            return int(cursor.lastrowid)

    def list_traces(
        self, *, feature: str | None = None, scenario: str | None = None, limit: int = 500
    ) -> list[dict[str, Any]]:
        query = """
            SELECT t.*, l.is_good, l.critique, l.final_output, l.source AS label_source,
                   j.judge_version, j.critique AS judge_critique, j.is_good AS judge_is_good
            FROM traces t
            LEFT JOIN labels l ON l.trace_id = t.id
            LEFT JOIN judge_results j ON j.id = (
                SELECT MAX(j2.id) FROM judge_results j2 WHERE j2.trace_id = t.id
            )
            WHERE (? IS NULL OR t.feature = ?)
              AND (? IS NULL OR t.scenario = ?)
            ORDER BY t.id DESC LIMIT ?
        """
        with self._connect() as db:
            rows = db.execute(query, (feature, feature, scenario, scenario, limit)).fetchall()
        return [dict(row) for row in rows]

    def save_label(
        self,
        trace_id: int,
        is_good: bool,
        critique: str,
        final_output: str,
        *,
        source: str = "human",
    ) -> None:
        if source not in ("human", "assistant"):
            raise ValueError("Label source must be 'human' or 'assistant'.")
        with self._connect() as db:
            db.execute(
                """INSERT INTO labels (trace_id, is_good, critique, final_output, source)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(trace_id) DO UPDATE SET
                    is_good=excluded.is_good, critique=excluded.critique,
                    final_output=excluded.final_output,
                    source=excluded.source,
                    labeled_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')""",
                (trace_id, int(is_good), critique, final_output, source),
            )

    def add_judge_result(
        self, trace_id: int, judge_version: str, critique: str, is_good: bool
    ) -> None:
        with self._connect() as db:
            db.execute(
                "INSERT INTO judge_results (trace_id, judge_version, critique, is_good) VALUES (?, ?, ?, ?)",
                (trace_id, judge_version, critique, int(is_good)),
            )

    def pass_rates(self) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                """SELECT date(created_at) AS day, prompt_version, suite_version,
                          COUNT(*) AS total, SUM(assertions_passed) AS passed
                   FROM traces WHERE assertions_passed IS NOT NULL
                   GROUP BY day, prompt_version, suite_version ORDER BY day"""
            ).fetchall()
        return [dict(row) for row in rows]

    def judge_alignment(self, judge_version: str | None = None) -> dict[str, Any]:
        with self._connect() as db:
            rows = db.execute(
                """SELECT l.is_good AS human, j.is_good AS judged
                   FROM labels l JOIN judge_results j ON j.trace_id = l.trace_id
                   WHERE l.source = 'human' AND j.id = (
                       SELECT MAX(j2.id) FROM judge_results j2
                       WHERE j2.trace_id = l.trace_id
                         AND (? IS NULL OR j2.judge_version = ?)
                   )""",
                (judge_version, judge_version),
            ).fetchall()
        pairs = [(int(row["human"]), int(row["judged"])) for row in rows]
        tp = sum(h == 1 and j == 1 for h, j in pairs)
        fp = sum(h == 0 and j == 1 for h, j in pairs)
        fn = sum(h == 1 and j == 0 for h, j in pairs)
        return {
            "n": len(pairs),
            "precision": tp / (tp + fp) if tp + fp else None,
            "recall": tp / (tp + fn) if tp + fn else None,
            "tp": tp,
            "fp": fp,
            "fn": fn,
        }
