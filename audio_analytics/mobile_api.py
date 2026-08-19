from django.contrib.auth import authenticate
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import AudioAnalysis, Device, MobileAuthToken


def _get_token(request):
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token.strip()


def _authenticate_mobile_request(request):
    raw_token = _get_token(request)
    if not raw_token:
        return None, None

    auth_token = (
        MobileAuthToken.objects.select_related("user")
        .filter(token=raw_token, revoked=False)
        .first()
    )
    if not auth_token:
        return None, None

    auth_token.last_used_at = timezone.now()
    auth_token.save(update_fields=["last_used_at"])
    return auth_token.user, auth_token


class MobileLoginView(APIView):
    """
    POST /api/v1/mobile/login/

    Body:
    {
        "username": "...",
        "password": "..."
    }

    Returns a mobile bearer token and the user's devices.
    """

    permission_classes = [AllowAny]

    def post(self, request):
        username = str(request.data.get("username", "")).strip()
        password = str(request.data.get("password", ""))

        if not username or not password:
            return Response(
                {"success": False, "error": "Username and password are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = authenticate(request=request, username=username, password=password)
        if user is None:
            return Response(
                {"success": False, "error": "Invalid username or password."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        if not user.is_active:
            return Response(
                {"success": False, "error": "User account is inactive."},
                status=status.HTTP_403_FORBIDDEN,
            )

        auth_token = MobileAuthToken.issue(user)

        devices = Device.objects.filter(user=user).order_by("-created_at")

        return Response(
            {
                "success": True,
                "token": auth_token.token,
                "devices": [
                    _serialize_device(device, include_key=False) for device in devices
                ],
            },
            status=status.HTTP_200_OK,
        )


class MobileLogoutView(APIView):
    """
    POST /api/v1/mobile/logout/
    """

    permission_classes = [AllowAny]

    def post(self, request):
        raw_token = _get_token(request)
        if raw_token:
            MobileAuthToken.objects.filter(
                token=raw_token,
                revoked=False,
            ).update(revoked=True, revoked_at=timezone.now())

        return Response({"success": True}, status=status.HTTP_200_OK)


class MobileDevicesView(APIView):
    """
    GET /api/v1/mobile/devices/
    """

    permission_classes = [AllowAny]

    def get(self, request):
        user, _ = _authenticate_mobile_request(request)
        if user is None:
            return Response(
                {
                    "detail": "Authentication credentials were not provided or are invalid."
                },
                status=status.HTTP_401_UNAUTHORIZED,
            )

        devices = Device.objects.filter(user=user).order_by("-created_at")

        return Response(
            {
                "devices": [
                    _serialize_device(device, include_key=False) for device in devices
                ]
            },
            status=status.HTTP_200_OK,
        )


class MobileDeviceLatestAnalysisView(APIView):
    """
    GET /api/v1/mobile/devices/<device_id>/latest-analysis/
    """

    permission_classes = [AllowAny]

    def get(self, request, device_id):
        user, _ = _authenticate_mobile_request(request)
        if user is None:
            return Response(
                {
                    "detail": "Authentication credentials were not provided or are invalid."
                },
                status=status.HTTP_401_UNAUTHORIZED,
            )

        device = Device.objects.filter(id=device_id, user=user).first()
        if device is None:
            return Response(
                {"detail": "Device not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        batch = device.batches.order_by("-id").first()

        if batch is None:
            return Response(
                {
                    "status": "no_recording",
                    "device": _serialize_device(device, include_key=False),
                    "batch_id": None,
                    "batch_status": None,
                    "latestAnalysis": None,
                },
                status=status.HTTP_200_OK,
            )

        analysis = (
            AudioAnalysis.objects.filter(
                batch=batch,
                status=AudioAnalysis.ProcessingStatus.SUCCESS,
            )
            .order_by("-id")
            .first()
        )

        return Response(
            {
                "status": "success" if analysis else "processing",
                "device": _serialize_device(device, include_key=False),
                "batch_id": batch.id,
                "batch_status": batch.status,
                "latestAnalysis": (_serialize_analysis(analysis) if analysis else None),
            },
            status=status.HTTP_200_OK,
        )


def _serialize_device(device, include_key=False):
    data = {
        "id": device.id,
        "name": device.name,
        "last_seen": device.last_seen.isoformat() if device.last_seen else None,
        "created_at": device.created_at.isoformat(),
    }

    if include_key:
        data["key"] = device.key

    return data


def _serialize_analysis(analysis):
    data = {
        "id": analysis.id,
        "batch_id": analysis.batch_id,
        "filename": analysis.filename,
        "status": analysis.status,
        "created_at": (
            analysis.created_at.isoformat()
            if getattr(analysis, "created_at", None)
            else None
        ),
    }

    for field in (
        "emotional_tone",
        "emotional_intensity",
        "background_noise_present",
        "background_noise_type",
        "background_noise_severity",
        "audio_quality",
        "speaker_overlap_present",
        "long_silence_present",
        "confidence",
    ):
        if hasattr(analysis, field):
            value = getattr(analysis, field)
            if (
                field
                in {
                    "background_noise_present",
                    "speaker_overlap_present",
                    "long_silence_present",
                }
                and value is not None
            ):
                value = bool(value)
            elif field == "confidence" and value is not None:
                value = float(value)
            data[field] = value

    return data
