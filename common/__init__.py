"""What the benchmark and the CAD-code evaluation share.

- `config`: the settings in the repository's `config.toml`, checked before anything runs.
- `litellm`: the one way a model is called, through LiteLLM on the Mac's :4000.
- `records`: where a run's records go, on the Mac, outside any checkout.
- `results`: the numbers a run leaves in the repository, and the check that they're only numbers.
- `crew`: the crew commit a run imports.
"""
