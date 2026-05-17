"""Unit tests for monitor.state."""

import threading

import pytest

from monitor.state import StateCache


class TestPipeline:
    def test_update_and_get(self) -> None:
        cache = StateCache()
        cache.update_pipeline({"status": "running", "step": 1})
        assert cache.get_pipeline() == {"status": "running", "step": 1}

    def test_merge(self) -> None:
        cache = StateCache()
        cache.update_pipeline({"a": 1})
        cache.update_pipeline({"b": 2})
        assert cache.get_pipeline() == {"a": 1, "b": 2}

    def test_get_returns_copy(self) -> None:
        cache = StateCache()
        cache.update_pipeline({"a": 1})
        copy = cache.get_pipeline()
        copy["a"] = 999
        assert cache.get_pipeline() == {"a": 1}

    def test_update_pipeline_ignores_subsequent_input_mutation(self) -> None:
        cache = StateCache()
        data = {"a": 1}
        cache.update_pipeline(data)
        data["a"] = 999
        assert cache.get_pipeline() == {"a": 1}


class TestAgents:
    def test_update_and_get(self) -> None:
        cache = StateCache()
        cache.update_agent("hypothesis", {"status": "idle"})
        assert cache.get_agent("hypothesis") == {"status": "idle"}

    def test_get_missing_agent(self) -> None:
        cache = StateCache()
        assert cache.get_agent("missing") == {}

    def test_merge(self) -> None:
        cache = StateCache()
        cache.update_agent("data_engineer", {"x": 1})
        cache.update_agent("data_engineer", {"y": 2})
        assert cache.get_agent("data_engineer") == {"x": 1, "y": 2}

    def test_get_all_agents(self) -> None:
        cache = StateCache()
        cache.update_agent("a", {"v": 1})
        cache.update_agent("b", {"v": 2})
        assert cache.get_all_agents() == {"a": {"v": 1}, "b": {"v": 2}}

    def test_get_agent_returns_copy(self) -> None:
        cache = StateCache()
        cache.update_agent("a", {"v": 1})
        copy = cache.get_agent("a")
        copy["v"] = 999
        assert cache.get_agent("a") == {"v": 1}

    def test_get_all_agents_returns_copy(self) -> None:
        cache = StateCache()
        cache.update_agent("a", {"v": 1})
        all_agents = cache.get_all_agents()
        all_agents["a"]["v"] = 999
        assert cache.get_agent("a") == {"v": 1}

    def test_update_agent_ignores_subsequent_input_mutation(self) -> None:
        cache = StateCache()
        data = {"v": 1}
        cache.update_agent("a", data)
        data["v"] = 999
        assert cache.get_agent("a") == {"v": 1}


class TestRuns:
    def test_set_and_get(self) -> None:
        cache = StateCache()
        cache.set_runs([{"id": 1}, {"id": 2}])
        assert cache.get_runs() == [{"id": 1}, {"id": 2}]

    def test_get_returns_copy(self) -> None:
        cache = StateCache()
        cache.set_runs([{"id": 1}])
        copy = cache.get_runs()
        copy[0]["id"] = 999
        assert cache.get_runs() == [{"id": 1}]

    def test_replace(self) -> None:
        cache = StateCache()
        cache.set_runs([{"id": 1}])
        cache.set_runs([{"id": 2}])
        assert cache.get_runs() == [{"id": 2}]


class TestLogs:
    def test_append_and_get(self) -> None:
        cache = StateCache()
        cache.append_log("agent1", {"msg": "hello"})
        cache.append_log("agent1", {"msg": "world"})
        assert cache.get_logs("agent1") == [{"msg": "hello"}, {"msg": "world"}]

    def test_get_logs_limit(self) -> None:
        cache = StateCache()
        for i in range(10):
            cache.append_log("agent1", {"i": i})
        assert cache.get_logs("agent1", limit=3) == [{"i": 7}, {"i": 8}, {"i": 9}]

    def test_max_keep_trimming(self) -> None:
        cache = StateCache()
        for i in range(250):
            cache.append_log("agent1", {"i": i}, max_keep=200)
        assert len(cache.get_logs("agent1", limit=250)) == 200
        assert cache.get_logs("agent1", limit=1) == [{"i": 249}]

    def test_get_logs_missing_agent(self) -> None:
        cache = StateCache()
        assert cache.get_logs("missing") == []

    def test_get_all_logs(self) -> None:
        cache = StateCache()
        cache.append_log("a", {"msg": "a1"})
        cache.append_log("b", {"msg": "b1"})
        assert cache.get_all_logs() == {
            "a": [{"msg": "a1"}],
            "b": [{"msg": "b1"}],
        }

    def test_get_all_logs_limit(self) -> None:
        cache = StateCache()
        for i in range(10):
            cache.append_log("a", {"i": i})
        assert len(cache.get_all_logs(limit=3)["a"]) == 3

    def test_append_log_returns_copy(self) -> None:
        cache = StateCache()
        event = {"msg": "hello"}
        cache.append_log("a", event)
        event["msg"] = "mutated"
        assert cache.get_logs("a") == [{"msg": "hello"}]


class TestThreadSafety:
    def test_concurrent_pipeline_updates(self) -> None:
        cache = StateCache()
        errors: list[Exception] = []

        def worker(idx: int) -> None:
            try:
                for _ in range(500):
                    cache.update_pipeline({f"key_{idx}": idx})
                    cache.get_pipeline()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        result = cache.get_pipeline()
        assert len(result) == 10
        for i in range(10):
            assert result[f"key_{i}"] == i

    def test_concurrent_agent_updates(self) -> None:
        cache = StateCache()
        errors: list[Exception] = []

        def worker(agent: str, idx: int) -> None:
            try:
                for _ in range(500):
                    cache.update_agent(agent, {f"k_{idx}": idx})
                    cache.get_agent(agent)
                    cache.get_all_agents()
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=worker, args=(f"agent_{i % 5}", i))
            for i in range(20)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        for i in range(5):
            agent_state = cache.get_agent(f"agent_{i}")
            # Each of the 4 workers that touched this agent set one key
            assert len(agent_state) == 4

    def test_concurrent_log_appends(self) -> None:
        cache = StateCache()
        errors: list[Exception] = []

        def worker(agent: str, start: int) -> None:
            try:
                for j in range(100):
                    cache.append_log(agent, {"v": start + j}, max_keep=400)
                    cache.get_logs(agent)
                    cache.get_all_logs()
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=worker, args=(f"agent_{i % 3}", i * 1000))
            for i in range(9)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        for i in range(3):
            logs = cache.get_logs(f"agent_{i}", limit=1000)
            assert len(logs) == 300
            # Verify no data corruption by checking uniqueness
            values = [e["v"] for e in logs]
            assert len(set(values)) == len(values)
