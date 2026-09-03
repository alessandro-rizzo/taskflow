package candidatea

import (
	"encoding/json"
	"fmt"
	"os"
	"sort"
)

type Argument struct {
	Name     string   `json:"name"`
	Type     string   `json:"type"`
	Enum     []string `json:"enum,omitempty"`
	Default  any      `json:"default,omitempty"`
	Required bool     `json:"required"`
}

type Output struct {
	ID       string `json:"id"`
	Type     string `json:"type"`
	Optional bool   `json:"optional"`
}

type Operation struct {
	ID                   string     `json:"id"`
	Description          string     `json:"description"`
	Arguments            []Argument `json:"arguments"`
	Outputs              []Output   `json:"outputs"`
	RequiredEffects      []string   `json:"required_effects"`
	RequiredCapabilities []string   `json:"required_capabilities"`
	body                 func()
}

type Schema struct {
	DocumentKind   string      `json:"document_kind"`
	FormatVersion  string      `json:"format_version"`
	FixtureID      string      `json:"fixture_id"`
	FixtureVersion string      `json:"fixture_version"`
	Status         string      `json:"status"`
	Operations     []Operation `json:"operations"`
}

type Diagnostic struct {
	Operation string `json:"operation"`
	Path      string `json:"path"`
	Expected  string `json:"expected"`
	Actual    any    `json:"actual"`
	Human     string `json:"human"`
}

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

type TraceOutput struct {
	ID       string `json:"id"`
	From     string `json:"from,omitempty"`
	Type     string `json:"type"`
	Optional bool   `json:"optional"`
}

type TraceWork struct {
	ID       string        `json:"id"`
	Type     string        `json:"type"`
	Consumes []string      `json:"consumes"`
	Produces []TraceOutput `json:"produces"`
}

type TraceAggregate struct {
	ID        string        `json:"id"`
	Type      string        `json:"type"`
	DependsOn []string      `json:"depends_on"`
	Exposes   []TraceOutput `json:"exposes"`
}

type Relation struct {
	From string `json:"from"`
	To   string `json:"to"`
}

type TraceSource struct {
	ID   string `json:"id"`
	Type string `json:"type"`
}

type Trace struct {
	Status               string         `json:"status"`
	Execution            string         `json:"execution"`
	CompositionRule      string         `json:"composition_rule"`
	Source               TraceSource    `json:"source"`
	ChildWork            []TraceWork    `json:"child_work"`
	Aggregate            TraceAggregate `json:"aggregate"`
	TypedHandleRelations []Relation     `json:"typed_handle_relations"`
}

type traceBuilder struct {
	trace Trace
}

func NewTrace() *traceBuilder {
	return &traceBuilder{trace: Trace{
		Status:          "experiment-only-not-plan-ir",
		Execution:       "fake",
		CompositionRule: "dependencies are authored by passing typed handles, not only string identifiers",
		Source:          TraceSource{ID: "source", Type: "Source"},
	}}
}

func (builder *traceBuilder) Source() Handle[Source] { return Handle[Source]{id: "source"} }

func Child[I, O any](builder *traceBuilder, id, outputType string, input Handle[I]) Handle[O] {
	builder.trace.ChildWork = append(builder.trace.ChildWork, TraceWork{
		ID: id, Type: outputType, Consumes: []string{input.id}, Produces: []TraceOutput{},
	})
	builder.trace.TypedHandleRelations = append(builder.trace.TypedHandleRelations, Relation{From: input.id, To: id})
	return Handle[O]{id: id}
}

func Aggregate(builder *traceBuilder, format Handle[Check], tests Handle[Report[GoTests]], lint Handle[Check]) Handle[Check] {
	for _, input := range []string{format.id, tests.id, lint.id} {
		builder.trace.TypedHandleRelations = append(builder.trace.TypedHandleRelations, Relation{From: input, To: "check"})
	}
	builder.trace.Aggregate = TraceAggregate{ID: "check", Type: "Check", DependsOn: []string{format.id, tests.id, lint.id}}
	return Handle[Check]{id: "check"}
}

func RequiredTraceOutput(id string, fromID string, outputType string) TraceOutput {
	return TraceOutput{ID: id, From: fromID, Type: outputType}
}

func OptionalTraceOutput(id string, fromID string, outputType string) TraceOutput {
	return TraceOutput{ID: id, From: fromID, Type: outputType, Optional: true}
}

func (builder *traceBuilder) Finish(outputs ...TraceOutput) Trace {
	builder.trace.Aggregate.Exposes = outputs
	for _, output := range outputs {
		if output.From == "test" {
			for index := range builder.trace.ChildWork {
				if builder.trace.ChildWork[index].ID == "test" {
					produced := output
					produced.From = ""
					builder.trace.ChildWork[index].Produces = []TraceOutput{produced}
				}
			}
		}
	}
	return builder.trace
}

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

func w1Schema() Schema {
	return schema(
		"w1-fast-project-check", "t1-experimental-v1", "experimental",
		Operation{
			ID:          "check",
			Description: "Format check, unit tests, and static analysis, aggregated into one pass/fail Check.",
			Arguments: []Argument{
				{Name: "verbosity", Type: "string", Enum: []string{"quiet", "normal", "verbose"}, Default: "normal"},
				{Name: "changed-only", Type: "boolean", Default: false},
			},
			Outputs: []Output{
				{ID: "test-report", Type: "Report[GoTests]"},
				{ID: "diagnostics", Type: "Report[Diagnostics]", Optional: true},
			},
			RequiredCapabilities: []string{"filesystem-read"},
			body:                 sentinelBody("W1"),
		},
	)
}

// E01-AUTHOR-END

func explicitSchemas() map[string]Schema {
	return map[string]Schema{
		"W1": w1Schema(),
		"W2": schema(
			"w2-cross-target-artifact-pipeline", "t1-w2-experimental-v1", "experimental",
			Operation{ID: "build-and-verify", Description: "Build the backend binary on Linux, run its Go test suite on a compatible Linux worker, and produce a local inspection summary.", Outputs: []Output{{ID: "backend-binary", Type: "Artifact[BackendBinary]"}, {ID: "go-tests-report", Type: "Report[GoTests]"}, {ID: "inspection-summary", Type: "LocalInspection"}}, RequiredCapabilities: []string{"linux-execution-profile"}, body: sentinelBody("W2")},
		),
		"W3": schema(
			"w3-isolated-native-mobile-stack", "t1-w3-fixture-v1-experimental", "experimental",
			Operation{ID: "mobile-e2e", Description: "Bring up a namespace-private Linux API stack, build the iOS app on macOS/Xcode, and run the end-to-end suite against a simulator.", Outputs: []Output{{ID: "mobile-e2e-report", Type: "Report[MobileE2E]"}}, RequiredCapabilities: []string{"linux-execution-profile", "macos-execution-profile", "simulator-session"}, body: sentinelBody("W3")},
		),
		"effect": schema(
			"e01-effect-probe", "e01-effect-probe-v1", "experimental-synthetic",
			Operation{ID: "publish-preview", Description: "Describe a policy-gated release publication without evaluating or authorizing its operation body.", Arguments: []Argument{{Name: "environment", Type: "string", Enum: []string{"staging", "production"}, Required: true}, {Name: "channel", Type: "string", Enum: []string{"beta", "stable"}, Default: "beta"}}, Outputs: []Output{{ID: "published-release", Type: "Effect[PublishedRelease]"}}, RequiredEffects: []string{"publish-release"}, RequiredCapabilities: []string{"network:app-store-connect", "secret:app-store-signing"}, body: sentinelBody("effect")},
		),
	}
}

func schema(id, version, status string, operation Operation) Schema {
	if operation.Arguments == nil {
		operation.Arguments = []Argument{}
	}
	if operation.Outputs == nil {
		operation.Outputs = []Output{}
	}
	if operation.RequiredEffects == nil {
		operation.RequiredEffects = []string{}
	}
	if operation.RequiredCapabilities == nil {
		operation.RequiredCapabilities = []string{}
	}
	return Schema{"schema", "t1-plan-conformance-schema-v1", id, version, status, []Operation{operation}}
}

func sentinelBody(scope string) func() {
	return func() {
		if path := os.Getenv("E01_BODY_SENTINEL"); path != "" {
			_ = os.WriteFile(path, []byte(scope), 0o600)
		}
		panic("E01 operation body evaluated during discovery: " + scope)
	}
}

func Discover(scope string) (Schema, error) {
	schema, ok := explicitSchemas()[scope]
	if !ok {
		return Schema{}, fmt.Errorf("unknown scope %q", scope)
	}
	return schema, nil
}

func Validate(scope string, values map[string]any) *Diagnostic {
	schema, err := Discover(scope)
	if err != nil {
		return &Diagnostic{scope, "$", "known operation", scope, err.Error()}
	}
	op := schema.Operations[0]
	known := map[string]Argument{}
	for _, argument := range op.Arguments {
		known[argument.Name] = argument
	}
	keys := make([]string, 0, len(values))
	for key := range values {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	for _, key := range keys {
		if _, ok := known[key]; !ok {
			return diagnostic(op.ID, key, "known argument", values[key])
		}
	}
	for _, argument := range op.Arguments {
		value, present := values[argument.Name]
		if !present {
			if argument.Required {
				return diagnostic(op.ID, argument.Name, "required "+argument.Type, nil)
			}
			continue
		}
		if argument.Type == "string" {
			if _, ok := value.(string); !ok {
				return diagnostic(op.ID, argument.Name, "string", value)
			}
		}
		if argument.Type == "boolean" {
			if _, ok := value.(bool); !ok {
				return diagnostic(op.ID, argument.Name, "boolean", value)
			}
		}
		if len(argument.Enum) > 0 {
			text, ok := value.(string)
			if ok {
				found := false
				for _, member := range argument.Enum {
					found = found || text == member
				}
				if !found {
					return diagnostic(op.ID, argument.Name, "one of "+fmt.Sprint(argument.Enum), value)
				}
			}
		}
	}
	return nil
}

func diagnostic(operation, path, expected string, actual any) *Diagnostic {
	return &Diagnostic{operation, path, expected, actual, fmt.Sprintf("operation %s argument %s expected %s; got %v", operation, path, expected, actual)}
}

func Encode(value any) ([]byte, error)         { return json.MarshalIndent(value, "", "  ") }
func AcceptIOS(artifact Artifact[IOSApp])      { _ = artifact }
func ConnectOther(endpoint Endpoint[OtherAPI]) { _ = endpoint }
