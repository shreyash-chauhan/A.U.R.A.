# Workflows contain only fixed calls to registered actions. Extend this data, never model-generated steps.
WORKFLOWS = {
    "study_mode": {"description":"Open a focused study setup", "steps":[
        {"intent":"open_app","arguments":{"app_id":"vscode"}},
        {"intent":"open_app","arguments":{"app_id":"chrome"}},
        {"intent":"open_documents","arguments":{}},
        {"intent":"volume_down","arguments":{}},
        {"intent":"set_timer","arguments":{"seconds":3000}}]},
    "coding_mode": {"description":"Open a coding setup", "steps":[
        {"intent":"open_app","arguments":{"app_id":"vscode"}},
        {"intent":"open_app","arguments":{"app_id":"terminal"}}]},
    "presentation_mode": {"description":"Open presentation software and lower system volume", "steps":[
        {"intent":"open_app","arguments":{"app_id":"powerpoint"}},
        {"intent":"volume_down","arguments":{}}]},
}
