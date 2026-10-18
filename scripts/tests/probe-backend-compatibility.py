"""Fresh interpreter tests a named LOCAL artifact against synthetic restored data.

No editable import fallback, migration, real provider or production permission.
"""
import hashlib
import json
from pathlib import Path
import socket
import sqlite3
import sys
from threading import local
from uuid import uuid4

backend, data = (Path(value).resolve() for value in sys.argv[1:3])
version, rejected = int(sys.argv[3]), sys.argv[4] == 'reject'
assert backend.is_dir() and data.is_dir()
assert not any(name == 'app' or name.startswith('app.') for name in sys.modules)
sys.path.insert(0, str(backend))
attempts, internal_pair = [], local()
original_connect, original_pair = socket.socket.connect, socket.socketpair


def no_network(*args, **kwargs):
    attempts.append(True)
    raise RuntimeError('Network forbidden in compatibility rehearsal')


def guarded_connect(sock, address):
    if getattr(internal_pair, 'constructing', False):
        return original_connect(sock, address)
    return no_network()


def local_pair(*args, **kwargs):
    internal_pair.constructing = True
    try:
        return original_pair(*args, **kwargs)
    finally:
        internal_pair.constructing = False


socket.socket.connect = guarded_connect
socket.socketpair = local_pair
socket.socket.connect_ex = socket.create_connection = socket.getaddrinfo = no_network

from fastapi.testclient import TestClient
from app import migrations
from app.config import Settings
from app.main import create_app
from app.schemas import Soup
from app.testing import FakeModel

soup = Soup(id='synthetic', title='Test', surface='Surface', bottom='Truth',
    checkpoints=[{'key': 'fact', 'answer': True}],
    confusionPoints=[{'q': 'Question?', 'a': '是'}])
model = FakeModel()
application = create_app(Settings.for_test(data, ADMIN_TOKEN='synthetic-admin'), model=model, soups=[soup])


def hashes():
    return {file.relative_to(data).as_posix(): hashlib.sha256(file.read_bytes()).hexdigest()
        for file in data.rglob('*') if file.is_file()}


before = hashes()
if rejected:
    try:
        with TestClient(application):
            raise AssertionError('Unsupported schema must not open for writing')
    except migrations.MigrationError:
        pass
    assert hashes() == before
    assert application.state.runtime.model_gateway is None
else:
    with TestClient(application) as client:
        history = client.get('/api/session/old')
        assert history.status_code == 200 and history.json()['questionsAsked'] == 1
        assert [item['content'] for item in history.json()['messages']] == ['Question?', '是']
        ask = dict(sessionId='old', question='Question?', requestId=str(uuid4()))
        answered = client.post('/api/chat', json=ask)
        # Unsupported assertion grammar remains a normal contextual model question.
        # FakeModel's literal scripted reply is not evidence of semantic quality.
        assert answered.status_code == 200, answered.text
        assert answered.json()['reply'] == '与此无关', answered.json()
        assert client.post('/api/chat', json=ask).content == answered.content
        assert client.get('/api/session/old').json()['questionsAsked'] == 2
        metrics = client.get('/api/metrics/admin', headers={'X-Admin-Token': 'synthetic-admin'},
            params={'start': 0, 'end': 1000})
        if version < 4:
            assert metrics.status_code == 503
        else:
            assert metrics.status_code == 200 and metrics.json()['schemaVersion'] == 3
            summary = metrics.json()['summary']['postPublicationRegression']
            if version == 4:
                assert summary == dict(state='unknown', failedRuns=None, observedRuns=None, reason='schema_5_required')
            else:
                assert summary['state'] == 'partial' and summary['observedRuns'] == summary['failedRuns'] == 0
                assert summary['excluded']['test']['observedRuns'] == 0
    with sqlite3.connect(data / 'sessions.db') as conn:
        assert conn.execute('SELECT max(version) FROM schema_migrations').fetchone()[0] == version
        assert conn.execute("SELECT questions_asked FROM sessions WHERE id='old'").fetchone()[0] == 2
    assert len(model.calls) == 1  # One fake transport call; replay never re-calls it.

runtime = application.state.runtime
assert runtime.closed and runtime.agent_worker is None
if runtime.model_gateway is not None:
    state = runtime.model_gateway.snapshot()
    assert state['closed'] and state['active'] == state['waiting_online'] == state['cleanup_failed'] == 0
if runtime.audit_store is not None:
    assert runtime.audit_shutdown['residualJobs'] == runtime.audit_shutdown['unpersistedCount'] == 0
origins = [module for name, module in sys.modules.items()
    if name in {'app', 'eval'} or name.startswith(('app.', 'eval.'))]
assert len(origins) > 30
assert all(Path(module.__file__).resolve().is_relative_to(backend) for module in origins)
assert not attempts
print(json.dumps(dict(status='passed', migrationVersion=version, rejected=rejected,
    moduleOriginsVerified=True, ownedResourcesClosed=True, networkAttempts=0, productionReady=False)))
