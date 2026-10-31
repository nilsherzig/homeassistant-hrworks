// Checks that runs work and the browser is reachable. Touches no portal page.
async ({ page, browser }, H) => {
  await H.ensureViewport(page);
  return { browser_version: browser.version() };
}
