import csv
import io
import os
import json
import zipfile
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.files.base import ContentFile
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import DetailView, ListView, TemplateView
from .analyzer import analyze_audio_quality_and_noise
from .models import AudioAnalysis, BatchUpload
from .evaluator import evaluate_predictions_against_ground_truth


class DashboardView(LoginRequiredMixin, TemplateView):
    """Main dashboard displaying system metrics and recent batch processing summary."""
    template_name = "audio_analytics/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["recent_batches"] = BatchUpload.objects.all().order_by("-uploaded_at")[:5]
        context["total_analyzed"] = AudioAnalysis.objects.filter(status=AudioAnalysis.ProcessingStatus.SUCCESS).count()
        context["failed_count"] = AudioAnalysis.objects.filter(status=AudioAnalysis.ProcessingStatus.FAILED).count()
        return context


class BatchUploadView(LoginRequiredMixin, View):

    def post(self, request, *args, **kwargs):
        zip_file = request.FILES.get("zip_file")
        if not zip_file or not zip_file.name.endswith(".zip"):
            return JsonResponse({"error": "Please upload a valid .zip archive."}, status=400)

        batch = BatchUpload.objects.create(zip_file=zip_file, status=BatchUpload.Status.PROCESSING)

        # Collected while iterating the archive; used to run the evaluator
        # against the manifest ground truth once all files are processed.
        predictions = []

        try:
            with zipfile.ZipFile(zip_file, "r") as archive:
                file_list = archive.namelist()

                # Parse Manifest CSV if available
                csv_filename = next((f for f in file_list if f.lower().endswith("labels.csv") or f.lower().endswith("manifest.csv")), None)
                ground_truths = {}
                if csv_filename:
                    with archive.open(csv_filename) as csv_file:
                        reader = csv.DictReader(io.TextIOWrapper(csv_file, encoding="utf-8"))
                        for row in reader:
                            name_key = row.get("name", "").strip()
                            if name_key:
                                ground_truths[name_key] = row.get("result_json", "")

                # Filter down to valid audio members up front (skip dirs, __MACOSX
                # resource forks, and dotfiles) so we can report batch progress.
                audio_members = [
                    m for m in archive.infolist()
                    if not m.is_dir()
                    and not m.filename.startswith("__MACOSX")
                    and "/." not in m.filename
                    and os.path.basename(m.filename).lower().endswith((".wav", ".mp3", ".m4a", ".flac", ".ogg"))
                ]

                batch.total_files = len(audio_members)
                batch.processed_files = 0
                batch.failed_files = 0
                batch.save()

                # Iterate through all valid audio archive contents
                for member in audio_members:
                    # Extract pure filename (strip directory paths inside ZIP)
                    filename = os.path.basename(member.filename)

                    # Per-file exception handling prevents 1 bad file from breaking the whole batch loop
                    try:
                        audio_bytes = archive.read(member)

                        analysis = AudioAnalysis.objects.create(
                            batch=batch,
                            filename=filename,
                            status=AudioAnalysis.ProcessingStatus.PENDING
                        )
                        analysis.audio_file.save(filename, ContentFile(audio_bytes), save=True)

                        # Run process on newly saved media file path
                        metrics = self._process_audio_file(analysis)

                        # Only feed successful predictions into the evaluator
                        if metrics and "error" not in metrics:
                            metrics_with_name = dict(metrics)
                            metrics_with_name["filename"] = filename
                            predictions.append(metrics_with_name)
                            batch.processed_files += 1
                        else:
                            batch.failed_files += 1

                    except Exception as clip_err:
                        # Log failure on individual record so other files continue processing
                        batch.failed_files += 1
                        AudioAnalysis.objects.filter(batch=batch, filename=filename).update(
                            status=AudioAnalysis.ProcessingStatus.FAILED,
                            error_details=str(clip_err)
                        )

                    batch.save()

            # Trigger evaluator if manifest ground-truth labels exist and we have predictions
            if ground_truths and predictions:
                eval_results = evaluate_predictions_against_ground_truth(predictions, ground_truths)
                if "error" not in eval_results:
                    batch.metrics_json = json.dumps(eval_results)

            # Mark batch as completed after iterating all files
            batch.status = BatchUpload.Status.COMPLETED
            batch.save()
            return redirect("batch_detail", pk=batch.pk)

        except Exception as batch_err:
            batch.status = BatchUpload.Status.FAILED
            batch.error_message = str(batch_err)
            batch.save()
            return JsonResponse({"error": f"Failed to process batch: {str(batch_err)}"}, status=500)

    def _process_audio_file(self, analysis: AudioAnalysis):
        """Runs analysis for a single clip, updates/saves the record, and
        returns the raw metrics dict so the caller can feed it to the evaluator."""
        try:
            metrics = analyze_audio_quality_and_noise(analysis.audio_file.path)

            if "error" in metrics:
                analysis.status = AudioAnalysis.ProcessingStatus.FAILED
                analysis.error_details = metrics["error"]
            else:
                # Tone & Intensity from Wav2Vec2
                analysis.emotional_tone = metrics["emotional_tone"]
                analysis.emotional_intensity = metrics["emotional_intensity"]

                # Noise & Quality from Librosa
                analysis.background_noise_present = metrics["background_noise_present"]
                analysis.background_noise_type = metrics["background_noise_type"]
                analysis.background_noise_severity = metrics["background_noise_severity"]
                analysis.audio_quality = metrics["audio_quality"]
                analysis.speaker_overlap_present = metrics["speaker_overlap_present"]
                analysis.long_silence_present = metrics["long_silence_present"]
                analysis.confidence = metrics["confidence"]

                analysis.status = AudioAnalysis.ProcessingStatus.SUCCESS

            analysis.save()
            return metrics
        except Exception as err:
            analysis.status = AudioAnalysis.ProcessingStatus.FAILED
            analysis.error_details = str(err)
            analysis.save()
            return {"error": str(err)}


class BatchListView(LoginRequiredMixin, ListView):
    """List view for reviewing all uploaded batches."""
    model = BatchUpload
    template_name = "audio_analytics/batch_list.html"
    context_object_name = "batches"
    ordering = ["-uploaded_at"]


class BatchDetailView(LoginRequiredMixin, DetailView):
    """Detail view showing individual audio clip predictions and batch progress."""
    model = BatchUpload
    template_name = "audio_analytics/batch_detail.html"
    context_object_name = "batch"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["analyses"] = self.object.analyses.all()
        context["metrics"] = json.loads(self.object.metrics_json) if getattr(self.object, "metrics_json", None) else None
        return context


class ExportBatchResultsView(LoginRequiredMixin, View):
    """Generates and downloads downloadable CSV structured output per requirement specs."""

    def get(self, request, pk, *args, **kwargs):
        batch = get_object_or_404(BatchUpload, pk=pk)

        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="batch_{batch.id}_results.csv"'

        writer = csv.writer(response)
        writer.writerow(["name", "result_json"])

        for analysis in batch.analyses.all():
            if analysis.status == AudioAnalysis.ProcessingStatus.SUCCESS:
                result_payload = json.dumps(analysis.to_dict())
            else:
                result_payload = json.dumps({"error": analysis.error_details})

            writer.writerow([analysis.filename, result_payload])

        return response