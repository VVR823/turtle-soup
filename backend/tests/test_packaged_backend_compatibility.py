"""Actual packaged code in a fresh child, not editable-source compatibility.

Characterizes schema one refusal, two-five core replay and metrics boundaries.
Frozen old release refusal is separately pinned; its absence is an explicit skip.
"""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
from uuid import uuid4

import pytest

from .test_release_recovery import fixture_source, hashes, recovery_module

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope='module')
def current_artifact():
    target = ROOT / '.cache' / ('d18-compat-' + str(uuid4()) + '-artifact')
    built = subprocess.run([shutil.which('node'), '--input-type=module', '-e',
        "import {buildBackendRelease} from './scripts/backend-release-policy.mjs'; "
        "console.log(JSON.stringify(buildBackendRelease(process.cwd(), process.argv[1])));", str(target)],
        cwd=ROOT, capture_output=True, text=True, timeout=30)
    assert built.returncode == 0, built.stderr
    assert json.loads(built.stdout)['productionReady'] is False
    return target


def child(artifact, data, version, *, reject):
    result = subprocess.run([sys.executable, '-I', '-B',
        str(ROOT / 'scripts/tests/probe-backend-compatibility.py'),
        str(artifact / 'backend'), str(data), str(version), 'reject' if reject else 'accept'],
        cwd=artifact, capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == dict(status='passed', migrationVersion=version,
        rejected=reject, moduleOriginsVerified=True, ownedResourcesClosed=True,
        networkAttempts=0, productionReady=False)


@pytest.mark.parametrize('version', [1, 2, 3, 4, 5])
def test_new_artifact_actual_restored_schema_core_and_metrics(tmp_path, current_artifact, version):
    source = fixture_source(tmp_path, version)
    before, frozen = hashes(source), hashes(current_artifact)
    recovery = recovery_module()
    recovery.backup(str(source), str(tmp_path / 'snapshot'), str(tmp_path / 'backup.json'))
    recovery.restore(str(tmp_path / 'snapshot'), str(tmp_path / 'restored'), str(tmp_path / 'restore.json'))
    child(current_artifact, tmp_path / 'restored', version, reject=version == 1)
    assert hashes(source) == before and hashes(current_artifact) == frozen


def test_pinned_old_schema_four_artifact_refuses_schema_five_without_writes(tmp_path):
    old = ROOT / '.cache/ts17-backend-VEVQiL-artifact'
    manifest = old / 'release-manifest.json'
    if not manifest.is_file():
        pytest.skip('Pinned historical artifact absent; no old-release compatibility claim')
    assert hashlib.sha256(manifest.read_bytes()).hexdigest() == 'ab61062c21dc29eaeca16234ed459415815eff10b1bb298922aaf73c2220fa85'
    files = json.loads(manifest.read_text(encoding='utf-8'))['files']
    frozen = hashes(old)
    assert {name: digest for name, digest in frozen.items() if name != 'release-manifest.json'} == files
    source = fixture_source(tmp_path, 5)
    before = hashes(source)
    child(old, source, 5, reject=True)
    assert hashes(source) == before and hashes(old) == frozen
