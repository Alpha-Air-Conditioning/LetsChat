from unittest.mock import MagicMock, patch
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import Conversation, Message, Profile


class ChatViewTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            password='testpassword123'
        )
        self.other_user = User.objects.create_user(
            username='otheruser',
            password='testpassword123'
        )
        self.conversation = Conversation.objects.create(
            name='General Chat',
            created_by=self.user
        )
        self.conversation.participants.add(self.user, self.other_user)
        self.message = Message.objects.create(
            conversation=self.conversation,
            sender=self.user,
            content='Hello world!'
        )

    def test_unique_number_generation(self):
        self.assertTrue(hasattr(self.user, 'profile'))
        self.assertEqual(len(self.user.profile.unique_number), 6)
        self.assertTrue(self.user.profile.unique_number.isdigit())

    def test_start_chat_by_unique_number(self):
        self.client.login(username='testuser', password='testpassword123')
        target_number = self.other_user.profile.unique_number
        response = self.client.post(reverse('start_chat'), {'query': f'#{target_number}'})
        self.assertEqual(response.status_code, 302)
        self.assertIn('conversation=', response.url)

    def test_live_search_users_endpoint(self):
        self.client.login(username='testuser', password='testpassword123')
        response = self.client.get(reverse('search_users') + f'?q={self.other_user.profile.unique_number}')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data['users']), 1)
        self.assertEqual(data['users'][0]['username'], 'otheruser')

    def test_home_unauthenticated_redirects(self):
        response = self.client.get(reverse('home'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response.url)

    def test_home_authenticated(self):
        self.client.login(username='testuser', password='testpassword123')
        response = self.client.get(reverse('home'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'General Chat')

    def test_home_with_active_conversation(self):
        self.client.login(username='testuser', password='testpassword123')
        response = self.client.get(reverse('home') + f'?conversation={self.conversation.id}')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Hello world!')

    def test_register_view_get(self):
        response = self.client.get(reverse('register'))
        self.assertEqual(response.status_code, 200)

    def test_settings_view_authenticated(self):
        self.client.login(username='testuser', password='testpassword123')
        response = self.client.get(reverse('settings'))
        self.assertEqual(response.status_code, 200)

    def test_delete_message(self):
        self.client.login(username='testuser', password='testpassword123')
        msg_id = self.message.id
        response = self.client.post(reverse('delete_message', kwargs={'message_id': msg_id}))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Message.objects.filter(id=msg_id).exists())

    def test_delete_message_ajax(self):
        self.client.login(username='testuser', password='testpassword123')
        msg = Message.objects.create(conversation=self.conversation, sender=self.user, content='To delete')
        response = self.client.post(
            reverse('delete_message', kwargs={'message_id': msg.id}),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'success')
        self.assertFalse(Message.objects.filter(id=msg.id).exists())

    def test_delete_conversation(self):
        self.client.login(username='testuser', password='testpassword123')
        conv_id = self.conversation.id
        response = self.client.post(reverse('delete_conversation', kwargs={'conversation_id': conv_id}))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Conversation.objects.filter(id=conv_id).exists())

    def test_toggle_block_user(self):
        self.client.login(username='testuser', password='testpassword123')
        # Block other_user
        response = self.client.post(reverse('toggle_block_user', kwargs={'user_id': self.other_user.id}))
        self.assertEqual(response.status_code, 302)
        from .models import BlockedUser
        self.assertTrue(BlockedUser.objects.filter(blocker=self.user, blocked=self.other_user).exists())

        # Unblock other_user
        response = self.client.post(reverse('toggle_block_user', kwargs={'user_id': self.other_user.id}))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(BlockedUser.objects.filter(blocker=self.user, blocked=self.other_user).exists())

    def test_search_users_privacy_when_empty(self):
        self.client.login(username='testuser', password='testpassword123')
        response = self.client.get(reverse('search_users'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['users'], [])

    def test_settings_update_username_and_email(self):
        self.client.login(username='testuser', password='testpassword123')
        response = self.client.post(reverse('settings'), {
            'username': 'newcoolname',
            'email': 'newemail@example.com'
        })
        self.assertEqual(response.status_code, 302)
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, 'newcoolname')
        self.assertEqual(self.user.email, 'newemail@example.com')

    def test_settings_duplicate_username_rejected(self):
        self.client.login(username='testuser', password='testpassword123')
        response = self.client.post(reverse('settings'), {
            'username': 'otheruser',
            'email': 'test@example.com'
        })
        self.assertEqual(response.status_code, 302)
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, 'testuser')

    def test_rename_conversation(self):
        self.client.login(username='testuser', password='testpassword123')
        response = self.client.post(
            reverse('rename_conversation', kwargs={'conversation_id': self.conversation.id}),
            {'name': 'Renamed Project Chat'}
        )
        self.assertEqual(response.status_code, 302)
        self.conversation.refresh_from_db()
        self.assertEqual(self.conversation.name, 'Renamed Project Chat')

    def test_google_login_unconfigured_redirects(self):
        with self.settings(GOOGLE_CLIENT_ID='', GOOGLE_CLIENT_SECRET=''):
            response = self.client.get(reverse('google_login'))
            self.assertEqual(response.status_code, 302)
            self.assertIn('/login/', response.url)

    def test_google_login_configured_redirects_to_google(self):
        with self.settings(GOOGLE_CLIENT_ID='test-client-id.apps.googleusercontent.com', GOOGLE_CLIENT_SECRET='test-secret'):
            response = self.client.get(reverse('google_login'))
            self.assertEqual(response.status_code, 302)
            self.assertIn('accounts.google.com/o/oauth2/v2/auth', response.url)
            self.assertIn('client_id=test-client-id.apps.googleusercontent.com', response.url)
            session = self.client.session
            self.assertTrue('google_oauth_state' in session)

    def test_google_callback_invalid_state(self):
        with self.settings(GOOGLE_CLIENT_ID='test-id', GOOGLE_CLIENT_SECRET='test-secret'):
            session = self.client.session
            session['google_oauth_state'] = 'correct_state'
            session.save()

            response = self.client.get(reverse('google_callback') + '?state=wrong_state&code=test_code')
            self.assertEqual(response.status_code, 302)
            self.assertIn('/login/', response.url)

    @patch('requests.get')
    @patch('requests.post')
    def test_google_callback_success_creates_user(self, mock_post, mock_get):
        with self.settings(GOOGLE_CLIENT_ID='test-id', GOOGLE_CLIENT_SECRET='test-secret'):
            # Setup session state
            session = self.client.session
            session['google_oauth_state'] = 'valid_state'
            session.save()

            # Mock token exchange
            mock_token_res = MagicMock()
            mock_token_res.json.return_value = {'access_token': 'fake_access_token'}
            mock_post.return_value = mock_token_res

            # Mock userinfo response
            mock_userinfo_res = MagicMock()
            mock_userinfo_res.json.return_value = {
                'email': 'newgoogleuser@example.com',
                'name': 'Google Hero',
                'picture': None
            }
            mock_get.return_value = mock_userinfo_res

            response = self.client.get(reverse('google_callback') + '?state=valid_state&code=valid_code')
            self.assertEqual(response.status_code, 302)

            # Check that new user was created
            created_user = User.objects.filter(email='newgoogleuser@example.com').first()
            self.assertIsNotNone(created_user)
            self.assertTrue(hasattr(created_user, 'profile'))
            self.assertEqual(len(created_user.profile.unique_number), 6)

    def test_upload_voice_message_success(self):
        self.client.login(username='testuser', password='testpassword123')
        fake_audio = SimpleUploadedFile('sample_note.webm', b'fake-audio-content', content_type='audio/webm')
        response = self.client.post(
            reverse('upload_voice_message', kwargs={'conversation_id': self.conversation.id}),
            {'audio': fake_audio}
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['status'], 'success')
        self.assertTrue('audio_url' in data)

        created_msg = Message.objects.get(id=data['id'])
        self.assertIsNotNone(created_msg.audio_file)
        self.assertEqual(created_msg.sender, self.user)

    def test_upload_voice_message_no_audio_rejected(self):
        self.client.login(username='testuser', password='testpassword123')
        response = self.client.post(
            reverse('upload_voice_message', kwargs={'conversation_id': self.conversation.id}),
            {}
        )
        self.assertEqual(response.status_code, 400)