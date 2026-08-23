import { FieldValidationError, createSubmissionGuard, formState, formStateChanged } from "../core/forms.js";

function requestIdSuffix(error) {
  return error?.requestId ? ` Request ID ${error.requestId}.` : "";
}

function fieldLabel(field) {
  return field?.closest?.("label")?.querySelector?.("span")?.textContent?.replace(/\s*\((required|optional)\)\s*$/, "")
    || field?.getAttribute?.("aria-label")
    || field?.name
    || "the highlighted field";
}

function clearFieldError(field) {
  field.setCustomValidity?.("");
  const errorId = field.dataset?.formErrorId;
  if (errorId) document.getElementById(errorId)?.remove();
  if (errorId && field.getAttribute?.("aria-describedby")) {
    const describedBy = field.getAttribute("aria-describedby").split(/\s+/).filter((id) => id && id !== errorId).join(" ");
    if (describedBy) field.setAttribute("aria-describedby", describedBy);
    else field.removeAttribute("aria-describedby");
  }
  if (field.dataset) delete field.dataset.formErrorId;
  field.removeAttribute?.("aria-invalid");
}

function showFieldError(form, fieldName, message) {
  const field = form.elements?.namedItem?.(fieldName) || form.querySelector?.(`[name="${CSS.escape(fieldName)}"]`);
  if (!field) return null;
  clearFieldError(field);
  field.setCustomValidity?.(message);
  field.setAttribute?.("aria-invalid", "true");
  if (field.id && field.insertAdjacentElement) {
    const error = document.createElement("small");
    error.id = `${field.id}-error`;
    error.className = "field-error";
    error.textContent = message;
    field.insertAdjacentElement("afterend", error);
    field.setAttribute("aria-describedby", [field.getAttribute("aria-describedby"), error.id].filter(Boolean).join(" "));
    field.dataset.formErrorId = error.id;
  }
  field.focus?.();
  field.reportValidity?.();
  return field;
}

function setButtonPending(button, pending, progressLabel, original) {
  if (!button) return;
  if (pending) {
    original.text = button.textContent;
    original.minWidth = button.style?.minWidth || "";
    if (button.offsetWidth && button.style) button.style.minWidth = `${Math.ceil(button.offsetWidth)}px`;
    button.textContent = progressLabel;
    button.disabled = true;
    button.setAttribute?.("aria-busy", "true");
  } else {
    button.textContent = original.text;
    button.disabled = false;
    button.removeAttribute?.("aria-busy");
    if (button.style) button.style.minWidth = original.minWidth;
  }
}

export function runDialogForm({
  dialog,
  form,
  submitButton,
  errorHost,
  acceptedValue,
  progressLabel = "Saving…",
  discardMessage = "Discard your unsaved changes?",
  onSubmit,
}) {
  errorHost.textContent = "";
  const initial = formState(form);
  const buttonState = { text: "", minWidth: "" };
  let settled = false;
  let resolveDialog;
  const result = new Promise((resolve) => { resolveDialog = resolve; });

  const finish = (accepted) => {
    if (settled) return;
    settled = true;
    cleanup();
    resolveDialog(accepted);
  };
  const close = (value) => {
    dialog.returnValue = value;
    dialog.close(value);
  };
  const shouldDiscard = () => formStateChanged(initial, formState(form));
  const requestClose = () => {
    if (guard.pending) return;
    if (shouldDiscard() && !window.confirm(discardMessage)) return;
    close("cancel");
  };
  const invalidSummary = () => {
    const invalid = form.querySelector?.(":invalid");
    if (!invalid) return;
    errorHost.textContent = `Please correct ${fieldLabel(invalid)} before continuing.`;
    invalid.focus?.();
    invalid.reportValidity?.();
  };
  const guard = createSubmissionGuard(async () => {
    errorHost.textContent = "";
    if (form.checkValidity && !form.checkValidity()) {
      invalidSummary();
      return false;
    }
    try {
      await onSubmit();
      close(acceptedValue);
      return true;
    } catch (error) {
      if (error instanceof FieldValidationError) showFieldError(form, error.fieldName, error.message);
      errorHost.textContent = error instanceof FieldValidationError
        ? `Please correct ${fieldLabel(form.elements?.namedItem?.(error.fieldName))} before continuing.`
        : `The service could not save your changes. ${error.message}${requestIdSuffix(error)} Your entered values are still here; correct the issue or retry.`;
      if (!(error instanceof FieldValidationError)) {
        errorHost.tabIndex = -1;
        errorHost.focus?.();
      }
      return false;
    }
  }, (pending) => {
    setButtonPending(submitButton, pending, progressLabel, buttonState);
    form.setAttribute?.("aria-busy", String(pending));
    for (const control of form.querySelectorAll?.('[type="submit"][value="cancel"]') || []) control.disabled = pending;
  });

  const submitted = (event) => {
    event.preventDefault();
    if (event.submitter?.value !== acceptedValue) requestClose();
    else guard.submit();
  };
  const cancelled = (event) => {
    event.preventDefault();
    requestClose();
  };
  const closed = () => finish(dialog.returnValue === acceptedValue);
  const input = (event) => {
    if (event.target?.dataset?.formErrorId || event.target?.validationMessage) clearFieldError(event.target);
  };
  const cleanup = () => {
    form.removeEventListener("submit", submitted);
    form.removeEventListener("input", input);
    dialog.removeEventListener("cancel", cancelled);
    dialog.removeEventListener("close", closed);
  };

  form.addEventListener("submit", submitted);
  form.addEventListener("input", input);
  dialog.addEventListener("cancel", cancelled);
  dialog.addEventListener("close", closed);
  dialog.returnValue = "";
  dialog.showModal();
  form.querySelector?.("input:not(:disabled), select:not(:disabled), textarea:not(:disabled), button:not(:disabled)")?.focus?.();
  return result;
}
