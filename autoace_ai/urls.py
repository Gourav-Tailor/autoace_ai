from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from audio_analytics import api_v1, device_views


urlpatterns = [
    # Admin Interface
    path("admin/", admin.site.urls),

    # Root URL (http://localhost:8000/) shows Login Page
    path(
        "",
        auth_views.LoginView.as_view(
            template_name="audio_analytics/login.html"
        ),
        name="login",
    ),

    # Logout URL
    path(
        "logout/",
        auth_views.LogoutView.as_view(next_page="login"),
        name="logout",
    ),

    # App Routes (Dashboard, Upload, Batches)
    path("", include("audio_analytics.urls")),

    # Device / ESP32 / mobile APIs
    path(
        "api/v1/sessions/",
        api_v1.SessionInitView.as_view(),
        name="api_v1_session_init",
    ),
    path(
        "api/v1/sessions/<int:batch_id>/chunks/",
        api_v1.SessionChunkView.as_view(),
        name="api_v1_session_chunk",
    ),
    path(
        "api/v1/sessions/<int:batch_id>/finalize/",
        api_v1.SessionFinalizeView.as_view(),
        name="api_v1_session_finalize",
    ),
    path(
        "api/v1/sessions/<int:batch_id>/heartbeat/",
        api_v1.SessionHeartbeatView.as_view(),
        name="api_v1_session_heartbeat",
    ),

    # Mobile: latest analyzed chunk for the authenticated device's
    # most recent recording batch.
    path(
        "api/v1/latest-analysis/",
        api_v1.LatestDeviceAnalysisView.as_view(),
        name="api_v1_latest_analysis",
    ),

    # Browser pages for managing device tokens
    path(
        "devices/",
        device_views.device_tokens_view,
        name="device_tokens",
    ),
    path(
        "devices/<int:device_id>/delete/",
        device_views.delete_device_view,
        name="delete_device",
    ),
]