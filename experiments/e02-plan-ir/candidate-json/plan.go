package candidatejson

import (
	"fmt"
	"sort"

	candidateb "e01/candidateb"
)

const PlanFormatVersion = "t1-plan-conformance-plan-v2"

type Plan struct {
	DocumentKind   string     `json:"document_kind"`
	FormatVersion  string     `json:"format_version"`
	FixtureID      string     `json:"fixture_id"`
	FixtureVersion string     `json:"fixture_version"`
	Status         string     `json:"status"`
	Nodes          []Node     `json:"nodes"`
	Artifacts      []Artifact `json:"artifacts"`
	Services       []Service  `json:"services,omitempty"`
	Secrets        []Secret   `json:"secrets,omitempty"`
	Effects        []Effect   `json:"effects,omitempty"`
}

type Node struct {
	ID                string           `json:"id"`
	Needs             []string         `json:"needs"`
	Consumes          []string         `json:"consumes"`
	Produces          []string         `json:"produces"`
	PlanningCondition Condition        `json:"planning_condition"`
	OutcomeCondition  Condition        `json:"outcome_condition"`
	Resources         Resources        `json:"resources"`
	ExecutionProfile  ExecutionProfile `json:"execution_profile"`
	CachePolicy       CachePolicy      `json:"cache_policy"`
}

type Condition struct {
	Type            string   `json:"type"`
	Patterns        []string `json:"patterns,omitempty"`
	ExcludePatterns []string `json:"exclude_patterns,omitempty"`
}

type Resources struct {
	CPUMillicores int64 `json:"cpu_millicores"`
	MemoryMiB     int64 `json:"memory_mib"`
}

type ExecutionProfile struct {
	OS            string `json:"os"`
	Toolchain     string `json:"toolchain"`
	ProfileDigest string `json:"profile_digest,omitempty"`
	ProfileID     string `json:"profile_id,omitempty"`
	TargetRole    string `json:"target_role,omitempty"`
}

type CachePolicy struct {
	Mode      string   `json:"mode"`
	KeyInputs []string `json:"key_inputs,omitempty"`
}

type Artifact struct {
	ID       string `json:"id"`
	Type     string `json:"type"`
	Optional bool   `json:"optional"`
}

type Service struct {
	ID    string `json:"id"`
	Name  string `json:"name"`
	Route string `json:"route"`
}

type Secret struct {
	ID         string `json:"id"`
	Capability string `json:"capability"`
	ResolvedBy string `json:"resolved_by"`
}

type Effect struct {
	ID              string `json:"id"`
	Kind            string `json:"kind"`
	Target          string `json:"target"`
	IdempotencyKey  string `json:"idempotency_key"`
	AuthorizedActor string `json:"authorized_actor"`
}

func always() Condition { return Condition{Type: "always"} }
func none() CachePolicy { return CachePolicy{Mode: "none"} }
func cached(inputs ...string) CachePolicy {
	return CachePolicy{Mode: "content-addressed", KeyInputs: inputs}
}

func W1() (Plan, error) {
	trace := candidateb.ComposeW1()
	if trace.Execution != "fake" || len(trace.TypedHandleRelations) != 6 {
		return Plan{}, fmt.Errorf("unexpected E01 Candidate B trace boundary")
	}
	needs := map[string][]string{}
	for _, relation := range trace.TypedHandleRelations {
		if relation.From != trace.Source.ID {
			needs[relation.To] = append(needs[relation.To], relation.From)
		}
	}
	for id := range needs {
		sort.Strings(needs[id])
	}
	return Plan{
		DocumentKind: "plan", FormatVersion: PlanFormatVersion,
		FixtureID: "w1-fast-project-check", FixtureVersion: "t1-experimental-v1", Status: "experimental",
		Nodes: []Node{
			{ID: "format", Needs: []string{}, Consumes: []string{"source-tree"}, Produces: []string{}, PlanningCondition: Condition{Type: "changed-paths", Patterns: []string{"**/*.go"}}, OutcomeCondition: always(), Resources: Resources{250, 128}, ExecutionProfile: ExecutionProfile{OS: "any", Toolchain: "go1.25.12"}, CachePolicy: cached("source-tree")},
			{ID: "test", Needs: []string{}, Consumes: []string{"source-tree"}, Produces: []string{"test-report"}, PlanningCondition: Condition{Type: "changed-paths", Patterns: []string{"**/*.go"}}, OutcomeCondition: always(), Resources: Resources{500, 256}, ExecutionProfile: ExecutionProfile{OS: "any", Toolchain: "go1.25.12"}, CachePolicy: cached("source-tree")},
			{ID: "lint", Needs: []string{}, Consumes: []string{"source-tree"}, Produces: []string{}, PlanningCondition: Condition{Type: "changed-paths", Patterns: []string{"**/*.go"}, ExcludePatterns: []string{"**/*_test.go"}}, OutcomeCondition: always(), Resources: Resources{250, 128}, ExecutionProfile: ExecutionProfile{OS: "any", Toolchain: "go1.25.12"}, CachePolicy: cached("source-tree")},
			{ID: "check", Needs: needs["check"], Consumes: []string{}, Produces: []string{}, PlanningCondition: always(), OutcomeCondition: Condition{Type: "all-upstream-pass"}, Resources: Resources{}, ExecutionProfile: ExecutionProfile{OS: "any", Toolchain: "none"}, CachePolicy: none()},
		},
		Artifacts: []Artifact{{ID: "source-tree", Type: "Tree"}, {ID: "test-report", Type: "Report[GoTests]"}},
	}, nil
}

func W2() Plan {
	source := root[sourceTree]("source-tree", "Tree")
	backend := produced[backendBinary]("backend-binary", "Artifact[BackendBinary]", "build")
	tests := produced[goTestsReport]("go-tests-report", "Report[GoTests]", "test")
	inspection := produced[localInspection]("inspection-summary", "LocalInspection", "inspect")
	buildNeeds, buildConsumes := inputs(source)
	testNeeds, testConsumes := inputs(backend)
	inspectNeeds, inspectConsumes := inputs(backend)
	profile := ExecutionProfile{OS: "linux", Toolchain: "go1.25.12", TargetRole: "linux-build", ProfileID: "linux-go1.25-amd64-example", ProfileDigest: "sha256:1b1e6c1b7c5b0e8f7d2c1f5a3e9c4b6a0d7f2e8c1a5b3d9f6c0e4a2b8d1f5c3e"}
	return Plan{DocumentKind: "plan", FormatVersion: PlanFormatVersion, FixtureID: "w2-cross-target-artifact-pipeline", FixtureVersion: "t1-w2-experimental-v1", Status: "experimental",
		Nodes: []Node{
			{ID: "build", Needs: buildNeeds, Consumes: buildConsumes, Produces: []string{backend.id}, PlanningCondition: always(), OutcomeCondition: always(), Resources: Resources{1000, 1024}, ExecutionProfile: profile, CachePolicy: cached(source.id, "execution_profile")},
			{ID: "test", Needs: testNeeds, Consumes: testConsumes, Produces: []string{tests.id}, PlanningCondition: always(), OutcomeCondition: always(), Resources: Resources{500, 512}, ExecutionProfile: ExecutionProfile{OS: "linux", Toolchain: "go1.25.12", TargetRole: "linux-test", ProfileID: profile.ProfileID, ProfileDigest: profile.ProfileDigest}, CachePolicy: cached(backend.id)},
			{ID: "inspect", Needs: inspectNeeds, Consumes: inspectConsumes, Produces: []string{inspection.id}, PlanningCondition: always(), OutcomeCondition: always(), Resources: Resources{100, 64}, ExecutionProfile: ExecutionProfile{OS: "any", Toolchain: "none", TargetRole: "local-inspect"}, CachePolicy: none()},
		},
		Artifacts: []Artifact{declaration(source, false), declaration(backend, false), declaration(tests, false), declaration(inspection, false)},
	}
}

func W3() Plan {
	source := root[sourceTree]("source-tree", "Tree")
	service := produced[apiService]("linux-api-service", "Service[API]", "linux-api-build")
	endpoint := produced[apiEndpoint]("api-endpoint", "Endpoint[API]", "linux-api-build")
	app := produced[iosApp]("ios-app", "Artifact[IOSApp]", "macos-xcode-build")
	simulator := root[simulatorSession]("simulator-session", "SimulatorSession")
	report := produced[mobileReport]("mobile-e2e-report", "Report[MobileE2E]", "mobile-e2e")
	linuxNeeds, linuxConsumes := inputs(source)
	macNeeds, macConsumes := inputs(source)
	e2eNeeds, e2eConsumes := inputs(endpoint, app, simulator)
	return Plan{DocumentKind: "plan", FormatVersion: PlanFormatVersion, FixtureID: "w3-isolated-native-mobile-stack", FixtureVersion: "t1-w3-fixture-v1-experimental", Status: "experimental",
		Nodes: []Node{
			{ID: "linux-api-build", Needs: linuxNeeds, Consumes: linuxConsumes, Produces: []string{service.id, endpoint.id}, PlanningCondition: always(), OutcomeCondition: always(), Resources: Resources{500, 512}, ExecutionProfile: ExecutionProfile{OS: "linux", Toolchain: "go1.25.12"}, CachePolicy: cached(source.id)},
			{ID: "macos-xcode-build", Needs: macNeeds, Consumes: macConsumes, Produces: []string{app.id}, PlanningCondition: always(), OutcomeCondition: always(), Resources: Resources{2000, 4096}, ExecutionProfile: ExecutionProfile{OS: "macos", Toolchain: "xcode16"}, CachePolicy: cached(source.id)},
			{ID: "mobile-e2e", Needs: e2eNeeds, Consumes: e2eConsumes, Produces: []string{report.id}, PlanningCondition: always(), OutcomeCondition: always(), Resources: Resources{1000, 2048}, ExecutionProfile: ExecutionProfile{OS: "macos", Toolchain: "simulator"}, CachePolicy: none()},
		},
		Artifacts: []Artifact{declaration(source, false), declaration(service, false), declaration(endpoint, false), declaration(app, false), declaration(simulator, false), declaration(report, false)},
	}
}

func Synthetic() Plan {
	return Plan{DocumentKind: "plan", FormatVersion: PlanFormatVersion, FixtureID: "synthetic", FixtureVersion: "t1-plan-conformance-synthetic-v1", Status: "experimental",
		Nodes: []Node{
			{ID: "build", Needs: []string{}, Consumes: []string{"source-tree"}, Produces: []string{"release-binary"}, PlanningCondition: Condition{Type: "changed-paths", Patterns: []string{"**/*.go"}}, OutcomeCondition: always(), Resources: Resources{1000, 1024}, ExecutionProfile: ExecutionProfile{OS: "linux", Toolchain: "go1.25.12"}, CachePolicy: cached("source-tree")},
			{ID: "sign", Needs: []string{"build"}, Consumes: []string{"release-binary"}, Produces: []string{"signed-binary"}, PlanningCondition: always(), OutcomeCondition: Condition{Type: "conditional"}, Resources: Resources{250, 128}, ExecutionProfile: ExecutionProfile{OS: "linux", Toolchain: "cosign"}, CachePolicy: none()},
			{ID: "publish", Needs: []string{"sign"}, Consumes: []string{"signed-binary"}, Produces: []string{"release-manifest"}, PlanningCondition: always(), OutcomeCondition: always(), Resources: Resources{100, 64}, ExecutionProfile: ExecutionProfile{OS: "any", Toolchain: "none"}, CachePolicy: none()},
		},
		Artifacts: []Artifact{{ID: "source-tree", Type: "Tree"}, {ID: "release-binary", Type: "Artifact[BackendBinary]"}, {ID: "signed-binary", Type: "Artifact[SignedBackendBinary]"}, {ID: "release-manifest", Type: "Report[ReleaseManifest]", Optional: true}},
		Secrets:   []Secret{{ID: "signing-key", Capability: "code-signing-key", ResolvedBy: "daemon"}},
		Services:  []Service{{ID: "artifact-registry-endpoint", Name: "artifact-registry", Route: "authorized-external"}},
		Effects:   []Effect{{ID: "publish-release", Kind: "publish", Target: "artifact-registry-endpoint", IdempotencyKey: "release-manifest-digest", AuthorizedActor: "release-bot"}},
	}
}

func Shape(platform string) (Plan, error) {
	switch platform {
	case "ios":
		return W3(), nil
	case "android":
		plan := W3()
		plan.FixtureID = "shape-android"
		plan.FixtureVersion = "e02-shape-probe-v1"
		for index := range plan.Nodes {
			if plan.Nodes[index].ID == "macos-xcode-build" {
				plan.Nodes[index].ID = "android-build"
				plan.Nodes[index].ExecutionProfile = ExecutionProfile{OS: "linux", Toolchain: "android-sdk"}
				plan.Nodes[index].Produces = []string{"android-app"}
			}
			if plan.Nodes[index].ID == "mobile-e2e" {
				plan.Nodes[index].Needs = []string{"android-build", "linux-api-build"}
				plan.Nodes[index].Consumes = []string{"android-app", "api-endpoint", "emulator-session"}
				plan.Nodes[index].ExecutionProfile = ExecutionProfile{OS: "linux", Toolchain: "emulator"}
			}
		}
		for index := range plan.Artifacts {
			switch plan.Artifacts[index].ID {
			case "ios-app":
				plan.Artifacts[index] = Artifact{ID: "android-app", Type: "Artifact[AndroidApp]"}
			case "simulator-session":
				plan.Artifacts[index] = Artifact{ID: "emulator-session", Type: "EmulatorSession"}
			}
		}
		return plan, nil
	default:
		return Plan{}, fmt.Errorf("platform must be ios or android")
	}
}

func Large(nodes int) Plan {
	plan := Plan{DocumentKind: "plan", FormatVersion: PlanFormatVersion, FixtureID: "large-graph", FixtureVersion: "e02-large-v1", Status: "experimental", Artifacts: []Artifact{{ID: "source-tree", Type: "Tree"}}}
	plan.Nodes = make([]Node, 0, nodes)
	for index := 0; index < nodes; index++ {
		id := fmt.Sprintf("node-%05d", index)
		needs := []string{}
		if index > 0 {
			needs = []string{fmt.Sprintf("node-%05d", index-1)}
		}
		plan.Nodes = append(plan.Nodes, Node{ID: id, Needs: needs, Consumes: []string{"source-tree"}, Produces: []string{}, PlanningCondition: always(), OutcomeCondition: always(), Resources: Resources{100, 64}, ExecutionProfile: ExecutionProfile{OS: "any", Toolchain: "none"}, CachePolicy: cached("source-tree")})
	}
	return plan
}
