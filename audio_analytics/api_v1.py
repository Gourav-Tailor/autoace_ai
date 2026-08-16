# audio_analytics/api_v1.py
"""
Token-authenticated API for external devices (ESP32, Raspberry Pi) and
mobile apps.

This file is fully additive:
- Does NOT modify or import anything from api_views.py.
- Reuses the same on-disk chunk/zip/Celery pipeline (process_batch_upload_task)
  so the processing logic never has to know whether audio came from the
  browser (session+CSRF) or a device (token auth).
- The existing web endpoints (LiveDemoAnalysisView, LongRecorderBatchView)
  and long_recorder.html are completely unaffected by anything here.

Auth: clients send `Authorization: Token <key>` on every request instead of
relying on cookies/CSRF. Issue tokens with the `create_device_token`
management command (see audio_analytics/management/commands/).
"""
import os
import tempfile
import zipfile
import traceback
import uuid

from django.utils import timezone
from rest_framework.authentication import TokenAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from pydub import AudioSegment

from .models import BatchUpload, Device
from .tasks import process_batch_upload_task


def _chunk_dir(batch_id):
    return os.path.join(tempfile.gettempdir(), f"batch_stream_{batch_id}")


def _touch_device(request):
    device = request.auth

    device.last_seen = timezone.now()
    device.save(update_fields=["last_seen"])

    return device


class SessionInitView(APIView):
    """POST /api/v1/sessions/  ->  start a new recording session (batch)."""

    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        _touch_device(request)
        title = request.data.get("title", "Device Recording")
        device = Device.objects.filter(api_token=request.auth).first()

        batch = BatchUpload.objects.create(
            user=request.user,
            name=f"{title} (Device Stream)",
            status="recording",
            device=device,
        )
        return Response(
            {"status": "success", "batch_id": batch.id},
            status=status.HTTP_201_CREATED,
        )


class SessionChunkView(APIView):
    """
    POST /api/v1/sessions/<batch_id>/chunks/

    Accepts one audio chunk (`chunk_data` file field, `index` integer field).
    Idempotent on `index`: retrying a chunk that already saved successfully
    returns 200 with duplicate=true instead of reprocessing or erroring --
    devices on flaky networks WILL retry requests that actually succeeded.
    """

    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, batch_id):
        _touch_device(request)

        batch = BatchUpload.objects.filter(id=batch_id, user=request.user).first()
        if not batch:
            return Response({"error": "Session not found"}, status=status.HTTP_404_NOT_FOUND)

        chunk_index = request.data.get("index")
        audio_file = request.FILES.get("chunk_data")
        if chunk_index is None or not audio_file:
            return Response(
                {"error": "Missing index or chunk_data"}, status=status.HTTP_400_BAD_REQUEST
            )

        try:
            chunk_index = int(chunk_index)
        except (TypeError, ValueError):
            return Response({"error": "index must be an integer"}, status=status.HTTP_400_BAD_REQUEST)

        chunk_dir = _chunk_dir(batch_id)
        os.makedirs(chunk_dir, exist_ok=True)

        wav_path = os.path.join(chunk_dir, f"chunk_{chunk_index:04d}.wav")

        if os.path.exists(wav_path):
            return Response(
                {"status": "chunk_saved", "filename": os.path.basename(wav_path), "duplicate": True},
                status=status.HTTP_200_OK,
            )

        raw_path = os.path.join(chunk_dir, f"temp_{chunk_index}_{uuid.uuid4().hex}.raw")

        try:
            with open(raw_path, "wb+") as dst:
                for c in audio_file.chunks():
                    dst.write(c)

            if not os.path.exists(raw_path) or os.path.getsize(raw_path) == 0:
                return Response(
                    {"error": f"Uploaded chunk {chunk_index} was empty or failed to save."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            try:
                sound = AudioSegment.from_file(raw_path)
                sound = sound.set_frame_rate(16000).set_channels(1)
                sound.export(wav_path, format="wav")
            except Exception:
                # Fallback: if pydub/ffmpeg can't decode it, keep the raw bytes
                # under the expected .wav name rather than losing the chunk.
                if os.path.exists(raw_path):
                    os.rename(raw_path, wav_path)
            finally:
                if os.path.exists(raw_path):
                    os.remove(raw_path)

            return Response(
                {"status": "chunk_saved", "filename": os.path.basename(wav_path)},
                status=status.HTTP_200_OK,
            )
        except Exception as e:
            traceback.print_exc()
            return Response(
                {"error": f"Internal Server Error: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class SessionFinalizeView(APIView):
    """POST /api/v1/sessions/<batch_id>/finalize/  ->  zip chunks & queue processing."""

    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, batch_id):
        _touch_device(request)

        batch = BatchUpload.objects.filter(id=batch_id, user=request.user).first()
        if not batch:
            return Response({"error": "Session not found"}, status=status.HTTP_404_NOT_FOUND)

        chunk_dir = _chunk_dir(batch_id)
        if not os.path.exists(chunk_dir) or not os.listdir(chunk_dir):
            return Response(
                {"error": "No recorded audio chunks found on server"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            zip_path = os.path.join(tempfile.gettempdir(), f"batch_{batch_id}_audio.zip")
            with zipfile.ZipFile(zip_path, "w") as zipf:
                for root, _, files in os.walk(chunk_dir):
                    for f in sorted(files):
                        if f.endswith(".wav"):
                            zipf.write(os.path.join(root, f), arcname=f)

            for f in os.listdir(chunk_dir):
                os.remove(os.path.join(chunk_dir, f))
            os.rmdir(chunk_dir)

            batch.status = "pending"
            batch.save(update_fields=["status"])

            process_batch_upload_task.delay(batch.id, zip_path)

            return Response({"status": "queued", "batch_id": batch.id}, status=status.HTTP_200_OK)
        except Exception as e:
            traceback.print_exc()
            return Response(
                {"error": f"Internal Server Error: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class SessionHeartbeatView(APIView):
    """
    POST /api/v1/sessions/<batch_id>/heartbeat/

    Cheap keep-alive ping a device can call periodically during a long
    session, so you can distinguish "still recording" from "silently died"
    without guessing from chunk upload timestamps alone.
    """

    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, batch_id):
        _touch_device(request)
        batch = BatchUpload.objects.filter(id=batch_id, user=request.user).first()
        if not batch:
            return Response({"error": "Session not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response({"status": "alive", "batch_status": batch.status}, status=status.HTTP_200_OK)