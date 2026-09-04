package candidatejson

import "sort"

// Handle is an experiment-local typed value. The producer is deliberately
// private: passing handles into inputs is what derives both plan references
// and dependency edges for the disposable W2/W3 builders.
type Handle[T any] struct {
	id       string
	producer string
	typeName string
}

type handleRef interface{ reference() (string, string) }

func (handle Handle[T]) reference() (string, string) { return handle.id, handle.producer }
func root[T any](id, typeName string) Handle[T]      { return Handle[T]{id: id, typeName: typeName} }
func produced[T any](id, typeName, producer string) Handle[T] {
	return Handle[T]{id: id, typeName: typeName, producer: producer}
}
func declaration[T any](handle Handle[T], optional bool) Artifact {
	return Artifact{ID: handle.id, Type: handle.typeName, Optional: optional}
}
func inputs(values ...handleRef) (needs, consumes []string) {
	needs = []string{}
	consumes = []string{}
	seenNeeds := map[string]bool{}
	seenConsumes := map[string]bool{}
	for _, value := range values {
		id, producer := value.reference()
		if !seenConsumes[id] {
			consumes = append(consumes, id)
			seenConsumes[id] = true
		}
		if producer != "" && !seenNeeds[producer] {
			needs = append(needs, producer)
			seenNeeds[producer] = true
		}
	}
	sort.Strings(needs)
	sort.Strings(consumes)
	return needs, consumes
}

type sourceTree struct{}
type backendBinary struct{}
type goTestsReport struct{}
type localInspection struct{}
type apiService struct{}
type apiEndpoint struct{}
type iosApp struct{}
type simulatorSession struct{}
type mobileReport struct{}
