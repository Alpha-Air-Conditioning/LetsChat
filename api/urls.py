from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register('conversations', views.ConversationViewSet, basename='conversation')
router.register('messages', views.MessageViewSet, basename='message')

urlpatterns = [
    # Auth & Users
    path('auth/register/', views.RegisterAPIView.as_view(), name='api_register'),
    path('auth/me/', views.MeAPIView.as_view(), name='api_me'),
    path('users/', views.UserListAPIView.as_view(), name='api_users'),

    # 1. File Upload (Multipart Form)
    path('upload', views.FileUploadAPIView.as_view(), name='api_upload_raw'),
    path('upload/', views.FileUploadAPIView.as_view(), name='api_upload'),

    # 2. Remote URL Upload (Direct Cloud Transfer)
    path('upload-url', views.RemoteURLUploadAPIView.as_view(), name='api_upload_url_raw'),
    path('upload-url/', views.RemoteURLUploadAPIView.as_view(), name='api_upload_url'),

    # 3. Text / JSON Database Store
    path('text', views.StoreTextAPIView.as_view(), name='api_text_raw'),
    path('text/', views.StoreTextAPIView.as_view(), name='api_text'),

    # 5. Retrieve Stored Text / JSON (JSON response)
    path('data/<str:message_id>', views.RetrieveDataAPIView.as_view(), name='api_data_raw'),
    path('data/<str:message_id>/', views.RetrieveDataAPIView.as_view(), name='api_data'),

    # Conversations and Messages
    path('', include(router.urls)),
]
