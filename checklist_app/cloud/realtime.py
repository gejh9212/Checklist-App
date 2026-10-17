"""Realtime invalidates snapshots; polling remains authoritative and recovers misses."""
import asyncio
import threading


class RealtimeWatcher:
    def __init__(self, client, config, user_id, invalidate):
        self.client = client
        self.config = config
        self.user_id = user_id
        self.invalidate = invalidate
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.run,daemon=True)
        self.thread.start()

    def run(self):
        try:
            asyncio.run(self.listen())
        except Exception:
            # Polling/reconnection remains active; never log session-bearing SDK errors.
            pass

    async def listen(self):
        from realtime import AsyncRealtimeClient
        session = self.client.auth.get_session()
        if not session:
            return
        realtime = AsyncRealtimeClient(self.config.url.replace('https://','wss://')+'/realtime/v1', token=self.config.key, params={'apikey':self.config.key})
        await realtime.set_auth(session.access_token)
        try:
            await realtime.connect()
            channel = realtime.channel('account-'+self.user_id)
            channel.on_postgres_changes('UPDATE',lambda event:self.invalidate(),table='profiles',schema='public',filter='user_id=eq.'+self.user_id)
            await channel.subscribe(lambda state,error=None:self.invalidate())
            token = session.access_token
            while not self.stop.is_set():
                await asyncio.sleep(1)
                current = self.client.auth.get_session()
                if current and current.access_token!=token:
                    token = current.access_token
                    await realtime.set_auth(token)
        finally:
            await realtime.close()

    def close(self):
        self.stop.set()
