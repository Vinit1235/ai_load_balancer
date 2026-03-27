class Scheduler:
    def __init__(self, state_manager):
        self.state_manager = state_manager
        self.mode = "HEURISTIC"  # or "AI"

    def select_node(self, task):
        if self.mode == "HEURISTIC":
            return self._heuristic_select(task)
        # Placeholder for AI mode
        return None

    def _heuristic_select(self, task):
        nodes = self.state_manager.get_nodes()
        best_node = None
        best_score = float('inf')
        for node in nodes:
            cpu_percent = node.get('cpu_percent', 0)
            ram_percent = node.get('ram_percent', 0)
            active_task_count = node.get('active_task_count', 0)
            score = (cpu_percent + ram_percent) * (1 + active_task_count * 0.2)
            if score < best_score:
                best_score = score
                best_node = node
        return best_node

    def drain_node(self, node_id):
        self.state_manager.set_node_status(node_id, "DRAINING")

    def migrate_task(self, task_id, target_node):
        self.state_manager.migrate_task(task_id, target_node)

    def rebalance(self):
        # Example: spread tasks evenly across nodes
        tasks = self.state_manager.get_pending_tasks()
        nodes = self.state_manager.get_nodes()
        if not nodes:
            return
        for i, task in enumerate(tasks):
            node = nodes[i % len(nodes)]
            self.state_manager.assign_task(task['id'], node['id'])
