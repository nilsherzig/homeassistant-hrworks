// Sign in. Credentials arrive in `args` only. A TOTP challenge leaves the tab open (the run
// is started with keep_open) so that mfa.js can finish it; every other outcome closes it.
async ({ page, context, args }, H) => {
  await H.ensureViewport(page);
  try {
    const result = await H.login(page, context, args);
    if (!result.mfa_required) await page.close();
    return result;
  } catch (err) {
    await page.close().catch(() => {});
    throw err;
  }
}
