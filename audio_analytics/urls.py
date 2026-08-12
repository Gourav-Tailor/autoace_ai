from django.urls import path
from .views import (
    DashboardView,
    BatchUploadView,
    BatchListView,
    BatchDetailView,
    ExportBatchResultsView,
)

urlpatterns = [
    # Dashboard route changed to /dashboard/
    path('dashboard/', DashboardView.as_view(), name='dashboard'),
    
    path('upload/', BatchUploadView.as_view(), name='batch_upload'),
    path('batches/', BatchListView.as_view(), name='batch_list'),
    path('batches/<int:pk>/', BatchDetailView.as_view(), name='batch_detail'),
    path('batches/<int:pk>/export/', ExportBatchResultsView.as_view(), name='batch_export'),
]