import {
  API,
  Artifact,
  Endpoint,
  IOSApp,
  OtherAPI,
  acceptIOS,
  composeW1,
  connectOther,
} from "./candidate.ts";

acceptIOS(new Artifact<IOSApp>());
connectOther(new Endpoint<OtherAPI>());
const endpoint: Endpoint<API> = new Endpoint<API>();
void endpoint;
composeW1();
