// Sign in. Credentials arrive in `args` only. The tab stays open on success and on a TOTP
// challenge: the portal session lives in the tab that signed in, and the integration runs
// every later operation in it (mfa.js continues a challenge there). Only a failed login
// closes it.
async ({ page, context, args }, H) => {
  await H.ensureViewport(page);
  try {
    return await H.login(page, context, args);
  } catch (err) {
    await page.close().catch(() => {});
    throw err;
  }
}
