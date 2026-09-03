package candidateb

import (
	_ "embed"
	"encoding/json"
	"fmt"
	"go/ast"
	"go/format"
	"go/parser"
	"go/token"
	"reflect"
	"strconv"
	"strings"
)

//go:embed project.go
var authoredSource string

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

func Generate() (map[string]Schema, error) { return GenerateFrom("project.go", authoredSource) }
func GenerateFrom(filename, source string) (map[string]Schema, error) {
	fset := token.NewFileSet()
	file, err := parser.ParseFile(fset, filename, source, parser.ParseComments)
	if err != nil {
		return nil, err
	}
	result := map[string]Schema{}
	for _, declaration := range file.Decls {
		generic, ok := declaration.(*ast.GenDecl)
		if !ok || generic.Tok != token.TYPE || generic.Doc == nil {
			continue
		}
		lines := strings.Split(generic.Doc.Text(), "\n")
		meta := map[string]string{}
		for _, line := range lines {
			if strings.HasPrefix(line, "E01:scope ") {
				for _, item := range strings.Fields(strings.TrimPrefix(line, "E01:scope ")) {
					pair := strings.SplitN(item, "=", 2)
					if len(pair) == 1 {
						meta["scope"] = pair[0]
					} else {
						meta[pair[0]] = pair[1]
					}
				}
			}
			if strings.HasPrefix(line, "E01:description ") {
				meta["description"] = strings.TrimPrefix(line, "E01:description ")
			}
			if strings.HasPrefix(line, "E01:capabilities ") {
				meta["capabilities"] = strings.TrimPrefix(line, "E01:capabilities ")
			}
			if strings.HasPrefix(line, "E01:effects ") {
				meta["effects"] = strings.TrimPrefix(line, "E01:effects ")
			}
		}
		if meta["scope"] == "" {
			continue
		}
		spec := generic.Specs[0].(*ast.TypeSpec)
		structure, ok := spec.Type.(*ast.StructType)
		if !ok {
			return nil, fmt.Errorf("%s:%d: E01 operation must be a struct", filename, fset.Position(spec.Pos()).Line)
		}
		op := Operation{ID: meta["operation"], Description: meta["description"], Arguments: []Argument{}, Outputs: []Output{}, RequiredEffects: split(meta["effects"]), RequiredCapabilities: split(meta["capabilities"]), body: sentinelBody(meta["scope"])}
		for _, field := range structure.Fields.List {
			if field.Tag == nil {
				continue
			}
			raw, err := strconv.Unquote(field.Tag.Value)
			if err != nil {
				return nil, fmt.Errorf("%s:%d: invalid authored tag: %w", filename, fset.Position(field.Pos()).Line, err)
			}
			tag := reflect.StructTag(raw).Get("e01")
			if tag == "" {
				continue
			}
			values := parseTag(tag)
			var rendered strings.Builder
			if err := format.Node(&rendered, fset, field.Type); err != nil {
				return nil, err
			}
			schemaType := rendered.String()
			if schemaType == "bool" {
				schemaType = "boolean"
			}
			parts := strings.Split(tag, ",")
			if parts[0] == "argument" {
				argument := Argument{Name: values["name"], Type: schemaType, Enum: split(values["enum"]), Required: values["required"] == "true"}
				if value, ok := values["default"]; ok {
					if schemaType == "boolean" {
						argument.Default, _ = strconv.ParseBool(value)
					} else {
						argument.Default = value
					}
				}
				op.Arguments = append(op.Arguments, argument)
			} else if parts[0] == "output" {
				if values["type"] != "" {
					schemaType = values["type"]
				}
				op.Outputs = append(op.Outputs, Output{values["id"], schemaType, values["optional"] == "true"})
			} else {
				return nil, fmt.Errorf("%s:%d: unknown E01 declaration kind %q", filename, fset.Position(field.Pos()).Line, parts[0])
			}
		}
		result[meta["scope"]] = Schema{"schema", "t1-plan-conformance-schema-v1", meta["fixture"], meta["version"], meta["status"], []Operation{op}}
	}
	if len(result) != 4 {
		return nil, fmt.Errorf("%s: expected four E01 declarations, got %d", filename, len(result))
	}
	return result, nil
}
func split(value string) []string {
	if value == "" {
		return []string{}
	}
	return strings.Split(value, "|")
}
func parseTag(tag string) map[string]string {
	result := map[string]string{}
	for _, item := range strings.Split(tag, ",")[1:] {
		pair := strings.SplitN(item, "=", 2)
		if len(pair) == 2 {
			result[pair[0]] = pair[1]
		}
	}
	return result
}
func Discover(scope string) (Schema, error) {
	schemas, err := Generate()
	if err != nil {
		return Schema{}, err
	}
	value, ok := schemas[scope]
	if !ok {
		return Schema{}, fmt.Errorf("unknown scope %q", scope)
	}
	return value, nil
}
func Encode(value any) ([]byte, error) { return json.MarshalIndent(value, "", "  ") }
