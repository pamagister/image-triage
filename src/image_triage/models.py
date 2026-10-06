"""YOLO object detection (ONNX) and model download."""

import ast
import hashlib
import os
import sys
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import onnx
import onnxruntime as ort
from PIL import Image

DEFAULT_MODEL_PATH = Path("res/yolo/yolo26n.onnx")
MODEL_URL = (
    "https://raw.githubusercontent.com/pamagister/Photo-Composition-Designer/"
    "main/res/yolo/yolo26n.onnx"
)
MODEL_SHA256 = "c081e98157a0c0ba08fbed26a478d9caaf34e6b7bcc50d396f50e2c0d508a615"
DOWNLOAD_HINT = (
    "Download it with the 'Download model' button in the GUI or 'image-triage-download-model', "
    "or disable models.enabled."
)

INPUT_SIZE = 640
# End of the YOLO26 backbone (C2PSA block, 256 x 20 x 20). Its global average is used as a
# content embedding to compare what is in the picture.
EMBEDDING_TENSOR = "/model.10/cv2/act/Mul_output_0"


@dataclass
class Detection:
    label: str
    confidence: float
    box: tuple[float, float, float, float]  # x1, y1, x2, y2 relative to the image size (0-1)

    @property
    def area(self) -> float:
        x1, y1, x2, y2 = self.box
        return max(0.0, x2 - x1) * max(0.0, y2 - y1)


def download_model(
    path: Path,
    progress: Callable[[int, int], None] | None = None,
    url: str = MODEL_URL,
    sha256: str = MODEL_SHA256,
) -> None:
    """Download the model to `path`, verifying its checksum. `progress(done, total)` in bytes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".part")
    hasher = hashlib.sha256()
    with urllib.request.urlopen(url, timeout=60) as response, open(part, "wb") as f:
        total = int(response.headers.get("Content-Length") or 0)
        done = 0
        for chunk in iter(lambda: response.read(1 << 16), b""):
            f.write(chunk)
            hasher.update(chunk)
            done += len(chunk)
            if progress:
                progress(done, total)
    if hasher.hexdigest() != sha256:
        part.unlink()
        raise ValueError(f"Checksum mismatch for downloaded model from {url}")
    os.replace(part, path)


class ObjectDetector:
    """YOLO26 ONNX model: object detections plus a content embedding per image."""

    def __init__(self, model_path: Path, confidence: float):
        model = onnx.load(str(model_path))
        if not any(EMBEDDING_TENSOR in node.output for node in model.graph.node):
            raise ValueError(f"Unsupported model (expected a YOLO26 detector): {model_path}")
        model.graph.output.append(
            onnx.helper.make_tensor_value_info(EMBEDDING_TENSOR, onnx.TensorProto.FLOAT, None)
        )
        options = ort.SessionOptions()
        # Images are analyzed in parallel threads already.
        options.intra_op_num_threads = 1
        self.session = ort.InferenceSession(
            model.SerializeToString(), options, providers=["CPUExecutionProvider"]
        )
        self.input_name = self.session.get_inputs()[0].name
        self.names = ast.literal_eval(self.session.get_modelmeta().custom_metadata_map["names"])
        self.confidence = confidence

    def detect(self, image: Image.Image) -> tuple[list[Detection], np.ndarray]:
        """Detect objects in an RGB image and return them with an L2-normalized embedding."""
        w, h = image.size
        scale = INPUT_SIZE / max(w, h)
        nw, nh = round(w * scale), round(h * scale)
        dx, dy = (INPUT_SIZE - nw) // 2, (INPUT_SIZE - nh) // 2
        canvas = Image.new("RGB", (INPUT_SIZE, INPUT_SIZE), (114, 114, 114))
        canvas.paste(image.resize((nw, nh), Image.Resampling.BILINEAR), (dx, dy))
        tensor = np.asarray(canvas, np.float32).transpose(2, 0, 1)[None] / 255.0

        boxes, features = self.session.run(None, {self.input_name: tensor})
        detections = []
        # End-to-end model: rows are x1, y1, x2, y2, confidence, class (no NMS needed).
        for x1, y1, x2, y2, conf, cls in boxes[0]:
            if conf < self.confidence:
                continue
            box = (
                float(np.clip((x1 - dx) / nw, 0, 1)),
                float(np.clip((y1 - dy) / nh, 0, 1)),
                float(np.clip((x2 - dx) / nw, 0, 1)),
                float(np.clip((y2 - dy) / nh, 0, 1)),
            )
            detections.append(Detection(self.names[int(cls)], float(conf), box))
        embedding = features[0].mean(axis=(1, 2))
        return detections, embedding / np.linalg.norm(embedding)


def main() -> int:
    """Download the model to the default path (or the path given as argument)."""
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_MODEL_PATH
    if path.exists():
        print(f"Model already present: {path}")
        return 0
    print(f"Downloading {MODEL_URL}\n  -> {path}")
    download_model(path)
    print("Done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
