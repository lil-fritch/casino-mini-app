import json
from channels.generic.websocket import AsyncWebsocketConsumer
from django.core.cache import cache

class NotificationConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.user = self.scope.get("user")
        if not self.user or self.user.is_anonymous:
            await self.close()
            return

        self.group_name = f"user_{self.user.id}"

        online_users = cache.get("online_users", set())
        online_users.add(self.user.id)
        cache.set("online_users", online_users, timeout=300)

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

        online_users = cache.get("online_users", set())
        online_users.discard(self.user.id)
        cache.set("online_users", online_users)

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
            if data.get("type") == "ping":
                online_users = cache.get("online_users", set())
                online_users.add(self.user.id)
                cache.set("online_users", online_users, timeout=300)
        except json.JSONDecodeError:
            pass

    async def send_notification(self, event):
        await self.send(text_data=json.dumps(event))
