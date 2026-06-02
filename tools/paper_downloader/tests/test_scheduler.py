import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core.scheduler import Scheduler, should_run
from datetime import datetime, timedelta


def test_should_run_weekly_never_run():
    assert should_run("weekly", None) is True


def test_should_run_weekly_recently_run():
    last = datetime.now() - timedelta(days=2)
    assert should_run("weekly", last) is False


def test_should_run_weekly_long_ago():
    last = datetime.now() - timedelta(days=8)
    assert should_run("weekly", last) is True


def test_scheduler_filters_sources():
    from sources.base import Source

    class MockSource(Source):
        name = "mock_weekly"
        frequency = "weekly"

        def scan(self, since):
            return []

        def download(self, meta, dest):
            return dest

    scheduler = Scheduler([MockSource()], config={})
    sources = scheduler.get_due_sources()
    assert len(sources) == 1
