"""YOLO26 ONNX object detector and content-embedding extractor."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import onnx
import onnxruntime as ort
from PIL import Image

from image_triage.core.models import Detection

INPUT_SIZE = 640
# End of the YOLO26 backbone (C2PSA block). Its spatial average is a compact content
# embedding used for similarity grouping.
EMBEDDING_TENSOR = "/model.10/cv2/act/Mul_output_0"


class UnsupportedModelError(ValueError):
    """The ONNX file is not the expected YOLO26 detector."""


@dataclass(slots=True)
class DetectorResult:
    """Detections and an L2-normalized embedding for one image."""

    detections: list[Detection]
    embedding: np.ndarray


class ObjectDetector:
    """Thread-safe YOLO26 detector wrapper.

    The ONNX Runtime session is shared across analysis threads; ``run`` is safe for
    concurrent reads.
    """

    def __init__(
        self,
        model_path: Path,
        confidence: float = 0.5,
        provider: str = "CPUExecutionProvider",
    ):
        model = onnx.load(str(model_path))
        if not any(EMBEDDING_TENSOR in node.output for node in model.graph.node):
            raise UnsupportedModelError(f"Unsupported model (expected YOLO26): {model_path}")
        model.graph.output.append(
            onnx.helper.make_tensor_value_info(EMBEDDING_TENSOR, onnx.TensorProto.FLOAT, None)
        )
        options = ort.SessionOptions()
        # Analysis already runs in parallel threads; avoid nested thread pools.
        options.intra_op_num_threads = 1
        options.log_severity_level = 3
        self.session = ort.InferenceSession(
            model.SerializeToString(), options, providers=[provider]
        )
        self.input_name = self.session.get_inputs()[0].name
        self.names = ast.literal_eval(self.session.get_modelmeta().custom_metadata_map["names"])
        self.confidence = confidence

    def detect(self, image: Image.Image) -> DetectorResult:
        """Detect objects and return the content embedding for an RGB image."""
        width, height = image.size
        scale = INPUT_SIZE / max(width, height)
        new_width, new_height = round(width * scale), round(height * scale)
        offset_x, offset_y = (INPUT_SIZE - new_width) // 2, (INPUT_SIZE - new_height) // 2
        canvas = Image.new("RGB", (INPUT_SIZE, INPUT_SIZE), (114, 114, 114))
        canvas.paste(
            image.resize((new_width, new_height), Image.Resampling.BILINEAR),
            (offset_x, offset_y),
        )
        tensor = np.asarray(canvas, np.float32).transpose(2, 0, 1)[None] / 255.0

        boxes, features = self.session.run(None, {self.input_name: tensor})
        detections: list[Detection] = []
        # End-to-end model: rows are x1, y1, x2, y2, confidence, class (no NMS needed).
        for x1, y1, x2, y2, confidence, class_id in boxes[0]:
            if confidence < self.confidence:
                continue
            box = (
                float(np.clip((x1 - offset_x) / new_width, 0, 1)),
                float(np.clip((y1 - offset_y) / new_height, 0, 1)),
                float(np.clip((x2 - offset_x) / new_width, 0, 1)),
                float(np.clip((y2 - offset_y) / new_height, 0, 1)),
            )
            detections.append(Detection(self.names[int(class_id)], float(confidence), box))
        embedding = np.asarray(features[0], dtype=np.float32).mean(axis=(1, 2))
        norm = float(np.linalg.norm(embedding))
        if norm > 1e-9:
            embedding = embedding / norm
        return DetectorResult(detections=detections, embedding=embedding)
