from django.contrib import admin

from .models import Conversation, Message, Profile


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'user',
        'unique_number',
    )
    search_fields = (
        'user__username',
        'user__email',
        'unique_number',
    )


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):

    list_display = (
        'id',
        'name',
        'created_by',
        'created_at',
    )

    search_fields = (
        'name',
    )


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):

    list_display = (
        'id',
        'conversation',
        'sender',
        'created_at',
    )

    search_fields = (
        'content',
        'sender__username',
    )