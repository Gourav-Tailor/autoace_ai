from django.urls import path
from .views import (
    DashboardView,
    BatchUploadView,
    BatchListView,
    BatchDetailView,
    ExportBatchResultsView,
    SignUpView
)
from .api_views import LiveDemoAnalysisView
from django.views.generic import TemplateView

urlpatterns = [
    # Dashboard route changed to /dashboard/
    path('dashboard/', DashboardView.as_view(), name='dashboard'),
    path("signup/", SignUpView.as_view(), name="signup"),
    path("demo/", TemplateView.as_view(template_name="audio_analytics/public_demo.html"), name="public_demo"),
    path("api/demo-analyze/", LiveDemoAnalysisView.as_view(), name="live_demo_api"),
    path('upload/', BatchUploadView.as_view(), name='batch_upload'),
    path('batches/', BatchListView.as_view(), name='batch_list'),
    path('batches/<int:pk>/', BatchDetailView.as_view(), name='batch_detail'),
    path('batches/<int:pk>/export/', ExportBatchResultsView.as_view(), name='batch_export'),
]