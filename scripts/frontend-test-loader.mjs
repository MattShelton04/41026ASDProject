/** Test-only ESM aliases. Never install this loader in a production browser or service. */
const root = new URL("../", import.meta.url);
const publicAssets = /^(student-[1-5]\/frontend\/)(browser|ai-chat|mapping)\/(.+)$/;

export async function resolve(specifier, context, nextResolve) {
  if (context.parentURL?.startsWith(root.href) && specifier.startsWith(".")) {
    const target = new URL(specifier, context.parentURL);
    if (target.href.startsWith(root.href)) {
      const match = target.href.slice(root.href.length).match(publicAssets);
      if (match) return nextResolve(new URL(`shared/frontend/${match[2]}/${match[3]}`, root).href, context);
    }
  }
  return nextResolve(specifier, context);
}
