/** Resolve the same public Shared assets that Docker/fixture servers mount for features. */
import { register } from "node:module";
register("./frontend-test-loader.mjs", import.meta.url);
