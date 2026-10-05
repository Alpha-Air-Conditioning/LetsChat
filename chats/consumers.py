import json
from django.utils import timezone

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

from django.db.models import Q

from .models import BlockedUser, Conversation, Message, Profile


class ChatConsumer(AsyncWebsocketConsumer):

    async def connect(self):
        self.conversation_id = self.scope['url_route']['kwargs']['conversation_id']
        self.user = self.scope['user']

        if not self.user.is_authenticated:
            await self.close(code=4401)
            return

        allowed = await self.is_member()
        if not allowed:
            await self.close(code=4403)
            return

        self.room_group_name = f'chat_{self.conversation_id}'
        self.user_group_name = f'user_{self.user.id}'

        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )
        await self.channel_layer.group_add(
            self.user_group_name,
            self.channel_name
        )
        await self.channel_layer.group_add(
            'global_presence',
            self.channel_name
        )

        await self.accept()

        # Update online presence
        await self.set_user_presence(True)
        await self.broadcast_presence(True)

    async def disconnect(self, close_code):
        if hasattr(self, 'room_group_name'):
            await self.channel_layer.group_discard(
                self.room_group_name,
                self.channel_name
            )
        if hasattr(self, 'user_group_name'):
            await self.channel_layer.group_discard(
                self.user_group_name,
                self.channel_name
            )
        if hasattr(self, 'user') and self.user.is_authenticated:
            await self.channel_layer.group_discard(
                'global_presence',
                self.channel_name
            )
            await self.set_user_presence(False)
            await self.broadcast_presence(False)

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
        except json.JSONDecodeError:
            return

        action = data.get('action')

        # Handle ping keepalive
        if action == 'ping':
            await self.send(text_data=json.dumps({'action': 'pong'}))
            return

        # Handle real-time message deletion
        if action == 'delete_message':
            message_id = data.get('message_id')
            if message_id:
                deleted = await self.delete_message_async(message_id)
                if deleted:
                    await self.channel_layer.group_send(
                        self.room_group_name,
                        {
                            'type': 'message_deleted',
                            'message_id': message_id,
                        }
                    )
            return

        # Handle WebRTC Call Signaling (Audio & Video Calling)
        if action in ['call_offer', 'call_answer', 'ice_candidate', 'call_reject', 'call_end', 'call_busy']:
            avatar_url = await self.get_sender_avatar()
            signal_payload = {
                'type': 'call_signal',
                'action': action,
                'sender': self.user.username,
                'sender_avatar': avatar_url,
                'call_type': data.get('call_type', 'video'),
                'sdp': data.get('sdp'),
                'candidate': data.get('candidate'),
                'conversation_id': self.conversation_id,
            }
            # Broadcast to chat room
            await self.channel_layer.group_send(
                self.room_group_name,
                signal_payload
            )
            # Also notify each participant directly on their personal user channel
            participant_ids = await self.get_other_participant_ids()
            for p_id in participant_ids:
                await self.channel_layer.group_send(
                    f'user_{p_id}',
                    signal_payload
                )
            return

        # Check if conversation is blocked
        blocked = await self.is_conversation_blocked()
        if blocked:
            await self.send(
                text_data=json.dumps({
                    'error': 'This conversation is blocked.'
                })
            )
            return

        # Handle sending new message
        message_text = data.get('message', '').strip()

        if not message_text or len(message_text) > 5000:
            return

        message = await self.create_message(message_text)
        avatar_url = await self.get_sender_avatar()

        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'chat_message',
                'id': message.id,
                'message': message.content,
                'sender': self.user.username,
                'sender_avatar': avatar_url,
                'created_at': message.created_at.isoformat(),
            }
        )

    async def chat_message(self, event):
        await self.send(
            text_data=json.dumps({
                'id': event['id'],
                'message': event['message'],
                'audio_url': event.get('audio_url'),
                'sender': event['sender'],
                'sender_avatar': event.get('sender_avatar'),
                'created_at': event['created_at'],
            })
        )

    async def message_deleted(self, event):
        await self.send(
            text_data=json.dumps({
                'action': 'delete',
                'message_id': event['message_id'],
            })
        )

    async def call_signal(self, event):
        await self.send(
            text_data=json.dumps({
                'action': event['action'],
                'sender': event['sender'],
                'sender_avatar': event.get('sender_avatar'),
                'call_type': event.get('call_type', 'video'),
                'sdp': event.get('sdp'),
                'candidate': event.get('candidate'),
                'conversation_id': event.get('conversation_id'),
            })
        )

    async def presence_update(self, event):
        await self.send(
            text_data=json.dumps({
                'action': 'presence_update',
                'user_id': event['user_id'],
                'username': event['username'],
                'is_online': event['is_online'],
                'last_seen': event['last_seen'],
            })
        )

    async def broadcast_presence(self, is_online):
        last_seen = await self.get_last_seen_display()
        await self.channel_layer.group_send(
            'global_presence',
            {
                'type': 'presence_update',
                'user_id': self.user.id,
                'username': self.user.username,
                'is_online': is_online,
                'last_seen': last_seen,
            }
        )

    @database_sync_to_async
    def set_user_presence(self, is_online):
        try:
            profile = getattr(self.user, 'profile', None)
            if not profile:
                profile = Profile.objects.get_or_create(user=self.user)[0]
            profile.is_online = is_online
            profile.last_seen = timezone.now()
            profile.save(update_fields=['is_online', 'last_seen'])
        except Exception:
            pass

    @database_sync_to_async
    def get_last_seen_display(self):
        try:
            profile = getattr(self.user, 'profile', None)
            if profile:
                return profile.last_seen_display
        except Exception:
            pass
        return "offline"

    @database_sync_to_async
    def is_member(self):
        return Conversation.objects.filter(
            id=self.conversation_id,
            participants=self.user
        ).exists()

    @database_sync_to_async
    def is_conversation_blocked(self):
        conv = Conversation.objects.filter(id=self.conversation_id).first()
        if not conv:
            return True
        participants = list(conv.participants.all())
        if len(participants) >= 2:
            p1, p2 = participants[0], participants[1]
            return BlockedUser.objects.filter(
                (Q(blocker=p1, blocked=p2) | Q(blocker=p2, blocked=p1))
            ).exists()
        return False

    @database_sync_to_async
    def get_sender_avatar(self):
        if hasattr(self.user, 'profile') and self.user.profile.avatar:
            try:
                return self.user.profile.avatar.url
            except Exception:
                return None
        return None

    @database_sync_to_async
    def create_message(self, content):
        conversation = Conversation.objects.get(id=self.conversation_id)
        message = Message.objects.create(
            conversation=conversation,
            sender=self.user,
            content=content
        )
        conversation.save(update_fields=['updated_at'])
        return message

    @database_sync_to_async
    def get_other_participant_ids(self):
        conv = Conversation.objects.filter(id=self.conversation_id).first()
        if not conv:
            return []
        return list(conv.participants.exclude(id=self.user.id).values_list('id', flat=True))

    @database_sync_to_async
    def delete_message_async(self, message_id):
        try:
            msg = Message.objects.get(
                id=message_id,
                conversation_id=self.conversation_id,
                sender=self.user
            )
            msg.delete()
            return True
        except Message.DoesNotExist:
            return False


class UserConsumer(AsyncWebsocketConsumer):
    """Global User WebSocket for incoming call notifications and presence across all pages."""

    async def connect(self):
        self.user = self.scope['user']
        if not self.user.is_authenticated:
            await self.close(code=4401)
            return

        self.user_group_name = f'user_{self.user.id}'
        await self.channel_layer.group_add(
            self.user_group_name,
            self.channel_name
        )
        await self.channel_layer.group_add(
            'global_presence',
            self.channel_name
        )
        await self.accept()

        await self.set_user_presence(True)
        await self.broadcast_presence(True)

    async def disconnect(self, close_code):
        if hasattr(self, 'user_group_name'):
            await self.channel_layer.group_discard(
                self.user_group_name,
                self.channel_name
            )
        if hasattr(self, 'user') and self.user.is_authenticated:
            await self.channel_layer.group_discard(
                'global_presence',
                self.channel_name
            )
            await self.set_user_presence(False)
            await self.broadcast_presence(False)

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
        except Exception:
            return

        action = data.get('action')
        if action == 'ping':
            await self.send(text_data=json.dumps({'action': 'pong'}))
            return

        if action in ['call_offer', 'call_answer', 'ice_candidate', 'call_reject', 'call_busy', 'call_end']:
            conversation_id = data.get('conversation_id')
            if conversation_id:
                avatar_url = await self.get_sender_avatar()
                await self.channel_layer.group_send(
                    f'chat_{conversation_id}',
                    {
                        'type': 'call_signal',
                        'action': action,
                        'sender': self.user.username,
                        'sender_avatar': avatar_url,
                        'call_type': data.get('call_type', 'video'),
                        'sdp': data.get('sdp'),
                        'candidate': data.get('candidate'),
                        'conversation_id': conversation_id,
                    }
                )

    async def call_signal(self, event):
        await self.send(
            text_data=json.dumps({
                'action': event.get('action'),
                'sender': event.get('sender'),
                'sender_avatar': event.get('sender_avatar'),
                'call_type': event.get('call_type', 'video'),
                'sdp': event.get('sdp'),
                'candidate': event.get('candidate'),
                'conversation_id': event.get('conversation_id'),
            })
        )

    async def presence_update(self, event):
        await self.send(
            text_data=json.dumps({
                'action': 'presence_update',
                'user_id': event['user_id'],
                'username': event['username'],
                'is_online': event['is_online'],
                'last_seen': event['last_seen'],
            })
        )

    async def broadcast_presence(self, is_online):
        last_seen = await self.get_last_seen_display()
        await self.channel_layer.group_send(
            'global_presence',
            {
                'type': 'presence_update',
                'user_id': self.user.id,
                'username': self.user.username,
                'is_online': is_online,
                'last_seen': last_seen,
            }
        )

    @database_sync_to_async
    def set_user_presence(self, is_online):
        try:
            profile = getattr(self.user, 'profile', None)
            if not profile:
                profile = Profile.objects.get_or_create(user=self.user)[0]
            profile.is_online = is_online
            profile.last_seen = timezone.now()
            profile.save(update_fields=['is_online', 'last_seen'])
        except Exception:
            pass

    @database_sync_to_async
    def get_last_seen_display(self):
        try:
            profile = getattr(self.user, 'profile', None)
            if profile:
                return profile.last_seen_display
        except Exception:
            pass
        return "offline"

    @database_sync_to_async
    def get_sender_avatar(self):
        if hasattr(self.user, 'profile') and self.user.profile.avatar:
            try:
                return self.user.profile.avatar.url
            except Exception:
                return None
        return None