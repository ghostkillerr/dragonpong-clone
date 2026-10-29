"""Bounded live test; creates only its own rooms and closes every connection."""
import asyncio
import json
from pathlib import Path

HOST = 'ekransizoyuncular.gen.tr'


async def main():
    writers = []
    async def connect():
        reader, writer = await asyncio.wait_for(asyncio.open_connection(HOST, 8870), 5)
        writers.append(writer)
        return reader, writer
    async def send(pair, kind, **fields):
        pair[1].write((json.dumps(dict(type=kind, protocol=2, **fields)) + '\n').encode())
        await pair[1].drain()
    async def receive(pair, kind, predicate=lambda message: True):
        async def loop():
            for _ in range(300):
                line = await pair[0].readline()
                if not line:
                    raise AssertionError('Connection ended early')
                item = json.loads(line)
                if item['type'] == 'rejected':
                    raise AssertionError(item)
                if item['type'] == kind and predicate(item):
                    return item
            raise AssertionError(f'Missing {kind}')
        return await asyncio.wait_for(loop(), 8)
    try:
        hosts = [await connect(), await connect()]
        guests = [await connect(), await connect()]
        ids = []
        for index, host in enumerate(hosts):
            await send(host, 'create', name=f'Klon doğrulama {index + 1}')
            ids.append((await receive(host, 'accepted'))['room_id'])
        assert ids[0] != ids[1]
        for index in range(2):
            await send(guests[index], 'join', name='Test rakibi', room_id=ids[index])
            assert (await receive(guests[index], 'accepted'))['player'] == 1
            for pair in (hosts[index], guests[index]):
                await receive(pair, 'characters')
                await send(pair, 'character', value=index)
            for pair in (hosts[index], guests[index]):
                await receive(pair, 'settings_required')
            await send(hosts[index], 'configure', score=30, shield=True, silent_ball=True)
            for pair in (hosts[index], guests[index]):
                assert (await receive(pair, 'configured'))['score'] == 30
            await send(hosts[index], 'start')
            for pair in (hosts[index], guests[index]):
                await receive(pair, 'started')
        viewer = await connect()
        await send(viewer, 'spectate', name='Test izleyicisi', room_id=ids[0])
        assert (await receive(viewer, 'accepted'))['player'] is None
        await send(viewer, 'perspective', player=1)
        assert (await receive(viewer, 'perspective'))['player'] == 1
        await send(hosts[0], 'step', direction=1)
        await send(guests[0], 'step', direction=1)
        await send(hosts[0], 'strike')
        state = await receive(viewer, 'state', lambda s: s['paddles'] == [1, -1] and s['velocity'][1] > 0)
        other = await receive(hosts[1], 'state')
        assert other['velocity'] == [0, 0] and other['paddles'] == [0, 0]
        report = dict(host=HOST, port=8870, rooms=2, players=4, spectators=1,
                      settings_score=30, mirrored_controls=True, serve=True,
                      isolated_rooms=True, spectator_perspective=True, passed=True)
        Path('public_verification.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps(report, indent=2))
    finally:
        for writer in writers:
            writer.close()
        await asyncio.gather(*(w.wait_closed() for w in writers), return_exceptions=True)


if __name__ == '__main__':
    asyncio.run(main())
