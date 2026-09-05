# E08 evidence limitations

- SSH/Linux is real OpenSSH into a real ARM64 Linux container, but both controller and VM share one physical Mac; this is not external-host or WAN evidence.
- Locality does not prove WAN latency, jitter, packet loss, NAT/firewall behavior, provider provisioning/quotas, external credential mediation, physical host loss, or cross-host recovery.
- Thirty SSH rows covering permanent worker loss, cancellation while running, output collection/digest failure, cleanup timeout, and caller lease expiry remain explicitly `state-machine-analysis-local-linux`; four disconnect groups prove durable replay across fresh connections only, not a precisely timed mid-flight socket cut.
- The two worker identities share one container and kernel. Their resume evidence proves identity separation and compatible replay, not recovery on a second physical host.
- The macOS leg remains a non-mutating stub and proves no Xcode, simulator, VM, reset, or native-host behavior.
- Transport framing, reconnect-token authentication/expiry, provider APIs, and all experiment types remain disposable and unstabilized.
