"""Append-only005 registration; reports are not candidate pre-release results."""
from . import baselines

_IMMUTABLE = ('id', 'operation_key', 'payload_digest', 'candidate_id', 'publication_operation_key',
    'soup_id', 'puzzle_version', 'published_rule_version', 'published_at', 'started_at', 'deadline_at',
    'traffic_class', 'evidence_kind', 'plan_json', 'plan_digest', 'planned_case_count')

POST_PUBLICATION_SQL = (
    """CREATE TABLE post_publication_runs (
        id TEXT PRIMARY KEY NOT NULL,operation_key TEXT NOT NULL UNIQUE,
        payload_digest TEXT NOT NULL CHECK(length(payload_digest)=64 AND payload_digest NOT GLOB '*[^0-9a-f]*'),
        candidate_id TEXT NOT NULL REFERENCES rule_candidates(id),publication_operation_key TEXT NOT NULL,
        soup_id TEXT NOT NULL,puzzle_version TEXT NOT NULL REFERENCES puzzle_versions(id),
        published_rule_version TEXT NOT NULL REFERENCES rule_releases(id),
        published_at REAL NOT NULL CHECK(published_at>=0 AND published_at<1e15),
        started_at REAL NOT NULL CHECK(started_at>=published_at AND started_at<1e15),
        deadline_at REAL NOT NULL CHECK(deadline_at>started_at AND deadline_at<=started_at+5),
        traffic_class TEXT NOT NULL CHECK(traffic_class IN ('real','test','synthetic','unknown')),
        evidence_kind TEXT NOT NULL CHECK(evidence_kind IN ('synthetic_fixture','deterministic_regression')),
        plan_json TEXT NOT NULL CHECK(length(plan_json) BETWEEN 1 AND 65536 AND json_valid(plan_json)),
        plan_digest TEXT NOT NULL CHECK(length(plan_digest)=64 AND plan_digest NOT GLOB '*[^0-9a-f]*'),
        planned_case_count INTEGER NOT NULL CHECK(typeof(planned_case_count)='integer' AND planned_case_count BETWEEN 1 AND 100),
        state TEXT NOT NULL CHECK(state IN ('running','passed','failed','incomplete')),
        attempted_case_count INTEGER NOT NULL DEFAULT 0 CHECK(typeof(attempted_case_count)='integer' AND attempted_case_count BETWEEN 0 AND planned_case_count),
        passed_case_count INTEGER NOT NULL DEFAULT 0 CHECK(typeof(passed_case_count)='integer' AND passed_case_count>=0),
        counterexample_case_count INTEGER NOT NULL DEFAULT 0 CHECK(typeof(counterexample_case_count)='integer' AND counterexample_case_count>=0),
        error_case_count INTEGER NOT NULL DEFAULT 0 CHECK(typeof(error_case_count)='integer' AND error_case_count>=0),
        unsupported_case_count INTEGER NOT NULL DEFAULT 0 CHECK(typeof(unsupported_case_count)='integer' AND unsupported_case_count>=0),
        result_json TEXT CHECK(result_json IS NULL OR (length(result_json) BETWEEN 1 AND 65536 AND json_valid(result_json))),
        result_digest TEXT CHECK(result_digest IS NULL OR (length(result_digest)=64 AND result_digest NOT GLOB '*[^0-9a-f]*')),
        finished_at REAL CHECK(finished_at IS NULL OR (finished_at>=started_at AND finished_at<1e15)),
        CHECK(attempted_case_count=passed_case_count+counterexample_case_count+error_case_count+unsupported_case_count),
        CHECK((state='running' AND attempted_case_count=0 AND result_json IS NULL AND result_digest IS NULL AND finished_at IS NULL)
            OR (state!='running' AND result_json IS NOT NULL AND result_digest IS NOT NULL AND finished_at IS NOT NULL)),
        CHECK(state!='passed' OR (passed_case_count=planned_case_count AND finished_at<=deadline_at)),
        CHECK((state='failed')=(counterexample_case_count>0)),
        CHECK(traffic_class!='real' OR evidence_kind!='synthetic_fixture'))""",
    'CREATE INDEX idx_post_publication_started ON post_publication_runs(started_at,id)',
    "CREATE TRIGGER post_publication_runs_plan_immutable BEFORE UPDATE ON post_publication_runs WHEN "
        + ' OR '.join(f'NEW.{name} IS NOT OLD.{name}' for name in _IMMUTABLE)
        + " BEGIN SELECT RAISE(ABORT,'immutable post-publication plan'); END",
    """CREATE TRIGGER post_publication_runs_terminal_immutable BEFORE UPDATE ON post_publication_runs
        WHEN OLD.state!='running' OR NEW.state='running'
        BEGIN SELECT RAISE(ABORT,'immutable post-publication outcome'); END""",
    """CREATE TRIGGER post_publication_runs_no_delete BEFORE DELETE ON post_publication_runs
        BEGIN SELECT RAISE(ABORT,'immutable post-publication history'); END""",
)

POST_PUBLICATION_OBJECTS = (
    ('table', 'post_publication_runs'), ('index', 'idx_post_publication_started'),
    ('trigger', 'post_publication_runs_plan_immutable'),
    ('trigger', 'post_publication_runs_terminal_immutable'), ('trigger', 'post_publication_runs_no_delete'),
)
CHECKSUM_005 = baselines.digest({'version': 5, 'sql': POST_PUBLICATION_SQL,
    'coverageContract': 'post-publication-observation-v1'})
