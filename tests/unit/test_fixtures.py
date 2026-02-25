from pathlib import Path


def test_slip_fixtures_exist_and_non_empty():
    root = Path(__file__).resolve().parents[1] / "fixtures" / "slips"
    files = ["t4_sample.txt", "t5_sample.txt", "rrsp_sample.txt"]
    for name in files:
        path = root / name
        assert path.exists()
        assert path.read_text().strip() != ""
