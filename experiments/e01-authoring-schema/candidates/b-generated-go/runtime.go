package candidateb

import (
	"fmt"
	"sort"
)

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

func RequiredTraceOutput(id, fromID, outputType string) TraceOutput {
	return TraceOutput{ID: id, From: fromID, Type: outputType}
}

func OptionalTraceOutput(id, fromID, outputType string) TraceOutput {
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

func Validate(scope string, values map[string]any) *Diagnostic {
	schema, err := Discover(scope)
	if err != nil {
		return diag(scope, "$", "known operation", scope)
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
			return diag(op.ID, key, "known argument", values[key])
		}
	}
	for _, argument := range op.Arguments {
		value, exists := values[argument.Name]
		if !exists {
			if argument.Required {
				return diag(op.ID, argument.Name, "required "+argument.Type, nil)
			}
			continue
		}
		if argument.Type == "string" {
			if _, ok := value.(string); !ok {
				return diag(op.ID, argument.Name, "string", value)
			}
		}
		if argument.Type == "boolean" {
			if _, ok := value.(bool); !ok {
				return diag(op.ID, argument.Name, "boolean", value)
			}
		}
		if len(argument.Enum) > 0 {
			text, ok := value.(string)
			if ok {
				found := false
				for _, member := range argument.Enum {
					found = found || member == text
				}
				if !found {
					return diag(op.ID, argument.Name, "one of "+fmt.Sprint(argument.Enum), value)
				}
			}
		}
	}
	return nil
}
func diag(operation, path, expected string, actual any) *Diagnostic {
	return &Diagnostic{operation, path, expected, actual, fmt.Sprintf("operation %s argument %s expected %s; got %v", operation, path, expected, actual)}
}
