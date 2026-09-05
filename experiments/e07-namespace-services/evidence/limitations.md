# E07 limitations

- This is same-host, process-level isolation on Darwin, not an OS namespace, VM, simulator, or physical device.
- The macOS consumer is an experiment-local fake relay; no real provider, Internet path, Compose runtime, or shared runtime was exercised.
- Lifecycle durability uses local SQLite with a deliberately short one-second lease; it does not establish distributed consistency or production operating bounds.
- The Python standard-library services are disposable evidence and do not define a production API or package.
