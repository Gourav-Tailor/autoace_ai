import csv
import io
import json
import os
import zipfile
from celery import shared_task
from .models import BatchUpload, AudioAnalysis
from .analyzer import analyze_audio_clip
from .evaluator import evaluate_predictions_against_ground_truth


@shared_task
def process_batch_upload_task(batch_id, zip_file_path):
    batch = None
    try:
        batch = BatchUpload.objects.get(id=batch_id)
        batch.status = BatchUpload.Status.PROCESSING
        batch.save()

        ground_truths = {}
        predictions = []

        with zipfile.ZipFile(zip_file_path, "r") as archive:
            file_list = archive.namelist()

            # 1. Parse labels.csv manifest
            csv_filename = next(
                (f for f in file_list if f.lower().endswith("labels.csv") or f.lower().endswith("manifest.csv")),
                None
            )
            if csv_filename:
                with archive.open(csv_filename) as csv_file:
                    reader = csv.DictReader(io.TextIOWrapper(csv_file, encoding="utf-8"))
                    for row in reader:
                        filename = row.get("name", "").strip()
                        gt_json = row.get("result_json", "").strip()
                        if filename:
                            ground_truths[filename] = gt_json

            # 2. Extract and analyze audio files. Skip directories, __MACOSX
            # resource forks, and dotfiles the same way the original
            # synchronous view did, so junk archive entries aren't sent to
            # the analyzer.
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

            for member in audio_members:
                filename = os.path.basename(member.filename)
                try:
                    audio_data = archive.read(member.filename)
                    result = analyze_audio_clip(audio_data, filename)

                    # analyze_audio_clip catches its own exceptions internally
                    # and returns {"error": "..."} rather than raising, so
                    # this has to be checked explicitly - otherwise the
                    # missing keys below raise an opaque KeyError instead of
                    # surfacing the analyzer's actual error message.
                    if "error" in result:
                        raise RuntimeError(result["error"])

                    AudioAnalysis.objects.create(
                        batch=batch,
                        filename=filename,
                        status=AudioAnalysis.ProcessingStatus.SUCCESS,
                        emotional_tone=result["emotional_tone"],
                        emotional_intensity=result["emotional_intensity"],
                        background_noise_present=result["background_noise_present"],
                        background_noise_type=result["background_noise_type"],
                        background_noise_severity=result["background_noise_severity"],
                        audio_quality=result["audio_quality"],
                        speaker_overlap_present=result["speaker_overlap_present"],
                        long_silence_present=result["long_silence_present"],
                        confidence=result["confidence"],
                    )

                    result_with_name = dict(result)
                    result_with_name["filename"] = filename
                    predictions.append(result_with_name)
                    batch.processed_files += 1

                except Exception as clip_err:
                    # Record the failure on its own AudioAnalysis row (instead
                    # of just incrementing a counter) so it shows up in
                    # BatchDetailView / ExportBatchResultsView, with the
                    # error preserved for debugging.
                    batch.failed_files += 1
                    AudioAnalysis.objects.create(
                        batch=batch,
                        filename=filename,
                        status=AudioAnalysis.ProcessingStatus.FAILED,
                        error_details=str(clip_err),
                    )

                # Update live progress
                batch.save()

        # 3. Trigger evaluation scoring
        if ground_truths and predictions:
            eval_results = evaluate_predictions_against_ground_truth(predictions, ground_truths)
            if "error" not in eval_results:
                batch.metrics_json = json.dumps(eval_results)

        batch.status = BatchUpload.Status.COMPLETED
        batch.save()

    except Exception as e:
        if batch is not None:
            batch.status = BatchUpload.Status.FAILED
            batch.error_message = str(e)
            batch.save()
    finally:
        # Clean up temporary zip file
        if os.path.exists(zip_file_path):
            os.remove(zip_file_path)