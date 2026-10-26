import pytest


@pytest.fixture(autouse=True)
def _isolate_carbon(tmp_path, monkeypatch, request):
    """Every extract is measured; keep tests off the real sensors, grid and output/."""
    from paratext import carbon, meters, report, tracking

    monkeypatch.setattr(tracking, "RUNS_DIR", tmp_path / "carbon" / "runs")
    monkeypatch.setattr(report, "REPORT_DIR", tmp_path / "carbon")
    if request.node.get_closest_marker("real_carbon"):
        return
    monkeypatch.setattr(meters, "detect", lambda *a, **k: (None, "no sensor (test)"))
    monkeypatch.setattr(carbon, "load_config", lambda: carbon.CarbonConfig())


def pytest_configure(config):
    config.addinivalue_line("markers", "real_carbon: use the real carbon config and meters")
