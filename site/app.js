document.querySelectorAll('[data-copy]').forEach((button) => {
  button.addEventListener('click', async () => {
    const original = button.textContent;
    try {
      await navigator.clipboard.writeText(button.dataset.copy);
      button.textContent = 'Copied ✓';
    } catch {
      button.textContent = 'Copy failed';
    }
    setTimeout(() => { button.textContent = original; }, 1800);
  });
});
