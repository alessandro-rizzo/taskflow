package candidatec

import (
	"encoding/json"
	"fmt"
	"os"
	"reflect"
	"sort"
	"strconv"
	"strings"
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
	body                 any
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
type Effect[T any] struct{}
type GoTests struct{}
type Diagnostics struct{}
type BackendBinary struct{}
type IOSApp struct{}
type API struct{}
type OtherAPI struct{}
type MobileE2E struct{}
type PublishedRelease struct{}
type LocalInspection struct{}

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

func Child[I, O any](builder *traceBuilder, id string, input Handle[I]) Handle[O] {
	builder.trace.ChildWork = append(builder.trace.ChildWork, TraceWork{
		ID: id, Type: typeName[O](), Consumes: []string{input.id}, Produces: []TraceOutput{},
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

func RequiredOutput[T any](id string, from Handle[T]) TraceOutput {
	return TraceOutput{ID: id, From: from.id, Type: typeName[T]()}
}

func OptionalOutput[T any](id string, from Handle[Check]) TraceOutput {
	return TraceOutput{ID: id, From: from.id, Type: typeName[T](), Optional: true}
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

type definition struct {
	Scope                string
	FixtureID            string
	FixtureVersion       string
	Status               string
	OperationID          string
	Description          string
	RequiredEffects      []string
	RequiredCapabilities []string
	Body                 any
}

// E01-AUTHOR-BEGIN
func ComposeW1() Trace {
	trace := NewTrace()
	source := trace.Source()
	format := Child[Source, Check](trace, "format", source)
	tests := Child[Source, Report[GoTests]](trace, "test", source)
	lint := Child[Source, Check](trace, "lint", source)
	check := Aggregate(trace, format, tests, lint)
	return trace.Finish(
		RequiredOutput("test-report", tests),
		OptionalOutput[Report[Diagnostics]]("diagnostics", check),
	)
}

type W1Arguments struct {
	Verbosity   string `e01:"name=verbosity,enum=quiet|normal|verbose,default=normal"`
	ChangedOnly bool   `e01:"name=changed-only,default=false"`
}

type W1Outputs struct {
	TestReport  Report[GoTests]     `e01:"id=test-report"`
	Diagnostics Report[Diagnostics] `e01:"id=diagnostics,optional=true"`
}

var w1 = definition{
	Scope:                "W1",
	FixtureID:            "w1-fast-project-check",
	FixtureVersion:       "t1-experimental-v1",
	Status:               "experimental",
	OperationID:          "check",
	Description:          "Format check, unit tests, and static analysis, aggregated into one pass/fail Check.",
	RequiredCapabilities: []string{"filesystem-read"},
	Body:                 neverRun[W1Arguments, W1Outputs]("W1"),
}

// E01-AUTHOR-END

type NoArguments struct{}
type W2Outputs struct {
	Backend    Artifact[BackendBinary] `e01:"id=backend-binary"`
	Tests      Report[GoTests]         `e01:"id=go-tests-report"`
	Inspection LocalInspection         `e01:"id=inspection-summary"`
}
type W3Outputs struct {
	Report Report[MobileE2E] `e01:"id=mobile-e2e-report"`
}
type EffectArguments struct {
	Environment string `e01:"name=environment,enum=staging|production,required=true"`
	Channel     string `e01:"name=channel,enum=beta|stable,default=beta"`
}
type EffectOutputs struct {
	Published Effect[PublishedRelease] `e01:"id=published-release"`
}

func definitions() map[string]definition {
	return map[string]definition{
		"W1": w1,
		"W2": {
			Scope: "W2", FixtureID: "w2-cross-target-artifact-pipeline", FixtureVersion: "t1-w2-experimental-v1", Status: "experimental",
			OperationID: "build-and-verify", Description: "Build the backend binary on Linux, run its Go test suite on a compatible Linux worker, and produce a local inspection summary.",
			RequiredCapabilities: []string{"linux-execution-profile"}, Body: neverRun[NoArguments, W2Outputs]("W2"),
		},
		"W3": {
			Scope: "W3", FixtureID: "w3-isolated-native-mobile-stack", FixtureVersion: "t1-w3-fixture-v1-experimental", Status: "experimental",
			OperationID: "mobile-e2e", Description: "Bring up a namespace-private Linux API stack, build the iOS app on macOS/Xcode, and run the end-to-end suite against a simulator.",
			RequiredCapabilities: []string{"linux-execution-profile", "macos-execution-profile", "simulator-session"}, Body: neverRun[NoArguments, W3Outputs]("W3"),
		},
		"effect": {
			Scope: "effect", FixtureID: "e01-effect-probe", FixtureVersion: "e01-effect-probe-v1", Status: "experimental-synthetic",
			OperationID: "publish-preview", Description: "Describe a policy-gated release publication without evaluating or authorizing its operation body.",
			RequiredEffects: []string{"publish-release"}, RequiredCapabilities: []string{"network:app-store-connect", "secret:app-store-signing"},
			Body: neverRun[EffectArguments, EffectOutputs]("effect"),
		},
	}
}

func neverRun[A, O any](scope string) func(A) O {
	return func(A) O {
		if path := os.Getenv("E01_BODY_SENTINEL"); path != "" {
			_ = os.WriteFile(path, []byte(scope), 0o600)
		}
		panic("E01 operation body evaluated during discovery: " + scope)
	}
}

func Discover(scope string) (Schema, error) {
	item, ok := definitions()[scope]
	if !ok {
		return Schema{}, fmt.Errorf("unknown scope %q", scope)
	}
	function := reflect.TypeOf(item.Body)
	if function.Kind() != reflect.Func || function.NumIn() != 1 || function.NumOut() != 1 {
		return Schema{}, fmt.Errorf("operation %s must have one argument and one output struct", item.OperationID)
	}
	arguments, err := reflectArguments(function.In(0))
	if err != nil {
		return Schema{}, fmt.Errorf("operation %s arguments: %w", item.OperationID, err)
	}
	outputs, err := reflectOutputs(function.Out(0))
	if err != nil {
		return Schema{}, fmt.Errorf("operation %s outputs: %w", item.OperationID, err)
	}
	operation := Operation{
		ID: item.OperationID, Description: item.Description, Arguments: arguments, Outputs: outputs,
		RequiredEffects: nonNil(item.RequiredEffects), RequiredCapabilities: nonNil(item.RequiredCapabilities), body: item.Body,
	}
	return Schema{
		DocumentKind: "schema", FormatVersion: "t1-plan-conformance-schema-v1", FixtureID: item.FixtureID,
		FixtureVersion: item.FixtureVersion, Status: item.Status, Operations: []Operation{operation},
	}, nil
}

func reflectArguments(value reflect.Type) ([]Argument, error) {
	if value.Kind() != reflect.Struct {
		return nil, fmt.Errorf("%s is not an argument struct", value)
	}
	arguments := make([]Argument, 0, value.NumField())
	for index := 0; index < value.NumField(); index++ {
		field := value.Field(index)
		options := parseTag(field.Tag.Get("e01"))
		name := options["name"]
		if name == "" {
			return nil, fmt.Errorf("%s.%s missing e01 name", value.Name(), field.Name)
		}
		argument := Argument{Name: name, Type: scalarName(field.Type)}
		if members := options["enum"]; members != "" {
			argument.Enum = strings.Split(members, "|")
		}
		if raw, found := options["default"]; found {
			argument.Default = parseDefault(raw, field.Type)
		}
		argument.Required = options["required"] == "true"
		arguments = append(arguments, argument)
	}
	return arguments, nil
}

func reflectOutputs(value reflect.Type) ([]Output, error) {
	if value.Kind() != reflect.Struct {
		return nil, fmt.Errorf("%s is not an output struct", value)
	}
	outputs := make([]Output, 0, value.NumField())
	for index := 0; index < value.NumField(); index++ {
		field := value.Field(index)
		options := parseTag(field.Tag.Get("e01"))
		id := options["id"]
		if id == "" {
			return nil, fmt.Errorf("%s.%s missing e01 id", value.Name(), field.Name)
		}
		outputs = append(outputs, Output{ID: id, Type: reflectedTypeName(field.Type), Optional: options["optional"] == "true"})
	}
	return outputs, nil
}

func parseTag(raw string) map[string]string {
	values := map[string]string{}
	for _, part := range strings.Split(raw, ",") {
		if part == "" {
			continue
		}
		pieces := strings.SplitN(part, "=", 2)
		if len(pieces) == 2 {
			values[pieces[0]] = pieces[1]
		}
	}
	return values
}

func parseDefault(raw string, value reflect.Type) any {
	if value.Kind() == reflect.Bool {
		parsed, _ := strconv.ParseBool(raw)
		return parsed
	}
	return raw
}

func scalarName(value reflect.Type) string {
	switch value.Kind() {
	case reflect.String:
		return "string"
	case reflect.Bool:
		return "boolean"
	default:
		return value.Name()
	}
}

func reflectedTypeName(value reflect.Type) string {
	name := value.Name()
	name = strings.ReplaceAll(name, "e01/candidatec.", "")
	return name
}

func typeName[T any]() string {
	return reflectedTypeName(reflect.TypeOf((*T)(nil)).Elem())
}

func nonNil(values []string) []string {
	if values == nil {
		return []string{}
	}
	return values
}

func Validate(scope string, values map[string]any) *Diagnostic {
	schema, err := Discover(scope)
	if err != nil {
		return &Diagnostic{Operation: scope, Path: "$", Expected: "known operation", Actual: scope, Human: err.Error()}
	}
	operation := schema.Operations[0]
	known := map[string]Argument{}
	for _, argument := range operation.Arguments {
		known[argument.Name] = argument
	}
	keys := make([]string, 0, len(values))
	for key := range values {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	for _, key := range keys {
		if _, found := known[key]; !found {
			return diagnostic(operation.ID, key, "known argument", values[key])
		}
	}
	for _, argument := range operation.Arguments {
		value, present := values[argument.Name]
		if !present {
			if argument.Required {
				return diagnostic(operation.ID, argument.Name, "required "+argument.Type, nil)
			}
			continue
		}
		if argument.Type == "string" {
			if _, ok := value.(string); !ok {
				return diagnostic(operation.ID, argument.Name, "string", value)
			}
		}
		if argument.Type == "boolean" {
			if _, ok := value.(bool); !ok {
				return diagnostic(operation.ID, argument.Name, "boolean", value)
			}
		}
		if len(argument.Enum) > 0 {
			text, ok := value.(string)
			if ok && !contains(argument.Enum, text) {
				return diagnostic(operation.ID, argument.Name, "one of "+fmt.Sprint(argument.Enum), value)
			}
		}
	}
	return nil
}

func contains(values []string, target string) bool {
	for _, value := range values {
		if value == target {
			return true
		}
	}
	return false
}

func diagnostic(operation, path, expected string, actual any) *Diagnostic {
	return &Diagnostic{
		Operation: operation, Path: path, Expected: expected, Actual: actual,
		Human: fmt.Sprintf("operation %s argument %s expected %s; got %v", operation, path, expected, actual),
	}
}

func Encode(value any) ([]byte, error)         { return json.MarshalIndent(value, "", "  ") }
func AcceptIOS(artifact Artifact[IOSApp])      { _ = artifact }
func ConnectOther(endpoint Endpoint[OtherAPI]) { _ = endpoint }
