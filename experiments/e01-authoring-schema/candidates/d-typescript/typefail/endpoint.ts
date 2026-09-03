import { API, Endpoint, OtherAPI, connectOther } from "../candidate.ts";

connectOther(new Endpoint<API>());
const invalid: Endpoint<OtherAPI> = new Endpoint<API>();
void invalid;
