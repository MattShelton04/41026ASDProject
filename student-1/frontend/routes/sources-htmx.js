const FRAGMENT_BASE = "/fragments/data-platform/v1/sources";

function formState(form) {
  return JSON.stringify(Array.from(new FormData(form).entries()));
}

function sourceContent(form) {
  return form?.querySelector("[data-source-editor], [data-source-delete]");
}

export function createSourceHtmxRoute({ view, entityDialog, actionDialog, confirmDiscard, announce, showToast }) {
  const active = new Map();

  function openSourceDialog(dialog, form, status = 200) {
    const previous = active.get(dialog);
    const editor = form.querySelector("[data-source-editor]");
    const initial = status >= 400 && previous?.initial ? previous.initial : formState(form);
    active.set(dialog, { form, initial, pending: false });
    if (!dialog.open) dialog.showModal();
    queueMicrotask(() => {
      const invalid = form.querySelector('[aria-invalid="true"]');
      const alert = form.querySelector('.form-error[role="alert"]:not(:empty)');
      (invalid || alert || editor?.querySelector("input:not([type='hidden']), select, textarea") || form.querySelector("button"))?.focus();
    });
  }

  function closeSourceDialog(dialog) {
    active.delete(dialog);
    if (dialog.open) dialog.close("cancel");
  }

  function requestClose(dialog, { onDiscardDecision = null } = {}) {
    const controller = active.get(dialog);
    if (!controller) return true;
    if (controller.pending) return false;
    const dirty = controller.form.querySelector("[data-source-editor]")
      && controller.initial !== formState(controller.form);
    if (!dirty) {
      closeSourceDialog(dialog);
      onDiscardDecision?.(true);
      return true;
    }
    Promise.resolve(confirmDiscard("Discard your unsaved source changes?"))
      .then((confirmed) => {
        if (confirmed && active.get(dialog) === controller) closeSourceDialog(dialog);
        onDiscardDecision?.(Boolean(confirmed));
      })
      .catch(() => onDiscardDecision?.(false));
    return false;
  }

  function handleDialogSubmit(event) {
    const form = event.currentTarget;
    if (!sourceContent(form)) return;
    event.preventDefault();
    const dialog = form.closest("dialog");
    if (event.submitter?.value === "cancel") requestClose(dialog);
    else if (!event.submitter) form.querySelector('[type="submit"][value="save"], [type="submit"][value="confirm"]')?.click();
  }

  for (const dialog of [entityDialog, actionDialog]) {
    dialog.querySelector("form")?.addEventListener("submit", handleDialogSubmit);
    dialog.addEventListener("cancel", (event) => {
      if (!active.has(dialog)) return;
      event.preventDefault();
      requestClose(dialog);
    });
  }

  document.addEventListener("htmx:beforeSwap", (event) => {
    const xhr = event.detail?.xhr;
    if (!xhr || xhr.status < 400) return;
    let path = "";
    try { path = new URL(xhr.responseURL, location.href).pathname; } catch { return; }
    const contentType = xhr.getResponseHeader("Content-Type") || "";
    if (!path.startsWith(FRAGMENT_BASE) || !contentType.startsWith("text/html")) return;
    event.detail.shouldSwap = true;
    event.detail.isError = false;
  });

  document.addEventListener("htmx:beforeRequest", (event) => {
    const dialog = event.detail?.elt?.closest?.("dialog");
    const controller = active.get(dialog);
    if (controller) controller.pending = true;
  });
  document.addEventListener("htmx:afterRequest", (event) => {
    const dialog = event.detail?.elt?.closest?.("dialog");
    const controller = active.get(dialog);
    if (controller) controller.pending = false;
  });
  document.addEventListener("htmx:afterSwap", (event) => {
    const target = event.detail?.target;
    const status = event.detail?.xhr?.status || 200;
    if (target?.id === "entity-form" && target.querySelector("[data-source-editor]")) {
      openSourceDialog(entityDialog, target, status);
    } else if (target?.id === "action-form" && target.querySelector("[data-source-delete]")) {
      openSourceDialog(actionDialog, target, status);
    } else if (target?.id === "source-crud-region") {
      closeSourceDialog(entityDialog);
      closeSourceDialog(actionDialog);
      queueMicrotask(() => {
        const region = document.querySelector("#source-crud-region");
        const hash = region?.dataset.sourceRouteHash;
        if (hash && location.hash !== hash) history.replaceState(null, "", hash);
        const notice = region?.querySelector("[data-source-success]");
        const focusTarget = notice || region?.querySelector("h1, [role='alert']");
        focusTarget?.focus();
      });
    }
  });
  document.addEventListener("propertyscope:source-mutated", (event) => {
    const detail = event.detail || {};
    const message = detail.message || "Source definition updated.";
    showToast(`${message}${detail.requestId ? ` Request ID ${detail.requestId}` : ""}`);
    announce(message);
  });

  function renderSources(id = "") {
    const host = document.createElement("section");
    host.id = "source-crud-region";
    host.className = "stack";
    host.setAttribute("aria-busy", "true");
    host.setAttribute("hx-get", id ? `${FRAGMENT_BASE}/${encodeURIComponent(id)}` : `${FRAGMENT_BASE}${location.hash.includes("?") ? `?${location.hash.split("?")[1]}` : ""}`);
    host.setAttribute("hx-trigger", "load");
    host.setAttribute("hx-target", "this");
    host.setAttribute("hx-swap", "outerHTML");
    const heading = document.createElement("h1");
    heading.textContent = "Data sources";
    const status = document.createElement("p");
    status.setAttribute("role", "status");
    status.textContent = "Loading source definitions…";
    host.append(heading, status);
    view.replaceChildren(host);
    if (!globalThis.htmx) throw new Error("The local HTMX asset could not be loaded.");
    globalThis.htmx.process(host);
  }

  return {
    renderSources,
    requestSourceDialogClose: requestClose,
  };
}
