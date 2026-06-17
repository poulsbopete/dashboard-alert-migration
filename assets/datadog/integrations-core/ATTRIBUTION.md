# Datadog integrations-core dashboard JSON

Dashboard definitions in this directory are copied from
[DataDog/integrations-core](https://github.com/DataDog/integrations-core) (BSD 3-Clause License).

Copyright © Datadog, Inc. and contributors. Redistribution and use in source and binary forms,
with or without modification, are permitted under the terms of the integrations-core LICENSE file.

These are **real** Datadog Agent integration dashboards (metric namespaces like `nginx.*`, `postgresql.*`).
They complement the synthetic OTLP-aligned dashboards in `assets/datadog/dashboards/`, which match the
workshop telemetry fleet. After migration, integration dashboards typically need matching metric data
(or `--field-profile` tuning) to populate charts in Kibana.

Refresh from upstream:

```bash
./scripts/update_datadog_integrations_dashboards.sh
```
