// Enter the authenticator code in the tab login.js left open (run with `tab`). A rejected
// code keeps the tab for another try; success closes it.
async ({ page, args }, H) => {
  await H.ensureViewport(page);
  const result = await H.mfa(page, args.code);
  await page.close();
  return result;
}
