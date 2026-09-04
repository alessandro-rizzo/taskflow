package candidatejson

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"sort"
	"strconv"
	"strings"
	"unicode/utf8"
)

type setRule struct{ objectID string }

var setLike = map[string]setRule{
	"$.nodes":                                {objectID: "id"},
	"$.artifacts":                            {objectID: "id"},
	"$.services":                             {objectID: "id"},
	"$.secrets":                              {objectID: "id"},
	"$.effects":                              {objectID: "id"},
	"$.nodes[*].needs":                       {},
	"$.nodes[*].consumes":                    {},
	"$.nodes[*].produces":                    {},
	"$.nodes[*].planning_condition.patterns": {},
	"$.nodes[*].planning_condition.exclude_patterns": {},
	"$.nodes[*].cache_policy.key_inputs":             {},
}

func Decode(raw []byte) (any, error) {
	if !utf8.Valid(raw) {
		return nil, fmt.Errorf("$ invalid UTF-8")
	}
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.UseNumber()
	value, err := decodeValue(decoder, "$")
	if err != nil {
		return nil, err
	}
	if _, err := decoder.Token(); err != io.EOF {
		if err == nil {
			return nil, fmt.Errorf("$ multiple JSON values")
		}
		return nil, fmt.Errorf("$ trailing data: %w", err)
	}
	return value, nil
}

func decodeValue(decoder *json.Decoder, path string) (any, error) {
	token, err := decoder.Token()
	if err != nil {
		return nil, fmt.Errorf("%s: %w", path, err)
	}
	switch value := token.(type) {
	case json.Delim:
		switch value {
		case '{':
			object := map[string]any{}
			for decoder.More() {
				keyToken, err := decoder.Token()
				if err != nil {
					return nil, fmt.Errorf("%s: %w", path, err)
				}
				key, ok := keyToken.(string)
				if !ok {
					return nil, fmt.Errorf("%s object member is not a string", path)
				}
				if _, exists := object[key]; exists {
					return nil, fmt.Errorf("%s.%s duplicate object member", path, key)
				}
				child, err := decodeValue(decoder, path+"."+key)
				if err != nil {
					return nil, err
				}
				object[key] = child
			}
			if end, err := decoder.Token(); err != nil || end != json.Delim('}') {
				return nil, fmt.Errorf("%s unterminated object", path)
			}
			return object, nil
		case '[':
			array := []any{}
			for decoder.More() {
				child, err := decodeValue(decoder, path+"[*]")
				if err != nil {
					return nil, err
				}
				array = append(array, child)
			}
			if end, err := decoder.Token(); err != nil || end != json.Delim(']') {
				return nil, fmt.Errorf("%s unterminated array", path)
			}
			return array, nil
		default:
			return nil, fmt.Errorf("%s unexpected delimiter", path)
		}
	case json.Number:
		text := value.String()
		if text == "-0" || strings.ContainsAny(text, ".eE+") {
			return nil, fmt.Errorf("%s non-canonical integer %q", path, text)
		}
		parsed, err := strconv.ParseInt(text, 10, 64)
		if err != nil {
			return nil, fmt.Errorf("%s integer outside signed 64-bit range: %q", path, text)
		}
		return parsed, nil
	case string, bool, nil:
		return value, nil
	default:
		return nil, fmt.Errorf("%s unsupported JSON value", path)
	}
}

func Canonicalize(raw []byte) ([]byte, error) {
	value, err := Decode(raw)
	if err != nil {
		return nil, err
	}
	normalized, err := normalize(value, "$")
	if err != nil {
		return nil, err
	}
	var output bytes.Buffer
	if err := writeCanonical(&output, normalized); err != nil {
		return nil, err
	}
	return output.Bytes(), nil
}

func normalize(value any, path string) (any, error) {
	switch typed := value.(type) {
	case map[string]any:
		out := make(map[string]any, len(typed))
		for key, child := range typed {
			normalized, err := normalize(child, path+"."+key)
			if err != nil {
				return nil, err
			}
			out[key] = normalized
		}
		return out, nil
	case []any:
		out := make([]any, len(typed))
		for index, child := range typed {
			normalized, err := normalize(child, path+"[*]")
			if err != nil {
				return nil, err
			}
			out[index] = normalized
		}
		rule, isSet := setLike[path]
		if !isSet {
			return out, nil
		}
		seen := map[string]bool{}
		for index, child := range out {
			var key string
			if rule.objectID != "" {
				object, ok := child.(map[string]any)
				if !ok {
					return nil, fmt.Errorf("%s[%d] must be an object", path, index)
				}
				key, ok = object[rule.objectID].(string)
				if !ok || key == "" {
					return nil, fmt.Errorf("%s[%d].%s must be a non-empty string", path, index, rule.objectID)
				}
			} else {
				var ok bool
				key, ok = child.(string)
				if !ok {
					return nil, fmt.Errorf("%s[%d] must be a string", path, index)
				}
			}
			if seen[key] {
				return nil, fmt.Errorf("%s duplicate set member %q", path, key)
			}
			seen[key] = true
		}
		keyOf := func(child any) string {
			if rule.objectID == "" {
				return child.(string)
			}
			return child.(map[string]any)[rule.objectID].(string)
		}
		sort.SliceStable(out, func(i, j int) bool { return keyOf(out[i]) < keyOf(out[j]) })
		return out, nil
	default:
		return value, nil
	}
}

func writeCanonical(output *bytes.Buffer, value any) error {
	switch typed := value.(type) {
	case nil:
		output.WriteString("null")
	case bool:
		if typed {
			output.WriteString("true")
		} else {
			output.WriteString("false")
		}
	case int64:
		output.WriteString(strconv.FormatInt(typed, 10))
	case string:
		writeString(output, typed)
	case []any:
		output.WriteByte('[')
		for index, child := range typed {
			if index > 0 {
				output.WriteByte(',')
			}
			if err := writeCanonical(output, child); err != nil {
				return err
			}
		}
		output.WriteByte(']')
	case map[string]any:
		keys := make([]string, 0, len(typed))
		for key := range typed {
			keys = append(keys, key)
		}
		sort.Strings(keys)
		output.WriteByte('{')
		for index, key := range keys {
			if index > 0 {
				output.WriteByte(',')
			}
			writeString(output, key)
			output.WriteByte(':')
			if err := writeCanonical(output, typed[key]); err != nil {
				return err
			}
		}
		output.WriteByte('}')
	default:
		return fmt.Errorf("unsupported canonical value %T", value)
	}
	return nil
}

func writeString(output *bytes.Buffer, value string) {
	output.WriteByte('"')
	for _, runeValue := range value {
		switch runeValue {
		case '"':
			output.WriteString(`\"`)
		case '\\':
			output.WriteString(`\\`)
		case '\b':
			output.WriteString(`\b`)
		case '\f':
			output.WriteString(`\f`)
		case '\n':
			output.WriteString(`\n`)
		case '\r':
			output.WriteString(`\r`)
		case '\t':
			output.WriteString(`\t`)
		default:
			if runeValue < 0x20 {
				fmt.Fprintf(output, `\u%04x`, runeValue)
			} else {
				output.WriteRune(runeValue)
			}
		}
	}
	output.WriteByte('"')
}

func Digest(canonical []byte) string {
	digest := sha256.Sum256(canonical)
	return hex.EncodeToString(digest[:])
}
