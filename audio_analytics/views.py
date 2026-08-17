import csv
import os
import json
import tempfile

from django.contrib.auth import login
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.files import File
from django.core.paginator import Paginator
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View
from django.views.generic import DetailView, ListView, TemplateView

from .forms import SignUpForm
from .models import AudioAnalysis, BatchUpload
from .tasks import process_batch_upload_task


PAGE_SIZE_OPTIONS = (10, 25, 50, 100)
DEFAULT_PAGE_SIZE = 10


def get_page_size(request):
    """Return a safe page size from the query string."""
    try:
        page_size = int(request.GET.get("page_size", DEFAULT_PAGE_SIZE))
    except (TypeError, ValueError):
        return DEFAULT_PAGE_SIZE

    return page_size if page_size in PAGE_SIZE_OPTIONS else DEFAULT_PAGE_SIZE


class SignUpView(View):
    """Handles new user registration."""

    def get(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect("dashboard")
        form = SignUpForm()
        return render(request, "audio_analytics/signup.html", {"form": form})

    def post(self, request, *args, **kwargs):
        form = SignUpForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect("dashboard")
        return render(request, "audio_analytics/signup.html", {"form": form})


class DashboardView(LoginRequiredMixin, TemplateView):
    """Main dashboard displaying system metrics and recent batch processing summary.
    Superusers see metrics/batches for everyone; regular users see only their own."""
    template_name = "audio_analytics/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        if self.request.user.is_superuser:
            batch_qs = BatchUpload.objects.all()
            analysis_qs = AudioAnalysis.objects.all()
        else:
            batch_qs = BatchUpload.objects.filter(user=self.request.user)
            analysis_qs = AudioAnalysis.objects.filter(batch__user=self.request.user)

        context["recent_batches"] = batch_qs.order_by("-uploaded_at")[:5]
        context["total_analyzed"] = analysis_qs.filter(
            status=AudioAnalysis.ProcessingStatus.SUCCESS
        ).count()
        context["failed_count"] = analysis_qs.filter(
            status=AudioAnalysis.ProcessingStatus.FAILED
        ).count()
        return context


class BatchUploadView(LoginRequiredMixin, View):
    """Accepts the uploaded archive, hands it off to a Celery worker, and
    redirects immediately. All per-file analysis, evaluator invocation, and
    batch status/metrics updates now happen asynchronously in
    process_batch_upload_task (see tasks.py)."""

    def post(self, request, *args, **kwargs):
        zip_file = request.FILES.get("zip_file")
        if not zip_file or not zip_file.name.endswith(".zip"):
            return JsonResponse(
                {"error": "Please upload a valid .zip archive."},
                status=400,
            )

        # Save the upload to a temp path on disk so the Celery worker
        # (which may run in a separate process/container) can read it by
        # filesystem path rather than via the in-request file handle.
        temp_dir = tempfile.gettempdir()
        temp_zip_path = os.path.join(temp_dir, f"upload_{zip_file.name}")
        with open(temp_zip_path, "wb+") as destination:
            for chunk in zip_file.chunks():
                destination.write(chunk)

        # Create the batch record up front with a "pending/processing" status,
        # associated with the uploading user; re-open the temp file so the
        # archive is also retained via the model's zip_file field for later
        # reference.
        with open(temp_zip_path, "rb") as saved_zip:
            batch = BatchUpload.objects.create(
                user=request.user,
                zip_file=File(saved_zip, name=zip_file.name),
                status=BatchUpload.Status.PROCESSING,
            )

        # Dispatch async task to background worker.
        process_batch_upload_task.delay(batch.id, temp_zip_path)

        # Immediately redirect user to batch details page.
        return redirect("batch_detail", pk=batch.pk)


class BatchListView(LoginRequiredMixin, ListView):
    """List batches with server-side pagination and selectable page size.
    Superusers see every batch; regular users see only their own."""

    model = BatchUpload
    template_name = "audio_analytics/batch_list.html"
    context_object_name = "batches"
    ordering = ["-uploaded_at"]

    def get_queryset(self):
        qs = super().get_queryset()
        if not self.request.user.is_superuser:
            qs = qs.filter(user=self.request.user)
        return qs.order_by("-uploaded_at", "-id")

    def get_paginate_by(self, queryset):
        return get_page_size(self.request)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_size"] = get_page_size(self.request)
        context["page_size_options"] = PAGE_SIZE_OPTIONS
        return context


class BatchDetailView(LoginRequiredMixin, DetailView):
    """Detail view showing paginated audio clip predictions and a graph for
    exactly the analysis records displayed on the current page.

    Non-superusers can only access batches they own (404 otherwise).
    """

    model = BatchUpload
    template_name = "audio_analytics/batch_detail.html"
    context_object_name = "batch"

    def get_queryset(self):
        qs = super().get_queryset()
        if self.request.user.is_superuser:
            return qs
        return qs.filter(user=self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        page_size = get_page_size(self.request)
        analyses_qs = self.object.analyses.all().order_by("-id")

        paginator = Paginator(analyses_qs, page_size)
        page_number = self.request.GET.get("page", 1)
        analyses_page = paginator.get_page(page_number)

        context["analyses"] = analyses_page.object_list
        context["page_obj"] = analyses_page
        context["paginator"] = paginator
        context["page_size"] = page_size
        context["page_size_options"] = PAGE_SIZE_OPTIONS

        # The graph intentionally uses ONLY the records visible on the
        # current pagination page. This keeps the chart aligned with the
        # table and avoids loading every analysis record for large batches.
        chart_data = []
        for analysis in analyses_page.object_list:
            chart_data.append(
                {
                    "filename": analysis.filename or f"Clip {analysis.pk}",
                    "tone": analysis.emotional_tone or "unknown",
                    "confidence": float(analysis.confidence or 0),
                    "intensity": analysis.emotional_intensity or "-",
                    "noise": bool(analysis.background_noise_present),
                    "noise_severity": analysis.background_noise_severity or "-",
                    "quality": analysis.audio_quality or "-",
                    "overlap": bool(analysis.speaker_overlap_present),
                    "silence": bool(analysis.long_silence_present),
                }
            )

        context["chart_data"] = chart_data
        context["metrics"] = (
            json.loads(self.object.metrics_json)
            if getattr(self.object, "metrics_json", None)
            else None
        )
        return context


class ExportBatchResultsView(LoginRequiredMixin, View):
    """Generates and downloads downloadable CSV structured output per requirement specs."""

    def get(self, request, pk, *args, **kwargs):
        if request.user.is_superuser:
            batch = get_object_or_404(BatchUpload, pk=pk)
        else:
            batch = get_object_or_404(
                BatchUpload,
                pk=pk,
                user=request.user,
            )

        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = (
            f'attachment; filename="batch_{batch.id}_results.csv"'
        )

        writer = csv.writer(response)
        writer.writerow(["name", "result_json"])

        for analysis in batch.analyses.all():
            if analysis.status == AudioAnalysis.ProcessingStatus.SUCCESS:
                result_payload = json.dumps(analysis.to_dict())
            else:
                result_payload = json.dumps({"error": analysis.error_details})

            writer.writerow([analysis.filename, result_payload])

        return response