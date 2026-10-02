from aura.models import ActionSpec


def register_workflows(registry, runner):
    registry.register(ActionSpec("run_workflow", "Run a predefined workflow",
        {"type":"object","properties":{"workflow_id":{"type":"string","enum":["study_mode","coding_mode","presentation_mode"]}},"required":["workflow_id"],"additionalProperties":False},
        lambda workflow_id: runner.run(workflow_id), examples=("Start study mode.",)))
