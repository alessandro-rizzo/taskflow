package candidateb

import "os"

type Handle[T any] struct{ id string }
type Artifact[T any] struct{ Handle[T] }
type Endpoint[T any] struct{ marker func() T }
type Source struct{}
type Check struct{}
type Report[T any] struct{}
type GoTests struct{}
type Diagnostics struct{}
type BackendBinary struct{}
type IOSApp struct{}
type API struct{}
type OtherAPI struct{}
type MobileE2E struct{}
type PublishedRelease struct{}
type LocalInspection struct{}

// E01-AUTHOR-BEGIN
func ComposeW1() Trace {
	trace := NewTrace()
	source := trace.Source()
	format := Child[Source, Check](trace, "format", "Check", source)
	tests := Child[Source, Report[GoTests]](trace, "test", "Report[GoTests]", source)
	lint := Child[Source, Check](trace, "lint", "Check", source)
	check := Aggregate(trace, format, tests, lint)
	return trace.Finish(
		RequiredTraceOutput("test-report", tests.id, "Report[GoTests]"),
		OptionalTraceOutput("diagnostics", check.id, "Report[Diagnostics]"),
	)
}

// E01:scope W1 fixture=w1-fast-project-check version=t1-experimental-v1 status=experimental operation=check
// E01:description Format check, unit tests, and static analysis, aggregated into one pass/fail Check.
// E01:capabilities filesystem-read
type W1Operation struct {
	Verbosity   string              `e01:"argument,name=verbosity,enum=quiet|normal|verbose,default=normal"`
	ChangedOnly bool                `e01:"argument,name=changed-only,default=false"`
	TestReport  Report[GoTests]     `e01:"output,id=test-report"`
	Diagnostics Report[Diagnostics] `e01:"output,id=diagnostics,optional=true"`
}

// E01-AUTHOR-END

// E01:scope W2 fixture=w2-cross-target-artifact-pipeline version=t1-w2-experimental-v1 status=experimental operation=build-and-verify
// E01:description Build the backend binary on Linux, run its Go test suite on a compatible Linux worker, and produce a local inspection summary.
// E01:capabilities linux-execution-profile
type W2Operation struct {
	Backend    Artifact[BackendBinary] `e01:"output,id=backend-binary"`
	Tests      Report[GoTests]         `e01:"output,id=go-tests-report"`
	Inspection LocalInspection         `e01:"output,id=inspection-summary"`
}

// E01:scope W3 fixture=w3-isolated-native-mobile-stack version=t1-w3-fixture-v1-experimental status=experimental operation=mobile-e2e
// E01:description Bring up a namespace-private Linux API stack, build the iOS app on macOS/Xcode, and run the end-to-end suite against a simulator.
// E01:capabilities linux-execution-profile|macos-execution-profile|simulator-session
type W3Operation struct {
	Report Report[MobileE2E] `e01:"output,id=mobile-e2e-report"`
}

// E01:scope effect fixture=e01-effect-probe version=e01-effect-probe-v1 status=experimental-synthetic operation=publish-preview
// E01:description Describe a policy-gated release publication without evaluating or authorizing its operation body.
// E01:capabilities network:app-store-connect|secret:app-store-signing
// E01:effects publish-release
type EffectOperation struct {
	Environment string                 `e01:"argument,name=environment,enum=staging|production,required=true"`
	Channel     string                 `e01:"argument,name=channel,enum=beta|stable,default=beta"`
	Published   EffectPublishedRelease `e01:"output,id=published-release,type=Effect[PublishedRelease]"`
}

type EffectPublishedRelease struct{}

func sentinelBody(scope string) func() {
	return func() {
		if path := os.Getenv("E01_BODY_SENTINEL"); path != "" {
			_ = os.WriteFile(path, []byte(scope), 0o600)
		}
		panic("E01 operation body evaluated during discovery: " + scope)
	}
}

func AcceptIOS(artifact Artifact[IOSApp])      { _ = artifact }
func ConnectOther(endpoint Endpoint[OtherAPI]) { _ = endpoint }
