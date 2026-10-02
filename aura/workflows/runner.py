from aura.models import ActionResult
from aura.workflows.catalog import WORKFLOWS


class WorkflowRunner:
    def __init__(self, registry): self.registry = registry

    def run(self, workflow_id):
        workflow = WORKFLOWS.get(workflow_id)
        if not workflow: return ActionResult(False, "I don't have that workflow.")
        completed = 0
        for step in workflow["steps"]:
            spec = self.registry.get(step["intent"])
            if not spec or spec.requires_confirmation:
                return ActionResult(False, "This workflow contains an unavailable action.", {"completed_steps":completed})
            result = self.registry.execute(step["intent"], step["arguments"])
            if not result.success: return ActionResult(False, result.message, {"completed_steps":completed})
            completed += 1
        return ActionResult(True, f"{workflow_id.replace('_',' ').title()} is ready.", {"completed_steps":completed})
