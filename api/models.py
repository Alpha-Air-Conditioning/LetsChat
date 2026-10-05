import hashlib
import os
import secrets
import string
from django.db import models


def generate_message_id():
    """Generate a clean 16-character URL-safe alphanumeric message ID."""
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(16))


class StoredFile(models.Model):
    message_id = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        default=generate_message_id
    )
    file = models.FileField(
        upload_to='storage/%Y/%m/%d/'
    )
    filename = models.CharField(
        max_length=255
    )
    file_size = models.BigIntegerField(
        default=0
    )
    mime_type = models.CharField(
        max_length=128,
        default='application/octet-stream'
    )
    file_hash = models.CharField(
        max_length=64,
        db_index=True
    )
    source_url = models.URLField(
        max_length=1024,
        blank=True,
        null=True
    )
    created_at = models.DateTimeField(
        auto_now_add=True
    )
    updated_at = models.DateTimeField(
        auto_now=True
    )

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.filename} ({self.message_id})"

    @staticmethod
    def calculate_hash(file_obj):
        hasher = hashlib.sha256()
        for chunk in file_obj.chunks(chunk_size=65536):
            hasher.update(chunk)
        return hasher.hexdigest()[:16]  # 16-char clean hash token


class StoredText(models.Model):
    message_id = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        default=generate_message_id
    )
    text = models.TextField()
    is_json = models.BooleanField(
        default=False
    )
    json_data = models.JSONField(
        blank=True,
        null=True
    )
    created_at = models.DateTimeField(
        auto_now_add=True
    )

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Text ({self.message_id})"
