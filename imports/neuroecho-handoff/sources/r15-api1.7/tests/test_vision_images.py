import base64
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from PIL import Image
from server import plugin_bridge, vision_images


def image_bytes(fmt="PNG", color="red"):
    output = BytesIO()
    Image.new("RGB", (3, 3), color).save(output, format=fmt)
    return output.getvalue()


def data_url(raw, mime="image/png"):
    return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"


class VisionImagesTest(unittest.TestCase):
    def test_valid_picture_is_normalized_and_checked(self):
        original = data_url(image_bytes())
        self.assertEqual(vision_images.validate_data_url(original), original)

    def test_rejects_bad_untrusted_images(self):
        bad_images = [
            "data:image/svg+xml;base64,PHN2Zz4=", "https://example.com/image.png",
            "data:image/png;base64,!!!!", "data:image/png;base64,a",
            data_url(b"not an image"), data_url(image_bytes("JPEG")),
            data_url(b"x" * (vision_images.MAX_IMAGE_BYTES + 1)),
        ]
        for bad in bad_images:
            with self.subTest(prefix=bad[:30]), self.assertRaises(ValueError):
                vision_images.validate_data_url(bad)

    def test_gif_uses_first_frame_as_png(self):
        output = BytesIO()
        Image.new("RGB", (3, 3), "red").save(
            output, format="GIF", save_all=True,
            append_images=[Image.new("RGB", (3, 3), "blue")]
        )
        converted = vision_images.validate_data_url(data_url(output.getvalue(), "image/gif"))
        self.assertTrue(converted.startswith("data:image/png;base64,"))
        result = Image.open(BytesIO(base64.b64decode(converted.split(",", 1)[1])))
        self.assertEqual(result.getpixel((0, 0))[:3], (255, 0, 0))

    def test_catalog_sticker_and_unlisted_path(self):
        with TemporaryDirectory() as directory:
            root = Path(directory) / "stickers"
            pack = root / "pack"
            folder = pack / "memes" / "happy"
            folder.mkdir(parents=True)
            (pack / "manifest.json").write_text('{}', encoding="utf-8")
            (folder / "good.png").write_bytes(image_bytes())
            secret = Path(directory) / "secret.png"
            secret.write_bytes(image_bytes())
            (folder / "escape.png").symlink_to(secret)
            with patch.object(plugin_bridge, "SERVER_STICKERS", root), patch.object(
                plugin_bridge, "PROFILES", Path(directory) / "no-profiles"
            ):
                self.assertTrue(vision_images.sticker_data_url("pack/happy/good.png").startswith("data:image/png;base64,"))
                for bad in ("pack/happy/../../secret.png", "pack/happy/escape.png", "builtin/happy.svg", "missing"):
                    with self.subTest(sticker=bad), self.assertRaises(ValueError):
                        vision_images.sticker_data_url(bad)


if __name__ == "__main__":
    unittest.main()
