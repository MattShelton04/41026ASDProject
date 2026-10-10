/** Start and decision forms. Controls keep native semantics; validation is ours (`noValidate`). */
import { append, el } from "../browser/index.js";
import { ACTOR_LIMIT, DECISION_NOTE_LIMIT, DEFAULT_MULTI_AGENT_LABELS, humaniseValue } from "./definitions.js";

/** Show or clear one control's accessible error message. */
export function setFieldError(ref, message) {
  if (!ref) return;
  const text = String(message || "");
  ref.error.textContent = text;
  ref.error.hidden = !text;
  for (const control of ref.controls) {
    if (text) control.setAttribute("aria-invalid", "true");
    else control.removeAttribute("aria-invalid");
  }
}

function describedBy(control, ...ids) {
  control.setAttribute("aria-describedby", ids.filter(Boolean).join(" "));
}

function errorNode(id) {
  const node = el("p", "ps-multi-agent__field-error");
  node.id = id;
  node.hidden = true;
  return node;
}

function buildControl(field) {
  if (field.control === "textarea") {
    const control = el("textarea", "ps-multi-agent__control");
    control.rows = 3;
    control.value = String(field.initialValue ?? "");
    return control;
  }
  if (field.control === "select") {
    const control = el("select", "ps-multi-agent__control");
    if (!field.required) {
      const empty = el("option", "", "Not specified");
      empty.value = "";
      append(control, empty);
    }
    for (const value of field.enum) {
      const option = el("option", "", humaniseValue(value));
      option.value = value;
      append(control, option);
    }
    control.value = String(field.initialValue ?? "");
    return control;
  }
  const control = el("input", field.control === "checkbox" ? "ps-multi-agent__checkbox" : "ps-multi-agent__control");
  control.type = field.control;
  if (field.control === "checkbox") { control.checked = field.initialValue === true || field.initialValue === "true"; return control; }
  control.value = String(field.initialValue ?? "");
  if (field.control === "number") {
    control.step = field.type === "integer" ? "1" : "any";
    control.inputMode = field.type === "integer" ? "numeric" : "decimal";
    if (field.minimum !== null) control.min = String(field.minimum);
    if (field.maximum !== null) control.max = String(field.maximum);
  }
  if (field.format === "uuid") {
    control.spellcheck = false;
    control.setAttribute("autocapitalize", "off");
    control.placeholder = "00000000-0000-0000-0000-000000000000";
  }
  if (field.pattern) control.pattern = field.pattern;
  control.autocomplete = "off";
  return control;
}

/**
 * Template-driven start form. Hidden inputs are listed read-only so the person can see
 * what the page supplied, but they are never editable here.
 */
export function buildStartForm({ fields, instanceId, initialInput = {}, labels = DEFAULT_MULTI_AGENT_LABELS }) {
  const form = el("form", "ps-multi-agent__start");
  form.noValidate = true;
  const heading = el("h3", "ps-multi-agent__form-title", labels.startHeading);
  heading.id = `${instanceId}-start-title`;
  form.setAttribute("aria-labelledby", heading.id);
  append(form, heading);
  const refs = new Map();
  const supplied = fields.filter((field) => field.hidden);
  if (supplied.length) {
    const list = el("dl", "ps-multi-agent__supplied");
    for (const field of supplied) {
      const row = el("div");
      append(row, el("dt", "", field.title), el("dd", "", String(initialInput?.[field.name] ?? "Not supplied")));
      append(list, row);
    }
    append(form, list);
  }
  for (const field of fields.filter((item) => !item.hidden)) {
    const id = `${instanceId}-input-${field.name}`;
    const control = buildControl(field);
    control.id = id;
    control.name = field.name;
    if (field.required && field.control !== "checkbox") control.required = true;
    if (field.maxLength && ["text", "textarea", "url"].includes(field.control)) control.maxLength = field.maxLength;
    const wrapper = el("div", `ps-multi-agent__field ps-multi-agent__field--${field.control}`);
    wrapper.dataset.input = field.name;
    const label = el("label", "ps-multi-agent__field-label");
    label.htmlFor = id;
    append(label, el("span", "", field.title));
    // Templates sometimes say "optional" in the title already; do not repeat it.
    if (!field.required && field.control !== "checkbox" && !/optional/i.test(field.title)) append(label, el("span", "ps-multi-agent__optional", " (optional)"));
    const help = field.description || (field.format === "uuid" ? "A UUID, as shown on the record." : "");
    const helpNode = help ? el("p", "ps-multi-agent__field-help", help) : null;
    if (helpNode) helpNode.id = `${id}-help`;
    const error = errorNode(`${id}-error`);
    describedBy(control, helpNode?.id, error.id);
    if (field.control === "checkbox") {
      const row = el("div", "ps-multi-agent__check-row");
      append(row, control, label);
      append(wrapper, row, helpNode, error);
    } else append(wrapper, label, control, helpNode, error);
    append(form, wrapper);
    refs.set(field.name, { field, control, controls: [control], error });
  }
  const problem = el("div", "ps-multi-agent__form-problem");
  const actions = el("div", "ps-multi-agent__actions");
  const submit = el("button", "ps-button ps-button--primary", labels.start);
  submit.type = "submit";
  submit.dataset.action = "start";
  append(actions, submit);
  append(form, problem, actions);
  const values = () => {
    const result = {};
    for (const field of fields) {
      const ref = refs.get(field.name);
      if (!ref) result[field.name] = initialInput?.[field.name];
      else result[field.name] = field.control === "checkbox" ? ref.control.checked : ref.control.value;
    }
    return result;
  };
  return { form, heading, refs, problem, submit, values };
}

/** Decision controls for exactly the actions the run allows. */
export function buildDecisionForm({
  run, options, draft, instanceId, guidance = "", labels = DEFAULT_MULTI_AGENT_LABELS, onChange = () => {},
}) {
  const form = el("form", "ps-multi-agent__decision");
  form.noValidate = true;
  const heading = el("h4", "ps-multi-agent__section-title", labels.decisionHeading);
  heading.id = `${instanceId}-decision-title`;
  form.setAttribute("aria-labelledby", heading.id);
  append(form, heading);
  if (guidance) {
    const note = el("aside", "ps-multi-agent__guidance");
    append(note, el("strong", "", labels.guidance), el("p", "", guidance));
    append(form, note);
  }

  const choices = el("fieldset", "ps-multi-agent__choices");
  append(choices, el("legend", "", "Decision"));
  const decisionError = errorNode(`${instanceId}-decision-error`);
  const radios = options.map((option) => {
    const id = `${instanceId}-decision-${option.action}`;
    const choice = el("div", `ps-multi-agent__choice ps-multi-agent__choice--${option.action}`);
    const radio = el("input", "ps-multi-agent__radio");
    radio.type = "radio";
    radio.name = `${instanceId}-decision`;
    radio.value = option.action;
    radio.id = id;
    radio.checked = draft.decision === option.action;
    const detailId = `${id}-detail`;
    describedBy(radio, detailId, decisionError.id);
    const label = el("label", "ps-multi-agent__choice-label", option.label);
    label.htmlFor = id;
    const detail = el("span", "ps-multi-agent__choice-detail", option.detail);
    detail.id = detailId;
    append(choice, radio, label, detail);
    append(choices, choice);
    return radio;
  });
  append(choices, decisionError);
  append(form, choices);

  const steps = Array.isArray(run?.plan?.steps) ? run.plan.steps : [];
  const accepted = el("fieldset", "ps-multi-agent__accepted");
  append(accepted, el("legend", "", labels.acceptedSteps));
  const acceptedError = errorNode(`${instanceId}-accepted-error`);
  const checkboxes = steps.map((step) => {
    const id = `${instanceId}-accept-${step.id}`;
    const row = el("div", "ps-multi-agent__check-row");
    const box = el("input", "ps-multi-agent__checkbox");
    box.type = "checkbox";
    box.id = id;
    box.value = step.id;
    box.checked = draft.acceptedStepIds.includes(step.id);
    describedBy(box, acceptedError.id);
    const label = el("label", "", `${step.title || humaniseValue(step.id)} (${step.id})`);
    label.htmlFor = id;
    append(row, box, label);
    append(accepted, row);
    return box;
  });
  append(accepted, acceptedError);
  accepted.hidden = draft.decision !== "partial";
  append(form, accepted);

  const noteId = `${instanceId}-decision-note`;
  const noteField = el("div", "ps-multi-agent__field");
  const noteLabel = el("label", "ps-multi-agent__field-label", labels.note);
  noteLabel.htmlFor = noteId;
  const note = el("textarea", "ps-multi-agent__control");
  note.id = noteId;
  note.rows = 4;
  note.maxLength = DECISION_NOTE_LIMIT;
  note.value = draft.note;
  const noteHelp = el("p", "ps-multi-agent__field-help", labels.noteHelp);
  noteHelp.id = `${noteId}-help`;
  const noteError = errorNode(`${noteId}-error`);
  describedBy(note, noteHelp.id, noteError.id);
  append(noteField, noteLabel, note, noteHelp, noteError);

  const actorId = `${instanceId}-decision-actor`;
  const actorField = el("div", "ps-multi-agent__field");
  const actorLabel = el("label", "ps-multi-agent__field-label", labels.actor);
  actorLabel.htmlFor = actorId;
  const actor = el("input", "ps-multi-agent__control");
  actor.id = actorId;
  actor.type = "text";
  actor.required = true;
  actor.maxLength = ACTOR_LIMIT;
  actor.autocomplete = "name";
  actor.value = draft.actor;
  const actorHelp = el("p", "ps-multi-agent__field-help", labels.actorHelp);
  actorHelp.id = `${actorId}-help`;
  const actorError = errorNode(`${actorId}-error`);
  describedBy(actor, actorHelp.id, actorError.id);
  append(actorField, actorLabel, actor, actorHelp, actorError);
  append(form, noteField, actorField);

  const problem = el("div", "ps-multi-agent__form-problem");
  const actions = el("div", "ps-multi-agent__actions");
  const submit = el("button", "ps-button ps-button--primary", labels.submitDecision);
  submit.type = "submit";
  submit.dataset.action = "decide";
  append(actions, submit);
  append(form, problem, actions);

  const sync = () => {
    draft.decision = radios.find((radio) => radio.checked)?.value || "";
    draft.note = note.value;
    draft.actor = actor.value;
    draft.acceptedStepIds = checkboxes.filter((box) => box.checked).map((box) => box.value);
    accepted.hidden = draft.decision !== "partial";
    note.required = Boolean(draft.decision) && draft.decision !== "approve";
    noteLabel.textContent = note.required ? `${labels.note} (required)` : labels.note;
    onChange(draft);
  };
  for (const control of [...radios, ...checkboxes]) control.addEventListener("change", sync);
  for (const control of [note, actor]) control.addEventListener("input", sync);
  note.required = Boolean(draft.decision) && draft.decision !== "approve";
  if (note.required) noteLabel.textContent = `${labels.note} (required)`;

  // Visual order, so validation focuses the first invalid control on the page.
  const refs = {
    decision: { controls: radios, error: decisionError, focus: radios[0] },
    accepted_step_ids: { controls: checkboxes, error: acceptedError, focus: checkboxes[0] },
    note: { controls: [note], error: noteError, focus: note },
    actor: { controls: [actor], error: actorError, focus: actor },
  };
  const controls = [...radios, ...checkboxes, note, actor, submit];
  return { form, heading, refs, problem, submit, controls, sync };
}
