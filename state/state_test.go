package state_test

import (
	"testing"
	"time"

	"github.com/alessandro-rizzo/taskflow/state"
)

func TestApplyDoesNotMutateUncommittedSnapshot(t *testing.T) {
	t.Parallel()
	original := state.Snapshot{
		Revision: 1,
		Run: state.Run{
			ID: "run", Status: state.Running,
			Steps: map[string]state.Step{
				"step": {ID: "step", Status: state.Pending},
			},
		},
	}
	transition := state.StepStatus(
		state.Step{ID: "step", Status: state.Succeeded},
		time.Unix(10, 0),
	)
	transition.Schema = state.SchemaVersion
	transition.Revision = 2
	applied, err := state.Apply(original, transition)
	if err != nil {
		t.Fatal(err)
	}
	if applied.Run.Steps["step"].Status != state.Succeeded {
		t.Fatalf("applied status = %s", applied.Run.Steps["step"].Status)
	}
	if original.Run.Steps["step"].Status != state.Pending {
		t.Fatalf("original snapshot mutated to %s before commit", original.Run.Steps["step"].Status)
	}
}
