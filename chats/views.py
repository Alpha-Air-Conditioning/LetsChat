import secrets
import urllib.parse
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.contrib import messages as django_messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
import requests

from .models import BlockedUser, Conversation, Message, Profile


@login_required
def home(request):
    # Ensure profile exists for the current user
    if not hasattr(request.user, 'profile'):
        Profile.objects.get_or_create(user=request.user)

    conversations = list(
        request.user.conversations
        .prefetch_related('participants__profile', 'messages__sender__profile')
        .all()
    )

    # Attach the other participant to each conversation for DP and display
    for conv in conversations:
        other = [p for p in conv.participants.all() if p.id != request.user.id]
        conv.other_participant = other[0] if other else None

    conversation_id = request.GET.get('conversation')
    active_conversation = None
    active_other_participant = None
    is_blocked_by_me = False
    is_blocked_by_other = False
    is_blocked = False
    messages = []

    if conversation_id:
        active_conversation = next(
            (c for c in conversations if str(c.id) == str(conversation_id)),
            None
        )
        if active_conversation:
            active_other_participant = active_conversation.other_participant
            if active_other_participant:
                is_blocked_by_me = BlockedUser.objects.filter(
                    blocker=request.user,
                    blocked=active_other_participant
                ).exists()
                is_blocked_by_other = BlockedUser.objects.filter(
                    blocker=active_other_participant,
                    blocked=request.user
                ).exists()
                is_blocked = is_blocked_by_me or is_blocked_by_other

            messages = (
                active_conversation.messages
                .select_related('sender__profile')
                .all()
            )

    return render(
        request,
        'chats/home.html',
        {
            'conversations': conversations,
            'active_conversation': active_conversation,
            'active_other_participant': active_other_participant,
            'is_blocked_by_me': is_blocked_by_me,
            'is_blocked_by_other': is_blocked_by_other,
            'is_blocked': is_blocked,
            'messages': messages,
            'user_profile': request.user.profile,
        }
    )


@login_required
def start_chat(request):
    """Start or open a chat ONLY by 6-digit Unique ID."""
    if request.method == 'POST':
        other_user_id = request.POST.get('user_id')
        query = request.POST.get('query', '').strip()

        other_user = None

        if other_user_id:
            other_user = get_object_or_404(User, id=other_user_id)
        elif query:
            clean_query = query.lstrip('#').strip()
            # Identify exclusively by 6-digit Unique ID
            other_user = (
                User.objects
                .filter(profile__unique_number=clean_query)
                .exclude(id=request.user.id)
                .first()
            )

        if other_user:
            # Check if 1-on-1 conversation already exists
            existing_conv = (
                Conversation.objects
                .filter(participants=request.user)
                .filter(participants=other_user)
                .first()
            )
            if existing_conv:
                return redirect(f'/?conversation={existing_conv.id}')

            # Create new direct conversation
            conv = Conversation.objects.create(
                name=f"{other_user.username}",
                created_by=request.user
            )
            conv.participants.add(request.user, other_user)
            return redirect(f'/?conversation={conv.id}')
        else:
            if query:
                django_messages.error(
                    request,
                    f'No member found with Unique ID "#{query.lstrip("#")}". Please enter a valid 6-digit ID.'
                )

    return redirect('home')


@login_required
def search_users(request):
    """Live search endpoint: Allows finding users by username, Unique ID, or email."""
    q = request.GET.get('q', '').strip().lstrip('#').lstrip('@')
    if not q:
        return JsonResponse({'users': []})

    users = (
        User.objects
        .exclude(id=request.user.id)
        .select_related('profile')
        .filter(
            Q(username__icontains=q) |
            Q(profile__unique_number__icontains=q) |
            Q(email__icontains=q)
        )[:15]
    )

    data = [
        {
            'id': u.id,
            'username': u.username,
            'email': u.email,
            'unique_number': getattr(u.profile, 'unique_number', str(u.id)),
            'avatar_url': u.profile.avatar.url if (hasattr(u, 'profile') and u.profile.avatar) else None,
        }
        for u in users
    ]
    return JsonResponse({'users': data})



def register(request):
    if request.user.is_authenticated:
        return redirect('home')

    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            # Profile is automatically generated via post_save signal
            login(request, user)
            return redirect('home')
    else:
        form = UserCreationForm()

    return render(
        request,
        'chats/register.html',
        {'form': form}
    )


@login_required
def settings_page(request):
    if not hasattr(request.user, 'profile'):
        Profile.objects.get_or_create(user=request.user)

    profile = request.user.profile

    if request.method == 'POST':
        # Remove avatar action
        if 'remove_avatar' in request.POST:
            if profile.avatar:
                profile.avatar.delete(save=False)
                profile.avatar = None
                profile.save()
                django_messages.success(request, 'Profile picture removed.')
                return redirect('settings')

        # Upload new avatar DP
        if 'avatar' in request.FILES:
            avatar_file = request.FILES['avatar']
            if avatar_file.size > 5 * 1024 * 1024:
                django_messages.error(request, 'Image file too large (Max 5MB).')
            else:
                profile.avatar = avatar_file
                profile.save()
                django_messages.success(request, 'Profile picture (DP) updated successfully!')
                return redirect('settings')

        # Update username and/or email
        new_username = request.POST.get('username', '').strip()
        email = request.POST.get('email', '').strip()
        updated = False

        if new_username and new_username != request.user.username:
            if len(new_username) < 2:
                django_messages.error(request, 'Username must be at least 2 characters long.')
                return redirect('settings')
            if User.objects.filter(username__iexact=new_username).exclude(id=request.user.id).exists():
                django_messages.error(request, f'Username "{new_username}" is already taken. Please choose another.')
                return redirect('settings')
            request.user.username = new_username
            updated = True

        if email != request.user.email:
            request.user.email = email
            updated = True

        if updated:
            request.user.save()
            django_messages.success(request, 'Profile details updated successfully!')
            return redirect('settings')

    return render(
        request,
        'chats/settings.html',
        {
            'user_profile': profile
        }
    )


@login_required
def rename_conversation(request, conversation_id):
    if request.method == 'POST':
        conversation = get_object_or_404(Conversation, id=conversation_id, participants=request.user)
        new_name = request.POST.get('name', '').strip()
        if new_name:
            conversation.name = new_name
            conversation.save()
            django_messages.success(request, 'Chat name updated.')
        return redirect(f'/?conversation={conversation.id}')
    return redirect('home')


@login_required
def delete_conversation(request, conversation_id):
    if request.method == 'POST':
        conversation = get_object_or_404(Conversation, id=conversation_id, participants=request.user)
        conversation.delete()
        django_messages.success(request, 'Conversation deleted.')
    return redirect('home')


@login_required
def delete_message(request, message_id):
    if request.method == 'POST':
        message = get_object_or_404(Message, id=message_id, sender=request.user)
        conv_id = message.conversation_id
        message.delete()
        if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.content_type == 'application/json':
            return JsonResponse({'status': 'success', 'message_id': message_id})
        django_messages.success(request, 'Message deleted.')
        return redirect(f'/?conversation={conv_id}')
    return redirect('home')


@login_required
def toggle_block_user(request, user_id):
    """Block or unblock a user."""
    if request.method == 'POST':
        target_user = get_object_or_404(User, id=user_id)
        if target_user.id == request.user.id:
            django_messages.error(request, 'You cannot block yourself.')
            return redirect('home')

        blocked_entry = BlockedUser.objects.filter(
            blocker=request.user,
            blocked=target_user
        ).first()

        conversation_id = request.POST.get('conversation_id')

        if blocked_entry:
            blocked_entry.delete()
            django_messages.success(request, f'Unblocked @{target_user.username}.')
        else:
            BlockedUser.objects.create(
                blocker=request.user,
                blocked=target_user
            )
            django_messages.warning(request, f'Blocked @{target_user.username}. You will not receive or send messages with them.')

        if conversation_id:
            return redirect(f'/?conversation={conversation_id}')

    return redirect('home')


def google_login(request):
    """Initiates Google OAuth 2.0 authorization flow."""
    if not getattr(settings, 'GOOGLE_CLIENT_ID', '') or not getattr(settings, 'GOOGLE_CLIENT_SECRET', ''):
        django_messages.info(
            request,
            'Google Sign-In is ready! To connect live Google accounts, please set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in your .env file.'
        )
        return redirect('login')

    state = secrets.token_urlsafe(32)
    request.session['google_oauth_state'] = state
    request.session['google_oauth_next'] = request.GET.get('next', 'home')

    redirect_uri = request.build_absolute_uri(reverse('google_callback'))
    params = {
        'client_id': settings.GOOGLE_CLIENT_ID,
        'redirect_uri': redirect_uri,
        'response_type': 'code',
        'scope': 'openid email profile',
        'access_type': 'offline',
        'state': state,
        'prompt': 'select_account',
    }
    auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?{urllib.parse.urlencode(params)}"
    return redirect(auth_url)


def google_callback(request):
    """Handles callback from Google OAuth 2.0."""
    error = request.GET.get('error')
    if error:
        django_messages.warning(request, f'Google sign-in was cancelled ({error}).')
        return redirect('login')

    code = request.GET.get('code')
    state = request.GET.get('state')
    session_state = request.session.get('google_oauth_state')

    if not code or not state or state != session_state:
        django_messages.error(request, 'Invalid or expired Google login session. Please try again.')
        return redirect('login')

    request.session.pop('google_oauth_state', None)
    redirect_uri = request.build_absolute_uri(reverse('google_callback'))

    token_url = 'https://oauth2.googleapis.com/token'
    token_data = {
        'code': code,
        'client_id': settings.GOOGLE_CLIENT_ID,
        'client_secret': settings.GOOGLE_CLIENT_SECRET,
        'redirect_uri': redirect_uri,
        'grant_type': 'authorization_code',
    }

    try:
        token_res = requests.post(token_url, data=token_data, timeout=10)
        token_json = token_res.json()
    except Exception:
        django_messages.error(request, 'Could not connect to Google servers. Please try again.')
        return redirect('login')

    access_token = token_json.get('access_token')
    if not access_token:
        error_msg = token_json.get('error_description') or token_json.get('error', 'Token exchange failed.')
        django_messages.error(request, f'Google authorization failed: {error_msg}')
        return redirect('login')

    try:
        userinfo_res = requests.get(
            'https://www.googleapis.com/oauth2/v3/userinfo',
            headers={'Authorization': f'Bearer {access_token}'},
            timeout=10
        )
        userinfo = userinfo_res.json()
    except Exception:
        django_messages.error(request, 'Failed to fetch user profile from Google.')
        return redirect('login')

    google_email = userinfo.get('email', '').strip().lower()
    google_name = userinfo.get('name') or userinfo.get('given_name') or ''
    google_picture = userinfo.get('picture')

    if not google_email:
        django_messages.error(request, 'Google account did not provide a valid email address.')
        return redirect('login')

    # Find existing user by email
    user = User.objects.filter(email__iexact=google_email).first()

    if not user:
        # Create username based on email
        base_username = google_email.split('@')[0]
        clean_username = "".join(c for c in base_username if c.isalnum() or c in '._-')
        if len(clean_username) < 2:
            clean_username = 'user'

        unique_username = clean_username
        suffix = 1
        while User.objects.filter(username__iexact=unique_username).exists():
            unique_username = f"{clean_username}_{suffix}"
            suffix += 1

        user = User.objects.create_user(
            username=unique_username,
            email=google_email
        )
        user.set_unusable_password()
        if google_name:
            user.first_name = google_name[:30]
        user.save()

    # Ensure profile exists
    if not hasattr(user, 'profile'):
        Profile.objects.get_or_create(user=user)

    # Attach Google avatar if user has none
    if google_picture and not user.profile.avatar:
        try:
            img_res = requests.get(google_picture, timeout=5)
            if img_res.status_code == 200:
                user.profile.avatar.save(
                    f"{user.username}_google_dp.jpg",
                    ContentFile(img_res.content),
                    save=True
                )
        except Exception:
            pass

    # Log the user into session
    login(request, user, backend='django.contrib.auth.backends.ModelBackend')
    django_messages.success(request, f'Successfully signed in with Google as @{user.username}!')

    next_url = request.session.pop('google_oauth_next', None)
    return redirect(next_url or 'home')


@csrf_exempt
@login_required
def upload_voice_message(request, conversation_id):
    """Uploads a recorded voice note and broadcasts it via WebSocket."""
    if request.method == 'POST':
        conversation = get_object_or_404(Conversation, id=conversation_id, participants=request.user)

        # Check if conversation is blocked
        participants = list(conversation.participants.all())
        if len(participants) >= 2:
            p1, p2 = participants[0], participants[1]
            if BlockedUser.objects.filter((Q(blocker=p1, blocked=p2) | Q(blocker=p2, blocked=p1))).exists():
                return JsonResponse({'error': 'This conversation is blocked.'}, status=403)

        audio_file = request.FILES.get('audio')
        if not audio_file:
            return JsonResponse({'error': 'No audio recorded.'}, status=400)

        message = Message.objects.create(
            conversation=conversation,
            sender=request.user,
            content='🎙️ Voice Message',
            audio_file=audio_file
        )
        conversation.save(update_fields=['updated_at'])

        avatar_url = None
        if hasattr(request.user, 'profile') and request.user.profile.avatar:
            try:
                avatar_url = request.user.profile.avatar.url
            except Exception:
                pass

        # Broadcast real-time over WebSocket
        channel_layer = get_channel_layer()
        if channel_layer:
            async_to_sync(channel_layer.group_send)(
                f'chat_{conversation.id}',
                {
                    'type': 'chat_message',
                    'id': message.id,
                    'message': message.content,
                    'audio_url': message.audio_file.url,
                    'sender': request.user.username,
                    'sender_avatar': avatar_url,
                    'created_at': message.created_at.isoformat(),
                }
            )

        return JsonResponse({
            'status': 'success',
            'id': message.id,
            'audio_url': message.audio_file.url,
            'created_at': message.created_at.isoformat(),
        })

    return JsonResponse({'error': 'Invalid request method.'}, status=405)