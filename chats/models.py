import random
import string
from django.conf import settings
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver


def generate_unique_number():
    """Generates a random 6-digit unique identifier number, e.g. '849201'."""
    while True:
        code = ''.join(random.choices(string.digits, k=6))
        # Ensure code is unique across all user profiles
        if not Profile.objects.filter(unique_number=code).exists():
            return code


class Profile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='profile'
    )
    unique_number = models.CharField(
        max_length=12,
        unique=True,
        db_index=True,
        default=generate_unique_number
    )
    avatar = models.ImageField(
        upload_to='avatars/',
        null=True,
        blank=True
    )
    is_online = models.BooleanField(
        default=False
    )
    last_seen = models.DateTimeField(
        null=True,
        blank=True
    )

    @property
    def last_seen_display(self):
        if self.is_online:
            return "online"
        if not self.last_seen:
            return "offline"
        from django.utils import timezone
        diff = timezone.now() - self.last_seen
        seconds = int(diff.total_seconds())
        if seconds < 60:
            return "Last seen just now"
        elif seconds < 3600:
            mins = max(1, seconds // 60)
            return f"Last seen {mins}m ago"
        elif seconds < 86400:
            hours = max(1, seconds // 3600)
            return f"Last seen {hours}h ago"
        elif seconds < 172800:
            return f"Last seen yesterday at {self.last_seen.strftime('%I:%M %p').lstrip('0')}"
        elif seconds < 604800:
            days = max(1, seconds // 86400)
            return f"Last seen {days}d ago"
        else:
            return f"Last seen {self.last_seen.strftime('%b %d')}"

    def __str__(self):
        return f"{self.user.username} (#{self.unique_number})"



@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_or_update_user_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.get_or_create(user=instance)
    else:
        if not hasattr(instance, 'profile'):
            Profile.objects.get_or_create(user=instance)


class Conversation(models.Model):

    name = models.CharField(
        max_length=255
    )

    participants = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name='conversations'
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='created_conversations'
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )


    class Meta:

        ordering = [
            '-updated_at'
        ]


    def __str__(self):

        return self.name


class Message(models.Model):

    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name='messages'
    )

    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='sent_messages'
    )

    content = models.TextField(
        blank=True,
        default=''
    )

    audio_file = models.FileField(
        upload_to='voice_notes/',
        null=True,
        blank=True
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    is_edited = models.BooleanField(
        default=False
    )

    is_deleted = models.BooleanField(
        default=False
    )

    is_read = models.BooleanField(
        default=False
    )


    class Meta:

        ordering = [
            'created_at'
        ]


    def __str__(self):

        return (
            f'{self.sender.username}: '
            f'{self.content[:50]}'
        )


class BlockedUser(models.Model):
    blocker = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='blocking'
    )
    blocked = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='blocked_by'
    )
    created_at = models.DateTimeField(
        auto_now_add=True
    )

    class Meta:
        unique_together = ('blocker', 'blocked')

    def __str__(self):
        return f"{self.blocker.username} blocked {self.blocked.username}"