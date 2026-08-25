import { FieldValidationError, createSubmissionGuard, formState, formStateChanged } from "../core/forms.js?v=18";

const activeDialogs = new WeakMap();
const semanticValidators = new WeakMap();
const documentModalCounts = new WeakMap();

function openModal(dialog, initialFocus) {
  const documentNode = dialog.ownerDocument || globalThis.document;
  const returnTarget = documentNode?.activeElement || null;
  if (documentNode?.body) {
    documentModalCounts.set(documentNode, (documentModalCounts.get(documentNode) || 0) + 1);
    documentNode.body.classList.add("ps-modal-open");
  }
  let released = false;
  const release = () => {
    if (released) return;
    released = true;
    if (documentNode?.body) {
      const next = Math.max(0, (documentModalCounts.get(documentNode) || 1) - 1);
      if (next) documentModalCounts.set(documentNode, next);
      else {
        documentModalCounts.delete(documentNode);
        documentNode.body.classList.remove("ps-modal-open");
      }
    }
    queueMicrotask(() => {
      if (returnTarget?.isConnected !== false) returnTarget?.focus?.();
    });
  };
  dialog.addEventListener("close", release, { once: true });
  try {
    dialog.showModal();
  } catch (error) {
    release();
    throw error;
  }
  queueMicrotask(() => {
    const target = typeof initialFocus === "string" ? dialog.querySelector?.(initialFocus) : initialFocus;
    if (dialog.open) target?.focus?.();
  });
}

function requestIdSuffix(error) {
  return error?.requestId ? ` Request ID ${error.requestId}.` : "";
}

function fieldLabel(field) {
  return field?.closest?.("label")?.querySelector?.("span")?.textContent?.replace(/\s*\((required|optional)\)\s*$/, "")
    || field?.getAttribute?.("aria-label")
    || field?.name
    || "the highlighted field";
}

function clearFieldError(field, { clearValidity = true } = {}) {
  if (clearValidity) field.setCustomValidity?.("");
  const errorId = field.dataset?.formErrorId;
  if (errorId) document.getElementById(errorId)?.remove();
  if (errorId && field.getAttribute?.("aria-describedby")) {
    const describedBy = field.getAttribute("aria-describedby").split(/\s+/).filter((id) => id && id !== errorId).join(" ");
    if (describedBy) field.setAttribute("aria-describedby", describedBy);
    else field.removeAttribute("aria-describedby");
  }
  if (field.dataset) delete field.dataset.formErrorId;
  if (field.dataset) delete field.dataset.semanticError;
  semanticValidators.delete(field);
  field.removeAttribute?.("aria-invalid");
}

function showFieldError(form, fieldName, message, { custom = true, report = true, validateValue = null } = {}) {
  const field = form.elements?.namedItem?.(fieldName) || form.querySelector?.(`[name="${CSS.escape(fieldName)}"]`);
  if (!field) return null;
  clearFieldError(field, { clearValidity: custom });
  if (custom) {
    field.setCustomValidity?.(message);
    if (field.dataset) field.dataset.semanticError = "true";
    if (validateValue) semanticValidators.set(field, validateValue);
  }
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
  if (report) field.reportValidity?.();
  return field;
}

export function presentFormError(form, errorHost, error) {
  if (error instanceof FieldValidationError) {
    const field = showFieldError(form, error.fieldName, error.message, { validateValue: error.validateValue });
    errorHost.textContent = `Please correct ${fieldLabel(field)} before continuing.`;
    return field;
  }
  errorHost.textContent = `The service could not save your changes. ${error.message}${requestIdSuffix(error)} Your entered values are still here; correct the issue or retry.`;
  errorHost.tabIndex = -1;
  errorHost.focus?.();
  return null;
}

export function requestActiveDialogClose(dialog, { onDiscardDecision = null } = {}) {
  const controller = activeDialogs.get(dialog);
  if (!controller) return true;
  return controller.requestClose({ onDiscardDecision });
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
  confirmDiscard = null,
  initialFocus = "input:not(:disabled), select:not(:disabled), textarea:not(:disabled)",
  onSubmit,
}) {
  if (dialog.open || activeDialogs.has(dialog)) throw new Error("This dialog already has an active form controller.");
  errorHost.textContent = "";
  const initial = formState(form);
  const buttonState = { text: "", minWidth: "" };
  let settled = false;
  let discardPending = false;
  let discardDecisionListener = null;
  let resolveDialog;
  const result = new Promise((resolve) => { resolveDialog = resolve; });

  const controller = {
    requestClose: (options) => requestClose(options),
  };
  const isCurrent = () => activeDialogs.get(dialog) === controller;
  const finish = (accepted) => {
    if (settled) return;
    settled = true;
    cleanup();
    if (isCurrent()) activeDialogs.delete(dialog);
    resolveDialog(accepted);
  };
  const close = (value) => {
    if (!isCurrent()) return;
    dialog.returnValue = value;
    dialog.close(value);
  };
  const shouldDiscard = () => formStateChanged(initial, formState(form));
  const requestClose = ({ onDiscardDecision = null } = {}) => {
    if (guard.pending) return false;
    if (shouldDiscard()) {
      if (onDiscardDecision) discardDecisionListener = onDiscardDecision;
      if (!confirmDiscard) {
        const listener = discardDecisionListener;
        discardDecisionListener = null;
        listener?.(false);
        errorHost.textContent = "Keep editing or use the provided discard action before closing this form.";
        return false;
      }
      if (!discardPending) {
        discardPending = true;
        Promise.resolve()
          .then(() => confirmDiscard(discardMessage))
          .then((confirmed) => {
            discardPending = false;
            const listener = discardDecisionListener;
            discardDecisionListener = null;
            if (confirmed && isCurrent() && !guard.pending) close("cancel");
            listener?.(Boolean(confirmed));
          })
          .catch(() => {
            discardPending = false;
            const listener = discardDecisionListener;
            discardDecisionListener = null;
            listener?.(false);
            if (isCurrent()) errorHost.textContent = "The discard confirmation could not open. Your changes are still here.";
          });
      }
      return false;
    }
    close("cancel");
    return true;
  };
  const invalidSummary = () => {
    const invalid = form.querySelector?.(":invalid");
    if (!invalid) return;
    errorHost.textContent = `Please correct ${fieldLabel(invalid)} before continuing.`;
    invalid.focus?.();
    invalid.reportValidity?.();
  };
  const guard = createSubmissionGuard(async () => {
    if (!isCurrent()) return false;
    errorHost.textContent = "";
    const valid = form.reportValidity ? form.reportValidity() : form.checkValidity ? form.checkValidity() : true;
    if (!valid) {
      invalidSummary();
      return false;
    }
    try {
      await onSubmit();
      if (!isCurrent()) return false;
      close(acceptedValue);
      return true;
    } catch (error) {
      if (!isCurrent()) return false;
      presentFormError(form, errorHost, error);
      return false;
    }
  }, (pending) => {
    if (!isCurrent()) return;
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
  const invalidated = (event) => {
    if (!isCurrent()) return;
    const field = event.target;
    field.setAttribute?.("aria-invalid", "true");
    if (!field.dataset?.formErrorId && field.validationMessage) showFieldError(form, field.name, field.validationMessage, { custom: false, report: false });
    if (!errorHost.textContent) errorHost.textContent = `Please correct ${fieldLabel(field)} before continuing.`;
  };
  const input = (event) => {
    const field = event.target;
    if (!field?.matches?.("input, select, textarea")) return;
    const semanticFields = Array.from(form.querySelectorAll?.("[data-semantic-error]") || []);
    if (semanticFields.length) {
      for (const semanticField of semanticFields) {
        semanticField.setCustomValidity?.("");
        if (!semanticField.checkValidity?.()) {
          const message = semanticField.validationMessage;
          clearFieldError(semanticField, { clearValidity: false });
          if (message) showFieldError(form, semanticField.name, message, { custom: false, report: false });
          continue;
        }
        const validateValue = semanticValidators.get(semanticField);
        let valid = false;
        try { valid = Boolean(validateValue?.(semanticField.value, form)); } catch { valid = false; }
        if (valid) clearFieldError(semanticField, { clearValidity: false });
      }
      if (!form.querySelector?.(":invalid") && !form.querySelector?.("[data-semantic-error]")) errorHost.textContent = "";
      if (semanticFields.includes(field)) return;
    }
    if (field.dataset?.formErrorId) clearFieldError(field);
    if (!field.checkValidity?.()) {
      field.setAttribute?.("aria-invalid", "true");
      if (field.validationMessage) showFieldError(form, field.name, field.validationMessage, { custom: false, report: false });
    } else {
      clearFieldError(field, { clearValidity: false });
      if (!form.querySelector?.(":invalid")) errorHost.textContent = "";
    }
  };
  const cleanup = () => {
    form.removeEventListener("submit", submitted);
    form.removeEventListener("input", input);
    form.removeEventListener("invalid", invalidated, true);
    dialog.removeEventListener("cancel", cancelled);
    dialog.removeEventListener("close", closed);
  };

  form.addEventListener("submit", submitted);
  form.addEventListener("input", input);
  form.addEventListener("invalid", invalidated, true);
  dialog.addEventListener("cancel", cancelled);
  dialog.addEventListener("close", closed);
  activeDialogs.set(dialog, controller);
  dialog.returnValue = "";
  openModal(dialog, initialFocus);
  return result;
}
