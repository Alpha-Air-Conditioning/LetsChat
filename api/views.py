import json
import mimetypes
import os
import re
from urllib.parse import urlparse

from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.http import FileResponse, Http404, HttpResponse, JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

import requests
from rest_framework import generics, permissions, status, viewsets
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from chats.models import Conversation, Message
from .models import StoredFile, StoredText
from .permissions import IsConversationMember
from .serializers import (
    ConversationSerializer,
    MessageSerializer,
    RegisterSerializer,
    UserSerializer,
)


def get_base_url(request):
    """Returns absolute base URL including scheme and host."""
    return request.build_absolute_uri('/')[:-1]


# ============================================================
# 1. AUTHENTICATION & CORE CHAT API
# ============================================================

class RegisterAPIView(generics.CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [permissions.AllowAny]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        refresh = RefreshToken.for_user(user)
        return Response({
            'user': UserSerializer(user).data,
            'access': str(refresh.access_token),
            'refresh': str(refresh),
        })


class MeAPIView(generics.RetrieveAPIView):
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return self.request.user


class UserListAPIView(generics.ListAPIView):
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return User.objects.exclude(id=self.request.user.id)


class ConversationViewSet(viewsets.ModelViewSet):
    serializer_class = ConversationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return (
            Conversation.objects
            .filter(participants=self.request.user)
            .prefetch_related('participants')
        )

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class MessageViewSet(viewsets.ModelViewSet):
    serializer_class = MessageSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        queryset = (
            Message.objects
            .filter(conversation__participants=self.request.user)
            .select_related('sender', 'conversation')
        )
        conversation_id = self.request.query_params.get('conversation')
        if conversation_id:
            queryset = queryset.filter(conversation_id=conversation_id)
        return queryset

    def perform_create(self, serializer):
        serializer.save(sender=self.request.user)


# ============================================================
# 2. FILE & STORAGE API (XeonFileBox compatible)
# ============================================================

class FileUploadAPIView(APIView):
    """
    1. File Upload (Multipart Form)
    POST /api/upload
    curl -F "file=@yourfile.png" http://127.0.0.1:8000/api/upload
    """
    permission_classes = [permissions.AllowAny]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, *args, **kwargs):
        file_obj = None
        for key in request.FILES:
            file_obj = request.FILES[key]
            break

        if not file_obj:
            return Response(
                {'error': 'No file uploaded. Use form field "file".'},
                status=status.HTTP_400_BAD_REQUEST
            )

        filename = file_obj.name or 'upload.bin'
        mime_type, _ = mimetypes.guess_type(filename)
        if not mime_type:
            mime_type = file_obj.content_type or 'application/octet-stream'

        file_hash = StoredFile.calculate_hash(file_obj)
        file_obj.seek(0)

        stored_file = StoredFile.objects.create(
            file=file_obj,
            filename=filename,
            file_size=file_obj.size,
            mime_type=mime_type,
            file_hash=file_hash,
        )

        base_url = get_base_url(request)

        return Response({
            'status': 'success',
            'messageID': stored_file.message_id,
            'filename': stored_file.filename,
            'size': stored_file.file_size,
            'mimeType': stored_file.mime_type,
            'hash': stored_file.file_hash,
            'fileUrl': f"{base_url}/file/{stored_file.message_id}?hash={stored_file.file_hash}",
            'streamUrl': f"{base_url}/stream/{stored_file.message_id}?hash={stored_file.file_hash}",
            'downloadUrl': f"{base_url}/file/{stored_file.message_id}?hash={stored_file.file_hash}&d=true",
            'viewUrl': f"{base_url}/view/{stored_file.message_id}?hash={stored_file.file_hash}",
            'createdAt': stored_file.created_at.isoformat(),
        }, status=status.HTTP_201_CREATED)


class RemoteURLUploadAPIView(APIView):
    """
    2. Remote URL Upload (Direct Cloud Transfer)
    POST /api/upload-url
    curl -X POST http://127.0.0.1:8000/api/upload-url -H "Content-Type: application/json" -d '{"url": "https://..."}'
    """
    permission_classes = [permissions.AllowAny]
    parser_classes = [JSONParser, FormParser]

    def post(self, request, *args, **kwargs):
        url = request.data.get('url', '').strip()
        if not url:
            return Response(
                {'error': 'Missing "url" field in payload.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            resp = requests.get(url, stream=True, timeout=30)
            resp.raise_for_status()
        except Exception as e:
            return Response(
                {'error': f'Failed to download file from URL: {str(e)}'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Determine filename
        parsed_url = urlparse(url)
        filename = os.path.basename(parsed_url.path) or 'remote_file.bin'
        if 'content-disposition' in resp.headers:
            cd = resp.headers['content-disposition']
            cd_filenames = re.findall(r'filename=["\']?([^"\';]+)["\']?', cd)
            if cd_filenames:
                filename = cd_filenames[0]

        mime_type = resp.headers.get('Content-Type')
        if not mime_type:
            mime_type, _ = mimetypes.guess_type(filename)
        mime_type = mime_type or 'application/octet-stream'

        file_content = resp.content
        file_obj = ContentFile(file_content, name=filename)

        stored_file = StoredFile(
            filename=filename,
            file_size=len(file_content),
            mime_type=mime_type,
            source_url=url,
        )
        stored_file.file.save(filename, file_obj, save=False)
        stored_file.file_hash = StoredFile.calculate_hash(file_obj)
        stored_file.save()

        base_url = get_base_url(request)

        return Response({
            'status': 'success',
            'messageID': stored_file.message_id,
            'filename': stored_file.filename,
            'size': stored_file.file_size,
            'mimeType': stored_file.mime_type,
            'hash': stored_file.file_hash,
            'sourceUrl': stored_file.source_url,
            'fileUrl': f"{base_url}/file/{stored_file.message_id}?hash={stored_file.file_hash}",
            'streamUrl': f"{base_url}/stream/{stored_file.message_id}?hash={stored_file.file_hash}",
            'downloadUrl': f"{base_url}/file/{stored_file.message_id}?hash={stored_file.file_hash}&d=true",
            'viewUrl': f"{base_url}/view/{stored_file.message_id}?hash={stored_file.file_hash}",
            'createdAt': stored_file.created_at.isoformat(),
        }, status=status.HTTP_201_CREATED)


class StoreTextAPIView(APIView):
    """
    3. Text / JSON Database Store
    POST /api/text
    curl -X POST http://127.0.0.1:8000/api/text -H "Content-Type: application/json" -d '{"text": "payload"}'
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request, *args, **kwargs):
        payload = request.data
        text_content = ''
        is_json = False
        json_data = None

        if isinstance(payload, dict):
            if 'text' in payload and len(payload) == 1 and isinstance(payload['text'], str):
                text_content = payload['text']
            else:
                is_json = True
                json_data = payload
                text_content = json.dumps(payload, indent=2)
        elif isinstance(payload, str):
            text_content = payload
        else:
            text_content = request.body.decode('utf-8', errors='ignore')

        if not text_content:
            return Response(
                {'error': 'Empty payload.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Check if text is valid json string
        if not is_json:
            try:
                parsed = json.loads(text_content)
                if isinstance(parsed, (dict, list)):
                    is_json = True
                    json_data = parsed
            except Exception:
                pass

        stored = StoredText.objects.create(
            text=text_content,
            is_json=is_json,
            json_data=json_data,
        )

        base_url = get_base_url(request)

        return Response({
            'status': 'success',
            'messageID': stored.message_id,
            'dataUrl': f"{base_url}/api/data/{stored.message_id}",
            'rawUrl': f"{base_url}/raw/{stored.message_id}",
            'isJson': stored.is_json,
            'createdAt': stored.created_at.isoformat(),
        }, status=status.HTTP_201_CREATED)


# ============================================================
# 3. DIRECT FILE ACCESS, RANGE STREAMING & VIEWER
# ============================================================

class DirectFileAccessView(View):
    """
    4. Direct File Access & Download
    GET /file/{messageID}?hash={hash}
    GET /file/{messageID}?hash={hash}&d=true
    """
    def get(self, request, message_id, *args, **kwargs):
        stored_file = get_object_or_404(StoredFile, message_id=message_id)

        # Check if force download requested
        is_download = request.GET.get('d', '').lower() in ['true', '1', 'yes']

        response = FileResponse(
            stored_file.file.open('rb'),
            content_type=stored_file.mime_type
        )
        disposition = 'attachment' if is_download else 'inline'
        response['Content-Disposition'] = f'{disposition}; filename="{stored_file.filename}"'
        response['Content-Length'] = stored_file.file_size
        response['Accept-Ranges'] = 'bytes'
        return response


class StreamFileView(View):
    """
    4. HTTP Range Streaming (Audio / Video streaming)
    GET /stream/{messageID}?hash={hash}
    """
    def get(self, request, message_id, *args, **kwargs):
        stored_file = get_object_or_404(StoredFile, message_id=message_id)
        file_path = stored_file.file.path

        if not os.path.exists(file_path):
            raise Http404("File not found on storage.")

        file_size = os.path.getsize(file_path)
        range_header = request.headers.get('Range', '').strip()

        if range_header:
            range_match = re.match(r'bytes=(\d+)-(\d*)', range_header)
            if range_match:
                first_byte = int(range_match.group(1))
                last_byte = int(range_match.group(2)) if range_match.group(2) else file_size - 1
                length = last_byte - first_byte + 1

                def file_iterator(path, offset, size, chunk_size=65536):
                    with open(path, 'rb') as f:
                        f.seek(offset)
                        remaining = size
                        while remaining > 0:
                            read_size = min(remaining, chunk_size)
                            data = f.read(read_size)
                            if not data:
                                break
                            remaining -= len(data)
                            yield data

                response = StreamingHttpResponse(
                    file_iterator(file_path, first_byte, length),
                    status=206,
                    content_type=stored_file.mime_type
                )
                response['Content-Range'] = f'bytes {first_byte}-{last_byte}/{file_size}'
                response['Content-Length'] = str(length)
                response['Accept-Ranges'] = 'bytes'
                return response

        # Standard full stream response
        response = FileResponse(
            open(file_path, 'rb'),
            content_type=stored_file.mime_type
        )
        response['Content-Length'] = str(file_size)
        response['Accept-Ranges'] = 'bytes'
        return response


class ViewerFileView(View):
    """
    4. Web Player / Viewer Page
    GET /view/{messageID}?hash={hash}
    """
    def get(self, request, message_id, *args, **kwargs):
        stored_file = get_object_or_404(StoredFile, message_id=message_id)
        base_url = get_base_url(request)

        file_url = f"{base_url}/file/{stored_file.message_id}?hash={stored_file.file_hash}"
        stream_url = f"{base_url}/stream/{stored_file.message_id}?hash={stored_file.file_hash}"
        download_url = f"{base_url}/file/{stored_file.message_id}?hash={stored_file.file_hash}&d=true"

        is_video = stored_file.mime_type.startswith('video/')
        is_audio = stored_file.mime_type.startswith('audio/')
        is_image = stored_file.mime_type.startswith('image/')
        is_pdf = stored_file.mime_type == 'application/pdf'
        is_text = stored_file.mime_type.startswith('text/') or stored_file.filename.endswith(('.json', '.py', '.js', '.md', '.txt'))

        text_content = ''
        if is_text and stored_file.file_size < 500000:
            try:
                with stored_file.file.open('r') as f:
                    text_content = f.read()
            except Exception:
                pass

        return render(
            request,
            'api/viewer.html',
            {
                'stored_file': stored_file,
                'file_url': file_url,
                'stream_url': stream_url,
                'download_url': download_url,
                'is_video': is_video,
                'is_audio': is_audio,
                'is_image': is_image,
                'is_pdf': is_pdf,
                'is_text': is_text,
                'text_content': text_content,
            }
        )


# ============================================================
# 4. RETRIEVE STORED TEXT / JSON
# ============================================================

class RetrieveDataAPIView(APIView):
    """
    5. Retrieve Stored Text / JSON (JSON response)
    GET /api/data/{messageID}
    """
    permission_classes = [permissions.AllowAny]

    def get(self, request, message_id, *args, **kwargs):
        stored = get_object_or_404(StoredText, message_id=message_id)
        return Response({
            'status': 'success',
            'messageID': stored.message_id,
            'isJson': stored.is_json,
            'data': stored.json_data if stored.is_json else stored.text,
            'createdAt': stored.created_at.isoformat(),
        })


class RetrieveRawTextView(View):
    """
    5. Retrieve Raw Plain Text
    GET /raw/{messageID}
    """
    def get(self, request, message_id, *args, **kwargs):
        stored = get_object_or_404(StoredText, message_id=message_id)
        content_type = 'application/json' if stored.is_json else 'text/plain; charset=utf-8'
        return HttpResponse(stored.text, content_type=content_type)