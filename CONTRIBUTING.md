# Contributing

Create a virtual environment, install with `python -m pip install -e .`, and run `python -m unittest discover -s tests -v`.

For numerical changes, include an independent benchmark or financial invariant and describe units and assumptions. Preserve the exact P&L identity and report approximation residuals. Add a minimal failing case before fixing an accounting bug.

Avoid committing account credentials, personal positions, proprietary research or unlicensed market data. Examples should use synthetic holdings. Do not change the scenario grid after evaluating a policy without recording a new experiment.

A pull request should explain the problem, resulting behavior, validation and any changed model assumptions. Model changes require a version increase so saved research reports can identify the implementation.
