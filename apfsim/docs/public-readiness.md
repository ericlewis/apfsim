# Public Readiness Notes

Before publishing `pocket_sim`, keep these boundaries explicit:

- Public CI should default to mock-only profiles so it does not require private ROMs or local checkouts.
- External core profiles should skip cleanly when their checkout root is missing.
- Generated profiles are review artifacts, not trusted production gates.
- Do not commit ROM assets or proprietary generated IP.
- Keep shim catalog entries public-source-compatible or clearly mark local/private requirements.
- Treat `video_shape.json`, `lifecycle.json`, `bridge_summary.json`, and `result.json` as versioned contracts.

Recommended public smoke:

```sh
bin/apfsim doctor --profile mock_port_gate
bin/apfsim test --matrix ci
bin/apfsim generate-profile --root /path/to/core --output output/generated-profiles
```
