const featureOutput = document.querySelector("#feature-output");
const agentOutput = document.querySelector("#agent-output");
const profileSelect = document.querySelector("#model-profile");

function render(target, value) {
  target.textContent = typeof value === "string" ? value : JSON.stringify(value, null, 2);
}

async function jsonRequest(url, options = {}) {
  const response = await fetch(url, options);
  const body = await response.json();
  if (!response.ok) {
    throw new Error(`${response.status}: ${body.detail || body.code || "request failed"}`);
  }
  return { response, body };
}

async function loadProfiles() {
  try {
    const { body } = await jsonRequest("/api/ai/model-profiles");
    for (const profile of body.profiles) {
      const model = body.models.find((item) => item.key === profile.model_key);
      const option = document.createElement("option");
      option.value = profile.key;
      option.selected = profile.key === body.default_profile;
      option.textContent = `${profile.key} — ${model.ollama_tag} (${profile.context_tokens} ctx)`;
      profileSelect.append(option);
    }
    render(agentOutput, `Ready. Default profile: ${body.default_profile}`);
  } catch (error) {
    render(agentOutput, `Could not load model registry: ${error.message}`);
  }
}

document.querySelector("#search-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const query = document.querySelector("#search-query").value;
    const { body } = await jsonRequest("/api/feature/records.search.v1", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query }),
    });
    render(featureOutput, body);
  } catch (error) {
    render(featureOutput, error.message);
  }
});

document.querySelector("#create-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const title = document.querySelector("#record-title").value;
    const idempotencyKey = `${crypto.randomUUID()}:call:${crypto.randomUUID()}`;
    const { body } = await jsonRequest("/api/feature/records.create.v1", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Idempotency-Key": idempotencyKey,
      },
      body: JSON.stringify({ title }),
    });
    render(featureOutput, body);
  } catch (error) {
    render(featureOutput, error.message);
  }
});

document.querySelector("#agent-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    render(agentOutput, "Submitting agent run…");
    const objective = document.querySelector("#objective").value;
    const { response, body } = await jsonRequest("/api/ai/agent-runs", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Idempotency-Key": crypto.randomUUID(),
      },
      body: JSON.stringify({
        feature_key: "student-1-integration-test",
        objective,
        model_profile: profileSelect.value,
      }),
    });
    const location = response.headers.get("Location") || `/api/v1/agent-runs/${body.id}`;
    const proxiedLocation = location.replace(/^\/api\/v1\//, "/api/ai/");
    for (let attempt = 0; attempt < 120; attempt += 1) {
      const current = await jsonRequest(proxiedLocation);
      render(agentOutput, current.body);
      const status = current.body.run.status;
      if (["succeeded", "failed", "cancelled", "review_required"].includes(status)) {
        return;
      }
      await new Promise((resolve) => setTimeout(resolve, 1000));
    }
    throw new Error("run did not finish within 120 seconds");
  } catch (error) {
    render(agentOutput, error.message);
  }
});

loadProfiles();
