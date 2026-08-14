# audio_analytics/api_views.py

import os
import tempfile
from django.http import JsonResponse
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from .analyzer import analyze_audio_clip

@method_decorator(csrf_exempt, name="dispatch")
class LiveDemoAnalysisView(View):
    def post(self, request):
        audio_file = request.FILES.get("audio")
        if not audio_file:
            return JsonResponse({"error": "No audio data received."}, status=400)

        # Enforce maximum 10MB limit (~1-2 mins of audio)
        if audio_file.size > 10 * 1024 * 1024:
            return JsonResponse({"error": "Audio file exceeds 1-minute max limit."}, status=400)

        try:
            filename = audio_file.name or "demo_recording.webm"
            audio_bytes = audio_file.read()
            
            # Analyze clip dynamically using your analyzer pipeline
            result = analyze_audio_clip(audio_bytes, filename)
            return JsonResponse({"success": True, "data": result})
        except Exception as e:
            return JsonResponse({"error": f"Failed to analyze recording: {str(e)}"}, status=500)