import pytest

from the_vision.detector import ModelMissingError, resolve_model


def test_offline_missing_model_raises_instead_of_downloading(tmp_path):
    with pytest.raises(ModelMissingError, match="fetch_models"):
        resolve_model(str(tmp_path / "yolo11n-pose.pt"), offline=True)


def test_existing_model_is_used(tmp_path):
    f = tmp_path / "m.pt"
    f.write_bytes(b"x")
    assert resolve_model(str(f), offline=True) == str(f)


def test_online_mode_allows_auto_download():
    assert resolve_model("yolo11n-pose.pt", offline=False) == "yolo11n-pose.pt"
