from shared.voice_assistant import build_voice_status_response


SNAPSHOT = {
    "working": 2,
    "nodes_online": 3,
    "tasks_total": 8,
    "task_status": {
        "pending": 1,
        "assigned": 1,
        "running": 1,
        "completed": 5,
        "failed": 0,
        "other": 0,
    },
    "nodes": [
        {"id": "worker-1", "name": "worker-1", "cpu": 94.2, "ram": 78.0, "thermal": 83.1, "status": "HEALTHY"},
        {"id": "worker-2", "name": "worker-2", "cpu": 41.0, "ram": 33.5, "thermal": 49.0, "status": "HEALTHY"},
    ],
    "recent_tasks": [],
}


def test_build_voice_status_response_returns_cluster_summary():
    result = build_voice_status_response("What is the cluster status?", SNAPSHOT, use_ai=False)

    assert result["ok"] is True
    assert result["provider"] == "local"
    assert "3 nodes" in result["answer"] or "3 nodes are online" in result["answer"]
    assert result["snapshot"]["nodes_online"] == 3


def test_build_voice_status_response_highlights_busy_worker():
    result = build_voice_status_response("Which worker is the hottest?", SNAPSHOT, use_ai=False)

    assert result["provider"] == "local"
    assert "worker-1" in result["answer"]
    assert "94.2% CPU" in result["answer"]
