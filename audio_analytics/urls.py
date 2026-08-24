from django.urls import path
from django.views.generic import TemplateView

from .api_views import LiveDemoAnalysisView, LongRecorderBatchView
from .billing_views import BillingView
from .mobile_api import (
    MobileDeviceLatestAnalysisView,
    MobileDevicesView,
    MobileLoginView,
    MobileLogoutView,
)
from .views import (
    BatchDetailView,
    BatchListView,
    BatchUploadView,
    DashboardView,
    ExportBatchResultsView,
    SignUpView,
)

urlpatterns = [
    path("dashboard/", DashboardView.as_view(), name="dashboard"),
    path("billing/", BillingView.as_view(), name="billing"),
    path("signup/", SignUpView.as_view(), name="signup"),
    path(
        "demo/",
        TemplateView.as_view(template_name="audio_analytics/public_demo.html"),
        name="public_demo",
    ),
    path("api/demo-analyze/", LiveDemoAnalysisView.as_view(), name="live_demo_api"),
    path("upload/", BatchUploadView.as_view(), name="batch_upload"),
    path("batches/", BatchListView.as_view(), name="batch_list"),
    path("batches/<int:pk>/", BatchDetailView.as_view(), name="batch_detail"),
    path(
        "batches/<int:pk>/export/",
        ExportBatchResultsView.as_view(),
        name="batch_export",
    ),
    path(
        "long-recorder/",
        TemplateView.as_view(template_name="audio_analytics/long_recorder.html"),
        name="long_recorder",
    ),
    path(
        "api/long-recorder/", LongRecorderBatchView.as_view(), name="long_recorder_api"
    ),
    path(
        "api/v1/mobile/login/",
        MobileLoginView.as_view(),
        name="mobile_login",
    ),
    path(
        "api/v1/mobile/logout/",
        MobileLogoutView.as_view(),
        name="mobile_logout",
    ),
    path(
        "api/v1/mobile/devices/",
        MobileDevicesView.as_view(),
        name="mobile_devices",
    ),
    path(
        "api/v1/mobile/devices/<int:device_id>/latest-analysis/",
        MobileDeviceLatestAnalysisView.as_view(),
        name="mobile_device_latest_analysis",
    ),
]
