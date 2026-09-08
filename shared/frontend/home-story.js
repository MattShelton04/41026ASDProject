/** Progressive enhancement of authored illustrations; no property data is implied. */
export function nearestStoryStep(steps, viewportHeight, focusLine = viewportHeight * 0.48) {
  let nearest = null;
  let distance = Infinity;
  for (const step of steps) {
    const rect = step.getBoundingClientRect();
    const next = Math.abs(rect.top + rect.height / 2 - focusLine);
    if (next < distance) { nearest = step; distance = next; }
  }
  return nearest;
}

export function createHomeStory(root, features, { host = window } = {}) {
  const story = root.querySelector('.feature-story');
  if (!story) return { destroy() {} };
  const visual = story.querySelector('.story-visual');
  const label = story.querySelector('#scene-label');
  const steps = [...story.querySelectorAll('[data-step]')];
  const buttons = [...story.querySelectorAll('[data-scene-target]')];
  const reducedMotion = host.matchMedia('(prefers-reduced-motion: reduce)');
  const mobile = host.matchMedia('(max-width: 700px)');
  let frame = null;
  let destroyed = false;
  for (const action of story.querySelectorAll('[data-story-area]')) {
    const feature = features[Number(action.dataset.storyArea)];
    if (feature?.href) action.href = feature.href;
    else {
      action.removeAttribute('href');
      action.textContent = feature?.implemented ? 'Currently disabled' : 'Coming later';
      action.classList.add('story-unavailable');
    }
  }
  function update() {
    frame = null;
    if (destroyed) return;
    const viewportHeight = host.innerHeight;
    const focusLine = mobile.matches ? viewportHeight * 0.74 : viewportHeight * 0.48;
    const active = nearestStoryStep(steps, viewportHeight, focusLine);
    if (active) {
      visual.dataset.scene = active.dataset.step;
      label.textContent = active.querySelector('.ps-eyebrow').textContent;
      for (const button of buttons) button.setAttribute('aria-pressed', String(button.dataset.sceneTarget === active.dataset.step));
    }
    const hero = root.querySelector('.map-panel');
    if (hero) {
      const offset = reducedMotion.matches || mobile.matches ? 0 : Math.min(90, Math.max(-90, hero.getBoundingClientRect().top * 0.08));
      hero.style.setProperty('--parallax', `${offset}px`);
    }
  }
  function schedule() {
    if (frame === null && !destroyed) frame = host.requestAnimationFrame(update);
  }
  const listeners = buttons.map((button) => {
    const listener = () => {
      const step = steps.find((item) => item.dataset.step === button.dataset.sceneTarget);
      step?.scrollIntoView({ block: 'center', behavior: reducedMotion.matches ? 'instant' : 'smooth' });
    };
    button.addEventListener('click', listener);
    return [button, listener];
  });
  host.addEventListener('scroll', schedule, { passive: true });
  host.addEventListener('resize', schedule, { passive: true });
  reducedMotion.addEventListener('change', schedule);
  update();
  return {
    destroy() {
      destroyed = true;
      host.removeEventListener('scroll', schedule);
      host.removeEventListener('resize', schedule);
      reducedMotion.removeEventListener('change', schedule);
      if (frame !== null) host.cancelAnimationFrame(frame);
      for (const [button, listener] of listeners) button.removeEventListener('click', listener);
    },
  };
}
