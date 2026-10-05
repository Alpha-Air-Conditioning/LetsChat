import io
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from chats.models import Conversation, Message
from .models import StoredFile, StoredText


class APITests(APITestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            username='apiuser',
            password='Password123!',
            email='apiuser@example.com'
        )
        self.other_user = User.objects.create_user(
            username='apiother',
            password='Password123!',
            email='apiother@example.com'
        )
        self.conversation = Conversation.objects.create(
            name='Dev Team',
            created_by=self.user
        )
        self.conversation.participants.add(self.user, self.other_user)

        refresh = RefreshToken.for_user(self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {refresh.access_token}')

    def test_get_me(self):
        url = reverse('api_me')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['username'], 'apiuser')

    def test_list_conversations(self):
        url = reverse('conversation-list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['name'], 'Dev Team')

    def test_create_message(self):
        url = reverse('message-list')
        response = self.client.post(url, {
            'conversation': self.conversation.id,
            'content': 'Hello from REST API'
        })
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Message.objects.filter(conversation=self.conversation).count(), 1)

    # 1. File Upload
    def test_file_upload_multipart(self):
        file_content = b'Hello XeonFileBox storage test content'
        upload_file = SimpleUploadedFile(
            'testfile.txt',
            file_content,
            content_type='text/plain'
        )
        url = reverse('api_upload')
        response = self.client.post(url, {'file': upload_file}, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['status'], 'success')
        self.assertIn('messageID', response.data)
        self.assertIn('fileUrl', response.data)
        self.assertIn('streamUrl', response.data)

        # 4. Direct File Access
        msg_id = response.data['messageID']
        file_access_url = reverse('file_access', kwargs={'message_id': msg_id})
        get_resp = self.client.get(file_access_url)
        self.assertEqual(get_resp.status_code, 200)

        # 4. Range Streaming
        stream_url = reverse('file_stream', kwargs={'message_id': msg_id})
        stream_resp = self.client.get(stream_url, HTTP_RANGE='bytes=0-10')
        self.assertEqual(stream_resp.status_code, 206)

        # 4. Web Viewer
        view_url = reverse('file_view', kwargs={'message_id': msg_id})
        view_resp = self.client.get(view_url)
        self.assertEqual(view_resp.status_code, 200)

    # 3. Text / JSON Database Store & Retrieve
    def test_text_and_json_store_and_retrieve(self):
        url = reverse('api_text')
        response = self.client.post(url, {'key': 'value', 'message': 'test json'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.data['isJson'])
        msg_id = response.data['messageID']

        # 5. Retrieve JSON
        data_url = reverse('api_data', kwargs={'message_id': msg_id})
        data_resp = self.client.get(data_url)
        self.assertEqual(data_resp.status_code, 200)
        self.assertEqual(data_resp.data['data']['key'], 'value')

        # 5. Retrieve Raw
        raw_url = reverse('text_raw', kwargs={'message_id': msg_id})
        raw_resp = self.client.get(raw_url)
        self.assertEqual(raw_resp.status_code, 200)
        self.assertIn(b'value', raw_resp.content)