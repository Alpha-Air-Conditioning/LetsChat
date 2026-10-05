from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
)

from api import views as api_views

urlpatterns = [

    # Django admin
    path(
        'admin/',
        admin.site.urls
    ),

    # Website
    path(
        '',
        include('chats.urls')
    ),

    # REST API
    path(
        'api/',
        include('api.urls')
    ),

    # JWT
    path(
        'api/auth/token/',
        TokenObtainPairView.as_view(),
        name='token'
    ),

    path(
        'api/auth/token/refresh/',
        TokenRefreshView.as_view(),
        name='token_refresh'
    ),

    # 4. Direct File Access & Download
    path('file/<str:message_id>', api_views.DirectFileAccessView.as_view(), name='file_access_raw'),
    path('file/<str:message_id>/', api_views.DirectFileAccessView.as_view(), name='file_access'),

    # 4. Range Streaming
    path('stream/<str:message_id>', api_views.StreamFileView.as_view(), name='file_stream_raw'),
    path('stream/<str:message_id>/', api_views.StreamFileView.as_view(), name='file_stream'),

    # 4. Web Player / Viewer
    path('view/<str:message_id>', api_views.ViewerFileView.as_view(), name='file_view_raw'),
    path('view/<str:message_id>/', api_views.ViewerFileView.as_view(), name='file_view'),

    # 5. Raw Plain Text
    path('raw/<str:message_id>', api_views.RetrieveRawTextView.as_view(), name='text_raw_raw'),
    path('raw/<str:message_id>/', api_views.RetrieveRawTextView.as_view(), name='text_raw'),

]

from django.views.static import serve
from django.urls import re_path

urlpatterns += [
    re_path(r'^media/(?P<path>.*)$', serve, {'document_root': settings.MEDIA_ROOT}),
]
if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATICFILES_DIRS[0])