import os

os.environ.setdefault(
    'DJANGO_SETTINGS_MODULE',
    'config.settings'
)

from django.conf import settings
from django.core.asgi import get_asgi_application
from django.contrib.staticfiles.handlers import ASGIStaticFilesHandler

django_application = get_asgi_application()
if settings.DEBUG:
    django_application = ASGIStaticFilesHandler(django_application)

from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import AllowedHostsOriginValidator

from chats.routing import websocket_urlpatterns


application = ProtocolTypeRouter({

    'http': django_application,

    'websocket':

        AuthMiddlewareStack(

            URLRouter(
                websocket_urlpatterns
            )

        ),

})