# Deliverable #9: Failure Modes, Limitations, and Production Roadmap

## 1. Primary Failure Modes & Root Causes

Our analysis of edge cases during testing identified four key failure modes where model predictions can degrade:

### A. Short Audio Clips & Extreme Truncation (< 1.5 seconds)
* **Symptom:** Inconsistent or lower-confidence emotion predictions on brief utterances (e.g., single-word responses like "Yeah" or "Okay").
* **Root Cause:** Wav2Vec2 transformer architectures rely on global context frames. Very short audio duration provides insufficient temporal feature maps for stable attention outputs.

### B. High Acoustic Noise & Cross-Talk (Overlapping Speakers)
* **Symptom:** Misinterpreting loud overlapping background speech as primary customer frustration or distress.
* **Root Cause:** Signal energy spikes from overlapping voices mimic pitch/amplitude escalation. Without explicit speaker diarization, the model evaluates total energy across both tracks.

### C. Background Music & Non-Speech Harmonics
* **Symptom:** Incorrect noise classification or inflated noise severity on calls with hold music or television chatter.
* **Root Cause:** Spectral centroid analysis can blur harmonic tones with broadband noise signatures.

### D. Subdued or Sarcastic Tone
* **Symptom:** Sarcastic statements (e.g., "Oh, fantastic service") classified as `neutral` or `satisfied`.
* **Root Cause:** Acoustic models evaluate pitch and spectral energy rather than semantic linguistic context.

---

## 2. System Limitations

1. **Mono Audio Processing:** The current pipeline assumes single-channel or flattened multi-channel audio files and does not separate agent and customer channels prior to classification.
2. **Deterministic Heuristics for Overlap & Silence:** Speaker overlap and long silence checks use energy-threshold heuristics (`librosa.effects.split`) rather than neural diarization models.
3. **Language Context:** The `superb/wav2vec2-base-superb-er` underlying model is optimized primarily for English phoneme patterns.

---

## 3. Recommended Next Steps for Production

To address these limitations while maintaining our **$0.003/minute cost ceiling**, we recommend the following enhancements:

### Short-Term Improvements (1–2 Weeks)
* **Diarization Integration:** Integrate `pyannote.audio` or a lightweight speaker separation module to isolate the customer audio channel prior to tone analysis.
* **ONNX Runtime Quantization:** Convert Wav2Vec2 PyTorch models to quantized ONNX format (INT8), cutting memory consumption by 50% and doubling CPU inference speed.
* **Semantic Context Multimodal Layer:** Combine speech emotion recognition logits with a lightweight open-source text sentiment model (e.g., `distilbert-base-uncased-finetuned-sst-2-english`) run on ASR transcripts to handle linguistic sarcasm.

### Long-Term Scaling (3–4 Weeks)
* **Asynchronous Task Queue:** Transition batch execution in Django from synchronous view handlers to an asynchronous task system using **Celery + Redis** to seamlessly handle multi-gigabyte ZIP archives containing thousands of calls.
* **Active Learning Pipeline:** Automatically route low-confidence predictions ($\text{confidence} < 0.60$) to a human-in-the-loop audit dashboard for ongoing fine-tuning dataset expansion.