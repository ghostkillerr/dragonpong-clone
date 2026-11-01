"""Short live check of the opt-in strike reference protocol."""
import asyncio
import json

from dragonpong.netplay import STRIKE_FEATURE

HOST = 'ekransizoyuncular.gen.tr'
PORT = 8870


async def main():
    connections = []

    async def connect():
        pair = await asyncio.wait_for(asyncio.open_connection(HOST, PORT), 5)
        connections.append(pair)
        return pair

    async def send(pair, kind, **fields):
        pair[1].write((json.dumps({'type': kind, 'protocol': 3, **fields}) + '\n').encode())
        await pair[1].drain()

    async def receive(pair, kind):
        async def read():
            while True:
                line = await pair[0].readline()
                if not line:
                    raise ConnectionError('Server closed the check connection')
                message = json.loads(line)
                if message.get('type') == 'rejected':
                    raise AssertionError(message)
                if message.get('type') == kind:
                    return message
        return await asyncio.wait_for(read(), 5)

    try:
        host, guest = await connect(), await connect()
        await send(host, 'rooms')
        listing = await receive(host, 'rooms')
        assert STRIKE_FEATURE in listing['features']
        await send(host, 'create', name='Sürüm doğrulama', features=[STRIKE_FEATURE])
        room_id = (await receive(host, 'accepted'))['room_id']
        await send(guest, 'join', name='Test rakibi', room_id=room_id,
                   features=[STRIKE_FEATURE])
        assert (await receive(guest, 'accepted'))['player'] == 1
        for pair in (host, guest):
            await receive(pair, 'characters')
            await send(pair, 'character', value=0)
        for pair in (host, guest):
            await receive(pair, 'settings_required')
        await send(host, 'configure', score=10, shield=False, silent_ball=False)
        for pair in (host, guest):
            await receive(pair, 'configured')
        await send(host, 'start')
        for pair in (host, guest):
            await receive(pair, 'started')
        state = await receive(host, 'state')
        assert state['flight_id'] == 0 and state['velocity'] == [0, 0]
        await send(host, 'strike', press=1,
                   view={'frame': state['frame_id'], 'seconds': 0})
        result = await receive(host, 'strike_result')
        assert result['result'] == 'serve', result
        print(json.dumps({'host': HOST, 'feature': STRIKE_FEATURE,
                          'serve_result': result['result'], 'passed': True}))
    finally:
        for _, writer in connections:
            writer.close()
        await asyncio.gather(*(writer.wait_closed() for _, writer in connections),
                             return_exceptions=True)


if __name__ == '__main__':
    asyncio.run(main())
