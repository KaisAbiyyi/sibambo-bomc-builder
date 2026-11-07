"""BMB-028: reproducible, measured agent-workflow benchmarks (lock evaluation/metrics).

Measures a scripted workflow against the real stdio MCP server and the real BOMC compiler. It makes
no performance promise and uses no model: deterministic quantities (calls, retries, estimated tokens,
bytes, hashes, geometry results) are expected to be identical on every run and every OS; timing and
memory are descriptive and vary by machine.
"""
