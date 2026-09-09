"""run_id 以本地时间精确到分钟命名。"""
from datetime import datetime

from app.core.runner import RunStore, allocate_run_id


def test_allocate_run_id_is_minute_stamp(tmp_path, monkeypatch):
    monkeypatch.setenv("VIZGUIDE_STORAGE_DIR", str(tmp_path))
    rid = allocate_run_id(RunStore())
    assert rid == datetime.now().strftime("%Y%m%d-%H%M")


def test_allocate_run_id_disambiguates_same_minute(tmp_path, monkeypatch):
    monkeypatch.setenv("VIZGUIDE_STORAGE_DIR", str(tmp_path))
    store = RunStore()
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    (tmp_path / "runs").mkdir(parents=True)
    (tmp_path / "runs" / f"{stamp}.json").write_text("{}", encoding="utf-8")
    rid = allocate_run_id(store)
    assert rid == f"{stamp}-2"
