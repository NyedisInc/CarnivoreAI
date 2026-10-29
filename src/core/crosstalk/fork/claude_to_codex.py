
from __future__ import annotations

import asyncio
import os
import tempfile
import uuid
from pathlib import Path

import websockets

from src.core.crosstalk.delivery.codex_appserver import _request


async def import_session(data: bytes, *, conversation: str, cwd: str,
                         codex_home: str | None = None) -> str:
    from src.core.crosstalk.fork.history import MAX_SOURCE_BYTES

    if len(data) > MAX_SOURCE_BYTES:
        raise ValueError('fork source exceeds the 64 MiB conversion limit')
    source_name = str(uuid.UUID(conversation)) + '.jsonl'
    projects = Path.home() / '.claude' / 'projects'
    projects.mkdir(parents=True, exist_ok=True, mode=0o700)
    # CLAUDE_CONFIG_DIR
    with tempfile.TemporaryDirectory(prefix='carnivore-fork-', dir='/tmp') as temporary, \
            tempfile.TemporaryDirectory(prefix='carnivore-fork-', dir=projects) as snapshot:
        directory = Path(temporary)
        source = Path(snapshot) / source_name
        source.write_bytes(data)
        source.chmod(0o600)
        socket = directory / 'app.sock'
        environment = os.environ.copy()
        if codex_home:
            environment['CODEX_HOME'] = codex_home
        else:
            environment.pop('CODEX_HOME', None)
        process = await asyncio.create_subprocess_exec(
            'codex', 'app-server', '--listen', 'unix://' + str(socket),
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL, env=environment)
        try:
            for _ in range(80):
                if socket.exists():
                    break
                if process.returncode is not None:
                    raise RuntimeError('Codex importer failed to start')
                await asyncio.sleep(0.1)
            if not socket.exists():
                raise TimeoutError('Codex importer did not open its socket')
            async with websockets.unix_connect(str(socket), open_timeout=3) as ws:
                await _request(ws, 'initialize', {'clientInfo': {'name': 'carnivore-fork', 'version': '1.0.0'},
                                                   'capabilities': {}}, 1)
                await ws.send('{"jsonrpc":"2.0","method":"initialized","params":{}}')
                result = await _request(ws, 'externalAgentConfig/import', {
                    'migrationItems': [{'itemType': 'SESSIONS', 'description': 'Carnivore fork', 'cwd': cwd,
                                        'details': {'sessions': [{'cwd': cwd, 'path': str(source)}]}}],
                    'providerId': 'claude', 'source': 'carnivore-fork',
                }, 2)
                import_id = result.get('importId')
                if not import_id:
                    raise ValueError('Codex importer returned no import id')
                for _ in range(60):
                    histories = await _request(ws, 'externalAgentConfig/import/readHistories', {}, 3)
                    record = next((item for item in histories.get('data', []) if item.get('importId') == import_id), None)
                    if record:
                        if record.get('failures'):
                            failure = record['failures'][0]
                            raise ValueError('Codex importer refused the Claude transcript: '
                                             + str(failure.get('failureStage', 'unknown')) + ': '
                                             + str(failure.get('message', 'unknown')))
                        target = next((item.get('target') for item in record.get('successes', [])
                                       if item.get('itemType') == 'SESSIONS'), None)
                        if target:
                            return str(target)
                        raise ValueError('Codex importer completed without a target thread')
                    await asyncio.sleep(0.5)
                raise TimeoutError('Codex import did not complete within 30 seconds')
        finally:
            if process.returncode is None:
                process.terminate()
            try:
                await asyncio.wait_for(process.wait(), 3)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
