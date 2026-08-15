export function waitForDialog(dialog, acceptedValue) {
  return new Promise((resolve) => {
    const closed = () => {
      dialog.removeEventListener("close", closed);
      resolve(dialog.returnValue === acceptedValue);
    };
    dialog.addEventListener("close", closed);
  });
}
