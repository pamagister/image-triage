"""ONNX Runtime execution provider detection."""

from __future__ import annotations

from image_triage.core.models import Provider

PRIORITY = [
    Provider.CUDA,
    Provider.ROCM,
    Provider.OPENVINO,
    Provider.DIRECTML,
    Provider.CPU,
]


def available_providers() -> list[str]:
    """Return available ONNX Runtime providers, or CPU only when unavailable."""
    try:
        import onnxruntime as ort

        return list(ort.get_available_providers())
    except Exception:
        return [Provider.CPU.value]


def select_provider(preference: str = "auto") -> str:
    """Choose a provider, preferring the configured one, then GPU, then CPU."""
    available = available_providers()
    if preference and preference != "auto" and preference in available:
        return preference
    for provider in PRIORITY:
        if provider.value in available:
            return provider.value
    return Provider.CPU.value
