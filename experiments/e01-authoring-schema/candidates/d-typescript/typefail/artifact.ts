import { Artifact, BackendBinary, IOSApp, acceptIOS } from "../candidate.ts";

acceptIOS(new Artifact<BackendBinary>());
const invalid: Artifact<IOSApp> = new Artifact<BackendBinary>();
void invalid;
