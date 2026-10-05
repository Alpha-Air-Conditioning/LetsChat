from django.contrib.auth import views as auth_views
from django.urls import path

from . import views


urlpatterns = [

    # Main chat
    path(
        '',
        views.home,
        name='home'
    ),

    # Login
    path(
        'login/',
        auth_views.LoginView.as_view(
            template_name='chats/login.html'
        ),
        name='login'
    ),

    # Logout
    path(
        'logout/',
        auth_views.LogoutView.as_view(),
        name='logout'
    ),

    # Registration
    path(
        'register/',
        views.register,
        name='register'
    ),

    # Google OAuth 2.0
    path(
        'auth/google/login/',
        views.google_login,
        name='google_login'
    ),
    path(
        'auth/google/callback/',
        views.google_callback,
        name='google_callback'
    ),

    # Settings
    path(
        'settings/',
        views.settings_page,
        name='settings'
    ),

    # Start new chat
    path(
        'new-chat/',
        views.start_chat,
        name='start_chat'
    ),

    # Live search users
    path(
        'search-users/',
        views.search_users,
        name='search_users'
    ),

    # Rename conversation
    path(
        'rename-conversation/<int:conversation_id>/',
        views.rename_conversation,
        name='rename_conversation'
    ),

    # Delete conversation
    path(
        'delete-conversation/<int:conversation_id>/',
        views.delete_conversation,
        name='delete_conversation'
    ),

    # Delete message
    path(
        'delete-message/<int:message_id>/',
        views.delete_message,
        name='delete_message'
    ),

    # Block / Unblock user
    path(
        'block-user/<int:user_id>/',
        views.toggle_block_user,
        name='toggle_block_user'
    ),

    # Upload Voice Note
    path(
        'upload-voice/<int:conversation_id>/',
        views.upload_voice_message,
        name='upload_voice_message'
    ),
]